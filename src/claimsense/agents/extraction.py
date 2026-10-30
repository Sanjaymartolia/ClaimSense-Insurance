"""Extraction agent: packet documents -> typed Claim with a source span for every bill line."""

from __future__ import annotations

import re

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
    return [f"possible prompt injection in {name}: '{m.group(0)}'"
            for name, text in documents.items() for m in [INJECTION_PATTERNS.search(text)] if m]


def verify_spans(claim: Claim, documents: dict[str, str]) -> list[str]:
    """Every value must be traceable to the uploaded text. Returns problems, never raises."""
    if not documents:
        return []
    problems = []
    for line in claim.bill_lines:
        doc = documents.get(line.source.document)
        if doc is None:
            problems.append(f"{line.line_id}: unknown document {line.source.document}")
        elif doc[line.source.start:line.source.end] != line.source.text and line.source.text not in doc:
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
        issues = verify_spans(claim, documents) + find_injections(documents)
        if not claim.total_matches_lines():
            issues.append(f"bill total {claim.bill_total} != sum of lines {claim.lines_total()}")
        return claim, issues

    def _extract(self, claim_id: str, documents: dict[str, str], retries: int = 1) -> Claim:
        docs = "\n\n".join(as_data(n, t) for n, t in documents.items())
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
