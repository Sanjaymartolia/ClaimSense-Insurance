"""Extraction agent: packet documents -> typed Claim with a source span for every bill line."""

from __future__ import annotations

import os
import re
from datetime import date

from claimsense.contracts import AgentName, Claim

from .llm import DATA_RULE, as_data, get_llm
from .permissions import ToolBelt
from .services import Services

# Cheap tripwire for the red-team case. The real input guardrail belongs to Tools & Security;
# this only makes sure the graph *notices* and flags it.
INJECTION_PATTERNS = re.compile(
    r"(note to (the )?ai|pre-?approved|ignore (all |the )?(previous|above)|system prompt|"
    r"you are now|approve this claim)",
    re.IGNORECASE,
)

SYSTEM = f"""You extract hospital-claim packets into the Claim schema.
{DATA_RULE}
Rules:
- One BillLine per itemised bill row. Copy the amount exactly; never add or round.
- source.document is the document name; source.start/end are character offsets of the row in that
  document; source.text is the exact substring.
- bill_total is the total printed on the bill, even if it does not equal the sum of the lines.
- patient_pseudonym: copy the patient identifier exactly as written.
- category: pick the closest LineCategory. Use 'consumables' for gloves, masks, syringes, kits."""


def find_injections(documents: dict[str, str]) -> list[str]:
    """The cheap regex tripwire alone. `guardrails.scan_documents` builds on it, so it must stay
    free of guardrail imports. The agent itself uses `detect_injections` (B4)."""
    return [
        f"possible prompt injection in {name}: '{m.group(0)}'"
        for name, text in documents.items()
        for m in [INJECTION_PATTERNS.search(text)]
        if m
    ]


def detect_injections(documents: dict[str, str], claim: Claim | None = None) -> list[str]:
    """B4 + L15: run the Tools & Security input guardrail over every document AND every bill-line
    description, because a packet can carry injected text in either.

    The check is `input_guardrails.classify_injection_fast`: `guardrails.scan_text` (normalised
    text, words spelt out letter by letter, Hinglish, Devanagari) plus the input module's own
    patterns. With CLAIMSENSE_GUARD_LLM=1 in real mode, a text no pattern flags also goes to the
    guard model (`guardrails.classify_injection_llm`; costs money, off by default).

    Each issue reads `possible prompt injection in <where>: '<cue>'`, the prefix the eval adapter
    and the fraud agent's `extraction: ...` flag already rely on. One issue per place: the first
    cue found there is enough for a person to look. A finding is a security signal that sends the
    claim to a person; it never changes an amount or counts as fraud evidence.
    """
    # Imported here: guardrails.guardrails imports this module (find_injections), so a top-level
    # import would be circular.
    from claimsense.guardrails.input_guardrails import classify_injection_fast

    use_llm = os.getenv("CLAIMSENSE_GUARD_LLM") == "1"
    places = [(name, text) for name, text in (documents or {}).items()]
    if claim is not None:
        places += [(f"bill line {line.line_id}", line.description) for line in claim.bill_lines]
    issues = []
    for where, text in places:
        result = classify_injection_fast(text)
        cue = f"'{result.patterns_matched[0]}'" if result.is_injection else None
        if cue is None and use_llm:
            from claimsense.guardrails.guardrails import classify_injection_llm

            cue = "flagged by the guard model" if classify_injection_llm(text) else None
        if cue:
            issues.append(f"possible prompt injection in {where}: {cue}")
    return issues


# B6: dates a document states for the stay, checked against the claim form. Indian bills write
# day first, so "05/06/2026" is 5 June. Formats: 2026-06-05, 05/06/2026, 05-06-2026, 5 June 2026,
# 5th Jun 2026. A date only counts when an admission or discharge word comes before it in the same
# sentence (or after it, if none comes before), so report, invoice and print dates are ignored.
_MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
_DATE = re.compile(
    r"\b(?P<y1>\d{4})-(?P<m1>\d{1,2})-(?P<d1>\d{1,2})\b"
    r"|\b(?P<d2>\d{1,2})[/-](?P<m2>\d{1,2})[/-](?P<y2>\d{4})\b"
    r"|\b(?P<d3>\d{1,2})(?:st|nd|rd|th)?\s+(?P<m3>[a-z]{3,9})\.?,?\s+(?P<y3>\d{4})\b",
    re.IGNORECASE,
)
_STAY_EVENTS = {
    "admission": (
        re.compile(r"\badmi(?:t|ts|tted|tting|ssion)\b", re.IGNORECASE),
        "admission_date",
    ),
    "discharge": (re.compile(r"\bdischarg\w*", re.IGNORECASE), "discharge_date"),
}


def _parse_date(m: re.Match) -> date | None:
    g = m.groupdict()
    try:
        if g["y1"]:
            return date(int(g["y1"]), int(g["m1"]), int(g["d1"]))
        if g["y2"]:
            return date(int(g["y2"]), int(g["m2"]), int(g["d2"]))
        month = _MONTHS.get(g["m3"][:3].lower())
        return date(int(g["y3"]), month, int(g["d3"])) if month else None
    except ValueError:  # 31/02/2026 and the like: not a date, so no claim about the stay
        return None


def _event_for(sentence: str, at: int) -> str | None:
    """The admission/discharge word closest before position `at`, else the first one after it."""
    before, after = [], []
    for event, (pattern, _) in _STAY_EVENTS.items():
        for k in pattern.finditer(sentence):
            (before if k.start() < at else after).append((k.start(), event))
    if before:
        return max(before)[1]
    return min(after)[1] if after else None


def find_date_conflicts(documents: dict[str, str], claim: Claim) -> list[str]:
    """B6: a document that states an admission or discharge date different from the claim form.

    Returns `date conflict in <document>: <event> <stated>, claim form <form date>`, one per
    conflicting date. The claim goes to a person: which date is right is theirs to decide, so no
    amount changes here.
    """
    issues = []
    for name, text in (documents or {}).items():
        for sentence in re.split(r"(?<=[.!?;\n])\s+", text):
            for m in _DATE.finditer(sentence):
                stated = _parse_date(m)
                event = _event_for(sentence, m.start()) if stated else None
                if event is None:
                    continue
                form = getattr(claim, _STAY_EVENTS[event][1])
                if stated != form:
                    issue = f"date conflict in {name}: {event} {stated}, claim form {form}"
                    if issue not in issues:
                        issues.append(issue)
    return issues


def verify_spans(claim: Claim, documents: dict[str, str]) -> list[str]:
    """Every value must be traceable to the uploaded text. Returns problems, never raises."""
    if not documents:
        return []
    problems = []
    for line in claim.bill_lines:
        doc = documents.get(line.source.document)
        if doc is None:
            problems.append(f"{line.line_id}: unknown document {line.source.document}")
        elif (
            doc[line.source.start : line.source.end] != line.source.text
            and line.source.text not in doc
        ):
            problems.append(f"{line.line_id}: source span not found in {line.source.document}")
    return problems


class ExtractionAgent:
    name = AgentName.EXTRACTION

    def __init__(self, services: Services):
        self.belt = ToolBelt(self.name, services.registry(), services.tool_log)
        self.llm = get_llm("extraction")

    def run(self, packet: dict) -> tuple[Claim, list[str]]:
        """packet = {"claim_id", "documents": {name: text}} and, for dev fixtures, "claim": {...}."""
        documents: dict[str, str] = packet.get("documents", {})
        if "claim" in packet:  # dev / eval fixture already extracted by hand
            claim = Claim.model_validate(packet["claim"])
        elif self.llm is None:
            raise RuntimeError("stub mode: give the packet a pre-extracted 'claim'")
        else:
            claim = self._extract(packet["claim_id"], documents)
        issues = (
            verify_spans(claim, documents)
            + detect_injections(documents, claim)
            + find_date_conflicts(documents, claim)
        )
        if not claim.total_matches_lines():
            issues.append(f"bill total {claim.bill_total} != sum of lines {claim.lines_total()}")
        return claim, issues

    def _extract(self, claim_id: str, documents: dict[str, str], retries: int = 1) -> Claim:
        # L15 input guardrail: identifiers (Aadhaar, PAN, card, phone, e-mail) are masked before
        # the text leaves the process for the model; the reader needs none of them (rule 4). The
        # span check later runs on the original text, which no bill line quotes an identifier of.
        from claimsense.guardrails.input_guardrails import mask_pii

        docs = "\n\n".join(as_data(n, mask_pii(t).masked_text) for n, t in documents.items())
        messages = [("system", SYSTEM), ("human", f"claim_id: {claim_id}\n\n{docs}")]
        structured = self.llm.with_structured_output(Claim)
        last_err = None
        for _ in range(retries + 1):  # bounded retry (L10): feed the validation error back once
            try:
                return structured.invoke(messages)
            except Exception as e:  # pydantic validation or provider error
                last_err = e
                messages.append(("human", f"Your output failed validation: {e}. Fix it."))
        raise RuntimeError(f"extraction failed: {last_err}")
