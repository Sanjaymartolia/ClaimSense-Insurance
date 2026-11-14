"""A judge that holds the raters' written rule, for judge calibration (round 2).

The harness judge, RAGAS faithfulness, runs on its own fixed prompt and asks only "does the
context say this?". On 14 November it failed calibration (kappa 0.150; README "Result"): it
accepted explanations that rest on a term the clause does not list, and it took text planted in a
bill line as support, because the policy wording and the claim facts reached it as one list.

This judge gets the raters' rule (`config/prompts/judge.md`), and the policy wording, the claim
facts and the explanation as three separate data blocks, the way the raters saw them
(`collect.sheet_row`). It answers three checks. Code, not the model, marks an explanation
supported, and only when all three hold. Its reasoning is never saved: it can quote claim facts
(rule 4). Every function takes a `structured` callable, so tests run with no key.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from claimsense.agents.llm import as_data
from claimsense.config import load_config
from eval.harness.loader import REPO_ROOT

#: `structured(prompt, schema) -> schema instance`. The default calls the `judge` model.
Structured = Callable[[str, type[BaseModel]], BaseModel]

#: The three checks of the rule, in the order the prompt states them.
CHECKS = ("names_listed_item", "nothing_invented", "no_policy_from_claim_documents")


class RubricVerdict(BaseModel):
    """The schema is the rubric: reasoning first, then one field per check, and no verdict."""

    reasoning: str = Field(
        description="Each statement of the explanation in turn, quoting the words of the policy "
        "wording or claim facts that support it, or saying that nothing does."
    )
    names_listed_item: bool = Field(description="Check 1 of the constraints.")
    nothing_invented: bool = Field(description="Check 2 of the constraints.")
    no_policy_from_claim_documents: bool = Field(description="Check 3 of the constraints.")


def prompt_path() -> Path:
    """`config/prompts/judge.md`: `prompts_dir` in config/models.yaml holds one file per role."""
    return REPO_ROOT / load_config()["prompts_dir"] / "judge.md"


def split_contexts(claim_id: str, contexts: list[str]) -> tuple[list[str], list[str]]:
    """(policy wording, claim facts). The facts block starts "Claim <id> facts"
    (`eval.harness.llm_judge_metrics.claim_facts`); the rest is wording the agent was shown."""
    prefix = f"Claim {claim_id} facts"
    facts = [c for c in contexts if c.startswith(prefix)]
    policy = [c for c in contexts if not c.startswith(prefix)]
    return policy, facts


def build_prompt(
    rubric: str, line_id: str, rationale: str, policy: list[str], facts: list[str]
) -> str:
    """The rule, then the three documents as data. No label, gold or score reaches it."""
    return "\n\n".join(
        [
            rubric.strip(),
            as_data("policy_wording", "\n---\n".join(policy)),
            as_data("claim_facts", "\n---\n".join(facts)),
            f"The explanation below is for bill line {line_id}.",
            as_data("explanation", rationale),
            "Answer the three checks.",
        ]
    )


def judge_item(
    rubric: str,
    line_id: str,
    rationale: str,
    policy: list[str],
    facts: list[str],
    structured: Structured | None = None,
) -> tuple[float, dict[str, bool]]:
    """(1.0 or 0.0, the three checks). Code decides: 1.0 only when every check holds."""
    ask = structured or _structured
    verdict = ask(build_prompt(rubric, line_id, rationale, policy, facts), RubricVerdict)
    checks = {name: bool(getattr(verdict, name)) for name in CHECKS}
    return (1.0 if all(checks.values()) else 0.0), checks


def _structured(prompt: str, schema: type[BaseModel]) -> BaseModel:
    # Imported here: it needs the `agents` extra, and a key only when it runs.
    from eval.agent_suite.judge import openrouter_structured

    return openrouter_structured(prompt, schema)
