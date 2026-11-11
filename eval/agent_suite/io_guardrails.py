"""L15: the Tools & Security input and output guardrail modules, measured where they stand.

`claimsense.guardrails.input_guardrails` and `output_guardrails` (Tools & Security) are not called
by the graph, the API or the harness. Section 5.1 measures `guardrails.scan_documents`; this module
measures these two, as components, on the same data, so their worth is known before anyone wires
them in. Nothing here changes what the pipeline does.

- **Health.** Does each module import? Does each pipeline run with its own defaults?
- **Input** (once the module imports): recall and false alarms of `classify_injection_fast` on the
  same documents as 5.1; false blocks of `verify_scope` on the dev documents; PII seeds that
  `mask_pii` leaves visible, and dev documents that it changes (no dev document holds PII).
- **Output:** the letter `SettlementAgent.draft_letter` writes for each dev claim is the clean
  set: how many would the scrubbers block or change? Leaks planted in one letter
  (`eval/redteam/guardrail_seeds.jsonl`) are the attack set: how many get through? The product's
  own `SettlementAgent.output_guard` is measured on the wrong-patient letter (RT-005) next to it.

The pipelines are fail-closed, so an exception is a block. Letters are written with the model off
(the stub sentences), so this costs nothing in either mode.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from types import ModuleType, SimpleNamespace

from eval.harness.loader import REPO_ROOT

from .dataset import Case
from .guardrail import case_documents

SEEDS = REPO_ROOT / "eval" / "redteam" / "guardrail_seeds.jsonl"
INPUT_MODULE = "claimsense.guardrails.input_guardrails"
OUTPUT_MODULE = "claimsense.guardrails.output_guardrails"
CLEAN_LETTER = "clean letter"


def load_seeds(side: str) -> list[dict]:
    rows = [json.loads(line) for line in SEEDS.read_text(encoding="utf-8").splitlines() if line]
    return [r for r in rows if r["side"] == side]


def import_module(name: str) -> tuple[ModuleType | None, str | None]:
    """(module, None), or (None, "<ExceptionType>: <first line>") if it cannot be imported."""
    try:
        return importlib.import_module(name), None
    except Exception as e:  # noqa: BLE001 - any import failure is the finding
        return None, f"{type(e).__name__}: {str(e).splitlines()[0][:160]}"


def _outcome(fn, *args, **kwargs) -> tuple[str, object]:
    """('ok', result) or ('raised', '<ExceptionType>')."""
    try:
        return "ok", fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 - fail-closed: any exception is a block
        return "raised", type(e).__name__


# ------------------------------------------------------------------------------------- input
@dataclass
class InputReport:
    import_error: str | None = None
    pipeline_error: str | None = None
    caught: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    false_alarms: list[str] = field(default_factory=list)
    scope_false_blocks: list[str] = field(default_factory=list)
    pii_left_visible: list[str] = field(default_factory=list)
    dev_documents_changed: list[str] = field(default_factory=list)
    n_attacks: int = 0
    n_clean: int = 0

    @property
    def recall(self) -> float:
        return len(self.caught) / self.n_attacks if self.n_attacks else 1.0

    def format(self) -> str:
        if self.import_error:
            return f"  {INPUT_MODULE} cannot be imported: {self.import_error}\n  (nothing measured)"
        return "\n".join(
            [
                f"  process_input_pipeline with its defaults: {self.pipeline_error or 'runs'}",
                f"  classify_injection_fast caught {len(self.caught)}/{self.n_attacks} injected "
                f"claims (recall {self.recall:.0%}); missed: {', '.join(self.missed) or '-'}",
                f"  false alarms on {self.n_clean} dev claims: "
                f"{', '.join(self.false_alarms) or 'none'}",
                f"  verify_scope blocks dev claims: {', '.join(self.scope_false_blocks) or 'none'}",
                f"  mask_pii leaves PII visible: {', '.join(self.pii_left_visible) or 'none'}; "
                f"changes dev claims (no PII there): "
                f"{', '.join(self.dev_documents_changed) or 'none'}",
            ]
        )


def measure_input(cases: list[Case], module: ModuleType | None = None) -> InputReport:
    if module is None:
        module, error = import_module(INPUT_MODULE)
        if module is None:
            return InputReport(import_error=error)
    attacks = [c for c in cases if c.injected]
    clean = [c for c in cases if c.source == "golden"]
    docs = {c.claim_id: list(case_documents(c).values()) for c in attacks + clean}

    def injected(cid: str) -> bool:
        return any(module.classify_injection_fast(t).is_injection for t in docs[cid])

    status, result = _outcome(
        module.process_input_pipeline, "Claim for policy POL-1 at the hospital."
    )
    report = InputReport(
        pipeline_error=None if status == "ok" else f"raises {result}",
        n_attacks=len(attacks),
        n_clean=len(clean),
    )
    report.caught = [c.claim_id for c in attacks if injected(c.claim_id)]
    report.missed = [c.claim_id for c in attacks if c.claim_id not in report.caught]
    report.false_alarms = [c.claim_id for c in clean if injected(c.claim_id)]
    report.scope_false_blocks = [
        c.claim_id
        for c in clean
        if any(_outcome(module.verify_scope, t)[0] == "raised" for t in docs[c.claim_id])
    ]
    for seed in load_seeds("input"):
        if seed["secret"] in module.mask_pii(seed["text"]).masked_text:
            report.pii_left_visible.append(f"{seed['seed_id']} ({seed['type']})")
    report.dev_documents_changed = [
        c.claim_id
        for c in clean
        if any(module.mask_pii(t).masked_text != t for t in docs[c.claim_id])
    ]
    return report


# ------------------------------------------------------------------------------------ output
def clean_letters(cases: list[Case], traces: list) -> dict[str, tuple[object, object, str]]:
    """{claim_id: (claim, worksheet, letter)}: for each dev claim that reached a person, the letter
    the settlement agent would write on approval, from the worksheet in the last review payload,
    with the model off. `claim` carries only what the letter uses."""
    from claimsense.agents.services import make_stub_services
    from claimsense.agents.settlement import SettlementAgent
    from claimsense.contracts import Worksheet

    from .trace import _adapter

    adapter = _adapter("reference", True)
    agent = SettlementAgent(make_stub_services())
    agent.llm = None  # the stub sentences: free, and the same letter in either mode
    out = {}
    for case, t in zip(cases, traces, strict=True):
        payload = t.review_payloads[-1] if t.review_payloads else {}
        if case.source != "golden" or not payload.get("worksheet"):
            continue
        worksheet = Worksheet.model_validate(payload["worksheet"])
        packet = adapter._packet(case.eval_case.claim)["claim"]
        claim = SimpleNamespace(
            claim_id=packet["claim_id"],
            policy_number=packet["policy_number"],
            patient_pseudonym=packet["patient_pseudonym"],
        )
        out[case.claim_id] = (claim, worksheet, agent.draft_letter(claim, worksheet))
    return out


def scrub(module: ModuleType, text: str) -> tuple[str, str]:
    """The output pipeline's steps, called one by one (its own entry point has defect G-02):
    leak checks, then link and image stripping. Returns ('blocked', type) or ('passed', text)."""
    status, result = _outcome(module.scrub_leaks, text)
    if status == "raised":
        return "blocked", str(result)
    return "passed", module.strip_all_external_references(result)


@dataclass
class OutputReport:
    import_error: str | None = None
    pipeline_error: str | None = None
    check_output_safe_blocks: int = 0
    n_letters: int = 0
    false_blocks: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    without_citation: list[str] = field(default_factory=list)
    caught: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    wrong_patient: dict[str, str] = field(default_factory=dict)

    def format(self) -> str:
        if self.import_error:
            return (
                f"  {OUTPUT_MODULE} cannot be imported: {self.import_error}\n  (nothing measured)"
            )
        n = len(self.caught) + len(self.missed)
        return "\n".join(
            [
                f"  process_output_pipeline with its defaults: {self.pipeline_error or 'runs'}",
                f"  check_output_safe blocks {self.check_output_safe_blocks}/{self.n_letters} "
                "clean letters (one per dev claim that reached a person with a worksheet)",
                f"  scrubbers on {self.n_letters} clean letters: blocked "
                f"{', '.join(self.false_blocks) or 'none'}; changed "
                f"{', '.join(self.changed) or 'none'}",
                f"  clean letters with no clause citation (a strict check would block): "
                f"{len(self.without_citation)}/{self.n_letters}",
                f"  planted leaks caught {len(self.caught)}/{n}; got through: "
                f"{', '.join(self.missed) or 'none'}",
                "  wrong-patient letter (RT-005): "
                + ", ".join(f"{k} {v}" for k, v in self.wrong_patient.items()),
            ]
        )


def measure_output(cases: list[Case], traces: list, module: ModuleType | None = None):
    if module is None:
        module, error = import_module(OUTPUT_MODULE)
        if module is None:
            return OutputReport(import_error=error)
    from claimsense.agents.settlement import SettlementAgent

    letters = clean_letters(cases, traces)
    report = OutputReport(n_letters=len(letters))
    if not letters:
        return report
    first_claim, first_ws, first_letter = next(iter(letters.values()))
    status, result = _outcome(module.process_output_pipeline, first_letter)
    report.pipeline_error = None if status == "ok" else f"raises {result}"
    for cid, (_, _, letter) in letters.items():
        safe = module.check_output_safe(letter, cid, [], strict_mode=False)[0]
        report.check_output_safe_blocks += not safe
        verdict, text = scrub(module, letter)
        if verdict == "blocked":
            report.false_blocks.append(f"{cid} ({text})")
        elif text != letter:
            report.changed.append(cid)
        if _outcome(module.verify_citations_present, letter)[0] == "raised":
            report.without_citation.append(cid)
    for seed in load_seeds("output"):
        verdict, text = scrub(module, first_letter + seed["text"])
        label = f"{seed['seed_id']} ({seed['type']})"
        if verdict == "blocked" or seed["secret"] not in text:
            report.caught.append(label)
        else:
            report.missed.append(label)
    # RT-005: the letter names another insured person. Only a check against the claim can see it.
    wrong = first_letter.replace(first_claim.patient_pseudonym, "SYN-PAT-9999")
    report.wrong_patient = {
        "output_guardrails": "blocked" if scrub(module, wrong)[0] == "blocked" else "passed",
        "SettlementAgent.output_guard": "blocked"
        if _outcome(SettlementAgent.output_guard, first_claim, first_ws, wrong)[0] == "raised"
        else "passed",
    }
    return report


def format_both(cases: list[Case], traces: list) -> str:
    return "\n".join(
        [
            f"input  ({INPUT_MODULE}):",
            measure_input(cases).format(),
            f"output ({OUTPUT_MODULE}):",
            measure_output(cases, traces).format(),
        ]
    )
