"""LLM-judge metric: is the agent's reason actually supported by the clause it cited?

This closes EVAL-02. `config/models.yaml` has reserved a `judge` model since the project started
and nothing used it; this module is its first caller, and it reads the id from there rather than
hard-coding one, as `CLAUDE.md` requires.

The metric is RAGAS `Faithfulness`: it breaks the agent's rationale into claims and checks each one
against the retrieved clause text. "Unfaithful" here means *unsupported by the cited wording*,
which is exactly the failure that matters - a confident sentence the policy does not say.

Two cautions, both load-bearing:

1. **Off by default.** It costs money and needs `OPENROUTER_API_KEY`. The whole harness runs and
   gates without it. Turn it on with `--judge`.
2. **An uncalibrated judge is an opinion, not a measurement.** Run
   `eval/calibration/judge_calibration.py` and report Cohen's kappa before any number from here
   goes in a report. `eval/README.md` asks for this and the KYC harness treats human agreement as
   a precondition, not a footnote.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from .loader import KNOWLEDGE_BASE, REPO_ROOT
from .models import AgentOutput, ClaimRecord, EvalCase, MetricResult

#: OpenRouter speaks the OpenAI wire format, so the plain `openai` provider works with a new base
#: url. Kept here, not in a config file, because it is a property of OpenRouter, not a tuning knob.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def load_key_from_dotenv() -> bool:
    """Put `OPENROUTER_API_KEY` into the environment from `.env`, if it is not already there.

    The project keeps the key in `.env` at the repository root, but nothing in `src/` loads that
    file: `claimsense.config.openrouter_api_key` reads `os.environ` only, and the project takes no
    `python-dotenv` dependency. Without this the judge fails with "not set" even though the key is
    sitting in `.env`.

    Rule 4 of the project applies. This function never prints, logs or returns the value. It
    returns only whether a key is now present.
    """
    if os.environ.get("OPENROUTER_API_KEY"):
        return True
    dotenv = Path(REPO_ROOT) / ".env"
    if not dotenv.exists():
        return False
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or not line.startswith("OPENROUTER_API_KEY="):
            continue
        value = line.split("=", 1)[1].strip().strip("'\"")
        if value:
            os.environ["OPENROUTER_API_KEY"] = value
            return True
    return False


class JudgeUnavailableError(RuntimeError):
    """Raised when `--judge` was asked for but cannot run. Never swallowed: a silently skipped
    judge would leave a gap in a report that looks like a pass."""


def clause_text_index() -> dict[str, str]:
    """`{clause_id: text with headings}` from the committed knowledge base.

    `text` is used rather than `source_text` because that is the field the retriever returns as
    `context_text`, and a list item such as 6.2.6 is meaningless without its parent heading
    (AGT-13). Judging against the bare item would mark correct rationales unfaithful.
    """
    index: dict[str, str] = {}
    for line in Path(KNOWLEDGE_BASE).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        clause_id = row.get("clause_id")
        if clause_id and clause_id not in index:
            index[clause_id] = row.get("text") or row.get("source_text") or ""
    return index


def claim_facts(claim: ClaimRecord) -> str:
    """The claim's own facts, as one context block for the judge.

    This block is not optional, and leaving it out was a real measurement error. An adjudication
    rationale always joins two sources: what the clause says, and what the claim says. A correct
    sentence such as "the only exception is ectopic pregnancy, which this claim does not state"
    cites the clause for the first half and the claim for the second. Judged against policy text
    alone, that second half is unverifiable, and faithfulness scores a correct rationale as
    unfaithful.

    Measured on clause 7.15 and a hand-written correct rationale, with the judge from
    `config/models.yaml`:

        clause text only              faithfulness 0.200
        clause text plus these facts  faithfulness 0.800

    Facts only, never conclusions. Nothing here says whether a line is payable, so the judge
    cannot read the answer off the context.
    """
    raw = claim.model_dump()
    stay = raw.get("hospitalisation") or {}
    policy = raw.get("policy") or {}
    parts = [
        f"Claim {claim.claim_id} facts, as filed.",
        f"Diagnosis: {stay.get('diagnosis', 'not stated')}.",
        f"Admitted {stay.get('admission_date', 'not stated')}, "
        f"discharged {stay.get('discharge_date', 'not stated')}.",
        f"Policy ran {policy.get('policy_start_date', '?')} "
        f"to {policy.get('policy_end_date', '?')}, "
        f"sum insured {policy.get('sum_insured_inr', '?')}.",
        "Pre-existing condition declared: "
        f"{'yes' if stay.get('pre_existing_condition_declared') else 'no'}.",
        "Bill lines: "
        + "; ".join(f"{b.line_id} {b.description} Rs {b.amount_inr}" for b in claim.bill_lines)
        + ".",
        "Any condition not listed above is not recorded on this claim.",
    ]
    return " ".join(parts)


#: `claimsense_adapter.placeholder_rationale`: a sentence the adapter writes when the coverage
#: model gave no reason. It is not the agent's text, so judging it would measure the adapter.
_PLACEHOLDER = re.compile(r"Line \S+ was adjudicated under clause \S+\.")


def is_placeholder(rationale: str) -> bool:
    return bool(_PLACEHOLDER.fullmatch(rationale.strip()))


def attach_clause_contexts(outputs: list[AgentOutput], cases: list[EvalCase] | None = None) -> int:
    """Fill empty `retrieved_contexts` from the clauses each output cited, plus the claim's facts.

    A real agent records what it was shown, and that is what should be judged. This helper is for
    adapters that cite without recording context (the fixture adapters, and any early pipeline):
    it reconstructs "the agent was shown the clause it cited" so the judge has something to score.

    Pass `cases` so the claim's facts go in too. See `claim_facts` for why that matters: without
    them a correct rationale scores 0.200 instead of 0.800. The argument is optional only so an
    adapter that already records its own full context is left untouched.

    An output whose adapter already recorded what the agent was shown keeps that context; with
    `cases`, the claim's facts are added to it, because a rationale joins clause and claim there
    too. Returns how many outputs it filled from the cited clauses.
    """
    index = clause_text_index()
    facts = {}
    if cases:
        facts = {case.claim_id: claim_facts(case.claim) for case in cases}
    filled = 0
    for out in outputs:
        if out.rationales and all(is_placeholder(r) for r in out.rationales.values()):
            continue  # no model reason on any line: nothing to judge (see is_placeholder)
        if out.retrieved_contexts:
            fact = facts.get(out.claim_id)
            if fact:
                for texts in out.retrieved_contexts.values():
                    if fact not in texts:
                        texts.append(fact)
            continue
        if not out.rationales:
            continue
        texts = [index[c] for c in out.citations if c in index]
        if not texts:
            continue
        if out.claim_id in facts:
            texts = [*texts, facts[out.claim_id]]
        out.retrieved_contexts = {line_id: texts for line_id in out.rationales}
        filled += 1
    return filled


def _build_scorer():  # noqa: ANN202 - ragas types are not importable without the extra
    try:
        from ragas.llms import llm_factory
        from ragas.metrics.collections import Faithfulness
    except ImportError as e:  # pragma: no cover - depends on the optional extra
        raise JudgeUnavailableError(
            f'ragas is not installed ({e}). Run: pip install -e ".[eval]", then on Python 3.14 '
            'also: pip install --no-deps "ragas>=0.4,<0.5" (see requirements.txt)'
        ) from e
    try:
        from openai import AsyncOpenAI

        from claimsense.config import model_for, openrouter_api_key
    except ImportError as e:  # pragma: no cover
        raise JudgeUnavailableError(f"judge dependencies missing: {e}") from e

    load_key_from_dotenv()
    try:
        api_key = openrouter_api_key()
    except RuntimeError as e:
        raise JudgeUnavailableError(
            f"{e}. Put it in .env at the repository root. The judge needs a key; "
            "the rest of the harness does not."
        ) from e

    model = model_for("judge")
    llm = llm_factory(
        model, provider="openai", client=AsyncOpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL)
    )
    return Faithfulness(llm=llm), model


async def _score_output(scorer, out: AgentOutput) -> tuple[float | None, dict]:  # noqa: ANN001
    """Mean faithfulness over the lines that have both a rationale and a context."""
    per_line: dict[str, float] = {}
    errors: dict[str, str] = {}
    for line_id, rationale in sorted(out.rationales.items()):
        contexts = out.retrieved_contexts.get(line_id) or []
        if not contexts or not rationale.strip() or is_placeholder(rationale):
            continue
        try:
            result = await scorer.ascore(
                user_input=f"Is line {line_id} payable, and under which clause?",
                response=rationale,
                retrieved_contexts=contexts,
            )
            per_line[line_id] = float(getattr(result, "value", result))
        except Exception as e:  # noqa: BLE001 - one bad line must not lose the whole run
            errors[line_id] = f"{type(e).__name__}: {e}"
    if not per_line:
        return None, {"scored_lines": 0, "errors": errors}
    mean = sum(per_line.values()) / len(per_line)
    return mean, {
        "scored_lines": len(per_line),
        "per_line": {k: round(v, 3) for k, v in per_line.items()},
        "worst_line": min(per_line, key=per_line.get),
        "errors": errors,
    }


def score_outputs(outputs: list[AgentOutput], limit: int | None = None) -> dict[str, MetricResult]:
    """Judge up to `limit` outputs. Returns one run-level `rationale_groundedness` metric.

    `limit` keeps a first run cheap: judging 50 claims line by line is many calls. Report the
    number judged alongside the score, because a mean over 5 claims is not a mean over 50.
    """
    scorer, model = _build_scorer()
    chosen = outputs if limit is None else outputs[:limit]

    async def run_all() -> list[tuple[AgentOutput, float | None, dict]]:
        scored = []
        for out in chosen:
            value, detail = await _score_output(scorer, out)
            scored.append((out, value, detail))
        return scored

    scored = asyncio.run(run_all())
    usable = [(o, v, d) for o, v, d in scored if v is not None]
    if not usable:
        return {
            "rationale_groundedness": MetricResult(
                name="rationale_groundedness",
                family="judge",
                value=0.0,
                passed=None,
                severity="warn",
                detail={
                    "judged_claims": 0,
                    "judge_model": model,
                    "note": (
                        "No claim had both a rationale and retrieved context. Use "
                        "attach_clause_contexts(), or an adapter that records what it retrieved."
                    ),
                },
            )
        }
    mean = sum(v for _, v, _ in usable) / len(usable)
    worst = min(usable, key=lambda t: t[1])
    return {
        "rationale_groundedness": MetricResult(
            name="rationale_groundedness",
            family="judge",
            value=mean,
            passed=None,  # no threshold until the judge is calibrated
            severity="medium",
            detail={
                "judged_claims": len(usable),
                "requested_claims": len(chosen),
                "judge_model": model,
                "worst_claim": worst[0].claim_id,
                "worst_value": round(worst[1], 3),
                "per_claim": {o.claim_id: round(v, 3) for o, v, _ in usable},
                "calibrated": False,
                "note": (
                    "Uncalibrated. Report Cohen's kappa from eval/calibration before citing this."
                ),
            },
        )
    }
