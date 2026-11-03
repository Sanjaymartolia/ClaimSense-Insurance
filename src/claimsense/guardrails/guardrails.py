"""Input and output guardrails (L15). ClaimSense Role 4 (Tools, Control & Security).

Treats every uploaded document (discharge summary, itemised bill, extracted text) as **data, never
instructions**, validates extracted claim fields and settlement arithmetic, and checks the outgoing
letter. It *extends* the primitives Role 3 already ships rather than duplicating them:

* ``claimsense.agents.llm.as_data`` / ``DATA_RULE`` - wrap untrusted text so a model treats it as data.
* ``claimsense.agents.extraction.find_injections`` / ``INJECTION_PATTERNS`` / ``verify_spans`` -
  the cheap extraction-time tripwire; we build on it with more patterns and structured findings.
* ``claimsense.contracts.Claim.total_matches_lines`` and the ``Worksheet`` validators - arithmetic truth.

Key safety stances
-------------------
* A prompt-injection finding is a **security** signal, not evidence of fraud. :func:`is_injection`
  is provided, but callers must never turn an injection flag into a fraud/decision outcome.
* Suspicious document instructions can never change system prompts, tool permissions or approval
  decisions: this module only *reports* findings; permissions live in ``hooks``/``TOOL_ACL`` and
  approvals in ``approval_security``.
* **No health details in logs**: findings carry ids, amounts and safe codes; :func:`scrub` strips
  diagnosis/patient/raw text before anything is logged.

The repo's red-team *attack strings* (``eval/redteam/attacks.jsonl``) are intentionally NOT loaded
as detection signatures - the defence must not be fitted to the specific attack set (Role 5 owns
those). Detection uses generic patterns.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path


def _ensure_claimsense_on_path() -> None:
    try:
        import claimsense  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    env = os.environ.get("CLAIMSENSE_SRC")
    here = Path(__file__).resolve()
    candidates = [Path(env)] if env else []
    candidates += [
        here.parent.parent / "ClaimSense-Insurance" / "src",
        here.parent / "ClaimSense-Insurance" / "src",
    ]
    for cand in candidates:
        if (cand / "claimsense").is_dir():
            sys.path.insert(0, str(cand))
            return


_ensure_claimsense_on_path()

from claimsense.agents.extraction import INJECTION_PATTERNS, find_injections  # noqa: E402
from claimsense.agents.extraction import verify_spans as _verify_spans  # noqa: E402
from claimsense.agents.llm import DATA_RULE, as_data  # noqa: E402
from claimsense.contracts import Claim, Worksheet  # noqa: E402

__all__ = [
    "DATA_RULE", "GuardFinding", "GuardReport", "OutputGuardViolation",
    "wrap_as_data", "scan_text", "scan_documents", "verify_spans",
    "validate_claim_fields", "check_consistency", "validate_worksheet_arithmetic",
    "check_letter", "assert_letter_ok", "screen_input", "screen_output",
    "is_injection", "scrub",
]


# --------------------------------------------------------------------------------------------
# Structured findings
# --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class GuardFinding:
    """A single guardrail finding. Messages are PHI-free (ids/amounts/codes only)."""

    code: str
    category: str          # "injection" | "input_validation" | "consistency" | "arithmetic" | "output"
    message: str
    severity: str = "warn"  # "info" | "warn" | "block"
    location: str | None = None

    def to_flag(self) -> str:
        """Render for the fraud/trace path (used by the workflow's string flag lists)."""
        where = f" [{self.location}]" if self.location else ""
        return f"{self.category}: {self.message}{where}"


@dataclass
class GuardReport:
    """Aggregated findings with convenience predicates."""

    findings: list[GuardFinding] = field(default_factory=list)

    def add(self, *findings: GuardFinding) -> None:
        self.findings.extend(f for f in findings if f is not None)

    @property
    def flagged(self) -> bool:
        return bool(self.findings)

    @property
    def blocked(self) -> bool:
        return any(f.severity == "block" for f in self.findings)

    def by_category(self, category: str) -> list[GuardFinding]:
        return [f for f in self.findings if f.category == category]

    def flags(self) -> list[str]:
        return [f.to_flag() for f in self.findings]


class OutputGuardViolation(ValueError):
    """Raised by :func:`assert_letter_ok` when the outgoing letter fails a check."""


# --------------------------------------------------------------------------------------------
# Input: treat document text as data; detect injection
# --------------------------------------------------------------------------------------------
def wrap_as_data(name: str, text: str) -> str:
    """Wrap untrusted document text so a model treats it as data (delegates to ``llm.as_data``)."""
    return as_data(name, text)


# Generic injection cues layered on top of the repo's INJECTION_PATTERNS. These are broad phrasings,
# not copies of the project's specific red-team strings.
_EXTRA_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|rules)", re.IGNORECASE),
    re.compile(r"disregard\s+(the\s+)?(policy|rules|exclusions|instructions)", re.IGNORECASE),
    re.compile(r"bypass\s+(the\s+)?(approval|gate|policy|review)", re.IGNORECASE),
    re.compile(r"do\s+not\s+(apply|deduct|check)\b", re.IGNORECASE),
    re.compile(r"\b(system|developer)\s*(prompt|message|role)\b", re.IGNORECASE),
    re.compile(r"</?\s*system\s*>", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\b", re.IGNORECASE),
    re.compile(r"reveal\s+(the\s+)?(system prompt|hidden|secret)", re.IGNORECASE),
    re.compile(r"as\s+agreed\s+with\s+the\s+insurer", re.IGNORECASE),
]


def scan_text(text: str, *, source: str | None = None) -> list[GuardFinding]:
    """Scan one untrusted string for prompt-injection cues. Returns security findings (not fraud)."""
    if not isinstance(text, str) or not text.strip():
        return []
    findings: list[GuardFinding] = []
    seen: set[str] = set()
    patterns = [INJECTION_PATTERNS, *_EXTRA_INJECTION_PATTERNS]
    for pat in patterns:
        m = pat.search(text)
        if m:
            snippet = m.group(0).strip().lower()
            if snippet not in seen:
                seen.add(snippet)
                findings.append(
                    GuardFinding(code="prompt_injection", category="injection",
                                 message=f"possible injected instruction: {snippet!r}",
                                 severity="warn", location=source)
                )
    return findings


def scan_documents(documents: dict[str, str]) -> list[GuardFinding]:
    """Scan every uploaded document. Combines the repo tripwire with the extra generic patterns."""
    findings: list[GuardFinding] = []
    # repo's cheap tripwire first (keeps parity with extraction's behaviour)
    for note in find_injections(documents or {}):
        findings.append(GuardFinding(code="prompt_injection", category="injection",
                                     message=note, severity="warn"))
    repo_hits = {f.message for f in findings}
    for name, text in (documents or {}).items():
        for finding in scan_text(text, source=name):
            if finding.message not in repo_hits:
                findings.append(finding)
    return findings


def verify_spans(claim: Claim, documents: dict[str, str]) -> list[GuardFinding]:
    """Every bill-line value must trace to the uploaded text (delegates to ``extraction.verify_spans``)."""
    return [GuardFinding(code="untraceable_span", category="input_validation", message=problem,
                         severity="warn")
            for problem in _verify_spans(claim, documents or {})]


# --------------------------------------------------------------------------------------------
# Input: validate extracted claim fields
# --------------------------------------------------------------------------------------------
def validate_claim_fields(claim: Claim) -> list[GuardFinding]:
    """Validate the typed claim (the contract already enforces types; we add cross-field checks)."""
    findings: list[GuardFinding] = []
    if not claim.bill_lines:
        findings.append(GuardFinding(code="no_bill_lines", category="input_validation",
                                     message="claim has no bill lines", severity="block"))
    if claim.sum_insured <= 0:
        findings.append(GuardFinding(code="bad_sum_insured", category="input_validation",
                                     message="sum insured must be positive", severity="block"))
    if not claim.total_matches_lines():
        findings.append(GuardFinding(
            code="bill_total_mismatch", category="consistency",
            message=f"bill total {claim.bill_total} != sum of lines {claim.lines_total()}",
            severity="warn"))
    return findings


# --------------------------------------------------------------------------------------------
# Input: cross-source consistency (bill total, dates, patient)
# --------------------------------------------------------------------------------------------
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_PATIENT_RE = re.compile(r"patient(?:\s+id)?\s*[:\-]?\s*([A-Za-z0-9\-]{3,})", re.IGNORECASE)


def _context_dates(text: str, keyword: str) -> list[str]:
    hits = []
    for m in _DATE_RE.finditer(text):
        start = max(0, m.start() - 40)
        if keyword in text[start:m.start()].lower():
            hits.append(m.group(1))
    return hits


def check_consistency(claim: Claim, documents: dict[str, str] | None = None) -> list[GuardFinding]:
    """Detect bill-total, date and patient-identity inconsistencies where the data supports it."""
    findings: list[GuardFinding] = []
    if not claim.total_matches_lines():
        findings.append(GuardFinding(
            code="bill_total_mismatch", category="consistency",
            message=f"bill total {claim.bill_total} != sum of lines {claim.lines_total()}",
            severity="warn"))

    for name, text in (documents or {}).items():
        if not isinstance(text, str):
            continue
        for d in _context_dates(text, "discharge"):
            if d != claim.discharge_date.isoformat():
                findings.append(GuardFinding(
                    code="date_mismatch", category="consistency",
                    message=f"discharge date in document ({d}) != claim ({claim.discharge_date.isoformat()})",
                    severity="warn", location=name))
        for d in _context_dates(text, "admiss"):
            if d != claim.admission_date.isoformat():
                findings.append(GuardFinding(
                    code="date_mismatch", category="consistency",
                    message=f"admission date in document ({d}) != claim ({claim.admission_date.isoformat()})",
                    severity="warn", location=name))
        for m in _PATIENT_RE.finditer(text):
            ident = m.group(1)
            if ident and ident.lower() != claim.patient_pseudonym.lower():
                findings.append(GuardFinding(
                    code="patient_mismatch", category="consistency",
                    message="document names a patient identifier that differs from the claim",
                    severity="warn", location=name))
                break
    return findings


# --------------------------------------------------------------------------------------------
# Output: settlement arithmetic + letter
# --------------------------------------------------------------------------------------------
def validate_worksheet_arithmetic(worksheet: Worksheet | dict) -> list[GuardFinding]:
    """Independently re-check that the worksheet's lines and totals reconcile."""
    findings: list[GuardFinding] = []
    try:
        ws = worksheet if isinstance(worksheet, Worksheet) else Worksheet.model_validate(worksheet)
    except Exception as exc:  # noqa: BLE001
        return [GuardFinding(code="worksheet_invalid", category="arithmetic",
                             message=f"worksheet failed validation: {type(exc).__name__}", severity="block")]
    for line in ws.lines:
        deducted = sum((d.amount for d in line.deductions), Decimal("0"))
        if line.claimed - deducted != line.payable:
            findings.append(GuardFinding(
                code="line_arithmetic", category="arithmetic",
                message=f"line {line.line_id}: claimed-deductions != payable", severity="block",
                location=line.line_id))
    payable = sum((line.payable for line in ws.lines), Decimal("0"))
    if ws.co_pay is not None:
        payable -= ws.co_pay.amount
    if payable != ws.total_payable:
        findings.append(GuardFinding(code="total_arithmetic", category="arithmetic",
                                     message="total_payable does not reconcile with lines", severity="block"))
    return findings


def check_letter(claim: Claim, worksheet: Worksheet, letter: str) -> list[GuardFinding]:
    """Output guard: the letter must name the right claim/policy/patient and quote the right total.

    Canonical replacement for ``settlement.output_guard`` (which invites Tools & Security to replace
    it); ``settlement.output_guard`` can delegate here.
    """
    findings: list[GuardFinding] = []
    if claim.claim_id != worksheet.claim_id:
        findings.append(GuardFinding(code="claim_mismatch", category="output",
                                     message="worksheet belongs to a different claim", severity="block"))
    if claim.policy_number not in (letter or ""):
        findings.append(GuardFinding(code="policy_missing", category="output",
                                     message="letter does not name the policy number", severity="block"))
    if claim.patient_pseudonym not in (letter or ""):
        findings.append(GuardFinding(code="patient_missing", category="output",
                                     message="letter does not name the insured person", severity="block"))
    if f"Rs {worksheet.total_payable}" not in (letter or ""):
        findings.append(GuardFinding(code="total_missing", category="output",
                                     message="letter total does not match the worksheet", severity="block"))
    return findings


def assert_letter_ok(claim: Claim, worksheet: Worksheet, letter: str) -> None:
    """Raise :class:`OutputGuardViolation` if the letter fails any output check."""
    problems = check_letter(claim, worksheet, letter)
    if problems:
        raise OutputGuardViolation("; ".join(p.message for p in problems))


# --------------------------------------------------------------------------------------------
# Aggregate screens
# --------------------------------------------------------------------------------------------
def screen_input(claim: Claim | None, documents: dict[str, str] | None = None) -> GuardReport:
    """Input guardrail: scan documents for injection, validate fields and cross-source consistency."""
    report = GuardReport()
    report.add(*scan_documents(documents or {}))
    if claim is not None:
        report.add(*validate_claim_fields(claim))
        report.add(*check_consistency(claim, documents))
        if documents:
            report.add(*verify_spans(claim, documents))
    return report


def screen_output(claim: Claim, worksheet: Worksheet, letter: str | None = None) -> GuardReport:
    """Output guardrail: arithmetic reconciliation plus the letter checks (if a letter is given)."""
    report = GuardReport()
    report.add(*validate_worksheet_arithmetic(worksheet))
    if letter is not None:
        report.add(*check_letter(claim, worksheet, letter))
    return report


# --------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------
def is_injection(findings: list[GuardFinding]) -> bool:
    """True if any finding is a prompt-injection signal. NOTE: this is NOT evidence of fraud."""
    return any(f.category == "injection" for f in findings)


_PHI_KEYS = frozenset(
    {"diagnosis", "procedure", "patient", "patient_pseudonym", "patient_name", "name",
     "discharge_summary", "documents", "document", "text", "source_text", "description",
     "bill_lines", "notes"}
)


def scrub(obj):
    """Return a copy with health details / free text removed, safe for logging."""
    if isinstance(obj, dict):
        return {k: ("<redacted>" if k.lower() in _PHI_KEYS else scrub(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(scrub(v) for v in obj)
    return obj
