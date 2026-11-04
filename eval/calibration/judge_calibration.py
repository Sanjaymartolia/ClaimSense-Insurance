"""Judge calibration: prove the judge agrees with people before you believe it.

`eval/README.md` asks for a judge "calibrated on 20+ human labels, report Cohen's kappa". This is
that workflow. It follows the order the KYC harness uses, and the order matters:

    1. Two people label the same calibration items independently.
    2. Check the people agree with EACH OTHER: inter-rater kappa >= MIN_HUMAN_KAPPA.
       If humans cannot agree, the task is underspecified and no judge score is meaningful.
       Fix the rubric first. This step is the one most often skipped.
    3. Run the judge on the same items.
    4. Check judge-versus-human kappa >= MIN_JUDGE_KAPPA.
    5. Freeze the rubric, the judge model id and the calibration set, and record the hash.
       A score from an unfrozen judge is not reproducible, so it is not evidence.

Cohen's kappa is implemented here rather than imported from scikit-learn. It is nine lines, and
the project has no sklearn dependency; adding one for nine lines is not a trade worth making.

    kappa = (observed agreement - chance agreement) / (1 - chance agreement)

Kappa, not raw agreement, because two raters who both say "grounded" 95% of the time agree 90% of
the time by luck alone. Kappa subtracts that luck.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

#: Humans must agree at least this well with each other before a judge is worth calibrating.
MIN_HUMAN_KAPPA = 0.7

#: The judge must agree with the humans at least this well to be used.
MIN_JUDGE_KAPPA = 0.6

#: Below 20 items a kappa is too noisy to act on. `eval/README.md` asks for 20+.
MIN_ITEMS = 20

CALIBRATION_DIR = Path(__file__).resolve().parent
CALIBRATION_SET = CALIBRATION_DIR / "calibration_set.jsonl"


class CalibrationError(RuntimeError):
    """Raised when the calibration set is unusable. Never downgraded to a warning: a silently
    skipped calibration leaves a number in a report that looks calibrated and is not."""


def cohens_kappa(labels_a: list[object], labels_b: list[object]) -> float:
    """Cohen's kappa for two raters over the same items, any hashable label.

    Returns 1.0 when both raters give one identical label to everything: there is no disagreement
    to measure, so the conventional 0/0 case is treated as perfect agreement rather than undefined.
    """
    if len(labels_a) != len(labels_b):
        raise ValueError(f"rater lists differ in length: {len(labels_a)} vs {len(labels_b)}")
    n = len(labels_a)
    if n == 0:
        raise ValueError("no items to compare")

    observed = sum(1 for a, b in zip(labels_a, labels_b, strict=True) if a == b) / n
    count_a, count_b = Counter(labels_a), Counter(labels_b)
    chance = sum(
        (count_a[label] / n) * (count_b[label] / n) for label in set(count_a) | set(count_b)
    )
    if chance >= 1.0:
        return 1.0 if observed >= 1.0 else 0.0
    return (observed - chance) / (1 - chance)


def interpret(kappa: float) -> str:
    """Landis and Koch's conventional bands. Useful in a report; not a substitute for the number."""
    if kappa < 0.0:
        return "worse than chance"
    if kappa < 0.21:
        return "slight"
    if kappa < 0.41:
        return "fair"
    if kappa < 0.61:
        return "moderate"
    if kappa < 0.81:
        return "substantial"
    return "almost perfect"


@dataclass(frozen=True)
class CalibrationItem:
    """One rationale a judge and at least two people all score."""

    item_id: str
    rationale: str
    contexts: list[str]
    labels: dict[str, int]  # rater name -> 1 grounded, 0 not grounded

    def rater_names(self) -> list[str]:
        return sorted(self.labels)


def load_calibration_set(path: Path | str = CALIBRATION_SET) -> list[CalibrationItem]:
    """Read the human-labelled calibration set, refusing anything unusable.

    Unlabelled rows raise rather than being dropped. A template that quietly scores as calibrated
    is worse than no calibration at all.
    """
    path = Path(path)
    if not path.exists():
        raise CalibrationError(
            f"{path} does not exist. Copy calibration_set.template.jsonl to "
            f"{path.name}, then have two people label every row independently."
        )
    items: list[CalibrationItem] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        labels = row.get("labels") or {}
        unlabelled = sorted(k for k, v in labels.items() if v is None)
        if unlabelled:
            raise CalibrationError(f"{path}:{n} has unlabelled raters {unlabelled}")
        if len(labels) < 2:
            raise CalibrationError(f"{path}:{n} needs at least two raters, found {sorted(labels)}")
        items.append(
            CalibrationItem(
                item_id=str(row["item_id"]),
                rationale=str(row["rationale"]),
                contexts=list(row.get("contexts") or []),
                labels={k: int(v) for k, v in labels.items()},
            )
        )
    if not items:
        raise CalibrationError(f"{path} has no rows")
    return items


def inter_rater_reliability(items: list[CalibrationItem]) -> dict:
    """Step 2: do the people agree with each other?

    Every pair of raters is reported, and the **lowest** pair decides. One disagreeing rater is a
    rubric problem, and averaging the pairs would hide them.
    """
    raters = items[0].rater_names()
    for item in items:
        if item.rater_names() != raters:
            raise CalibrationError(
                f"item {item.item_id} has raters {item.rater_names()}, expected {raters}"
            )
    if len(raters) < 2:
        raise CalibrationError(f"need two raters, found {raters}")

    pairs: dict[str, float] = {}
    for i, first in enumerate(raters):
        for second in raters[i + 1 :]:
            pairs[f"{first}|{second}"] = cohens_kappa(
                [item.labels[first] for item in items], [item.labels[second] for item in items]
            )
    worst_pair = min(pairs, key=pairs.get)
    worst = pairs[worst_pair]
    return {
        "n_items": len(items),
        "raters": raters,
        "pairwise_kappa": {k: round(v, 4) for k, v in pairs.items()},
        "worst_pair": worst_pair,
        "kappa": round(worst, 4),
        "interpretation": interpret(worst),
        "min_required": MIN_HUMAN_KAPPA,
        "enough_items": len(items) >= MIN_ITEMS,
        "passed": worst >= MIN_HUMAN_KAPPA and len(items) >= MIN_ITEMS,
    }


def majority_label(item: CalibrationItem) -> int | None:
    """The humans' consensus, or None when they tie. Ties are excluded from judge comparison:
    an item people cannot agree on cannot fairly judge a judge."""
    counts = Counter(item.labels.values())
    best, count = counts.most_common(1)[0]
    if list(counts.values()).count(count) > 1:
        return None
    return int(best)


def judge_agreement(
    items: list[CalibrationItem],
    judge_scores: dict[str, float],
    threshold: float = 0.5,
) -> dict:
    """Step 4: does the judge agree with the humans?

    `judge_scores` maps item_id to the judge's continuous score (RAGAS faithfulness is 0.0-1.0).
    It is cut at `threshold` into the same binary label the humans used, because kappa needs
    matching label sets. Report the threshold: moving it moves the kappa.
    """
    human: list[int] = []
    judge: list[int] = []
    skipped_tie: list[str] = []
    missing: list[str] = []
    for item in items:
        consensus = majority_label(item)
        if consensus is None:
            skipped_tie.append(item.item_id)
            continue
        if item.item_id not in judge_scores:
            missing.append(item.item_id)
            continue
        human.append(consensus)
        judge.append(int(judge_scores[item.item_id] >= threshold))

    if not human:
        raise CalibrationError(
            f"no comparable items (ties={len(skipped_tie)}, missing judge scores={len(missing)})"
        )
    kappa = cohens_kappa(human, judge)
    agreement = sum(1 for h, j in zip(human, judge, strict=True) if h == j) / len(human)
    return {
        "n_compared": len(human),
        "skipped_ties": skipped_tie,
        "missing_judge_scores": missing,
        "threshold": threshold,
        "raw_agreement": round(agreement, 4),
        "kappa": round(kappa, 4),
        "interpretation": interpret(kappa),
        "min_required": MIN_JUDGE_KAPPA,
        "passed": kappa >= MIN_JUDGE_KAPPA,
    }


def freeze(
    items: list[CalibrationItem],
    judge_model: str,
    rubric_path: Path | str | None = None,
) -> dict:
    """Step 5: a hash that pins what was calibrated.

    Record this in the report. If the calibration set, the rubric or the model changes, the hash
    changes, and any earlier judge number stops applying.
    """
    digest = hashlib.sha256()
    for item in sorted(items, key=lambda i: i.item_id):
        digest.update(item.item_id.encode())
        digest.update(item.rationale.encode())
        for context in item.contexts:
            digest.update(context.encode())
        for rater in item.rater_names():
            digest.update(f"{rater}={item.labels[rater]}".encode())
    digest.update(judge_model.encode())
    rubric_hash = None
    if rubric_path is not None:
        rubric_bytes = Path(rubric_path).read_bytes()
        rubric_hash = hashlib.sha256(rubric_bytes).hexdigest()
        digest.update(rubric_bytes)
    return {
        "frozen_hash": digest.hexdigest(),
        "judge_model": judge_model,
        "n_items": len(items),
        "rubric_sha256": rubric_hash,
    }


def report(items: list[CalibrationItem], judge_scores: dict[str, float] | None = None) -> str:
    """A terminal summary of the whole workflow, in step order."""
    human = inter_rater_reliability(items)
    lines = [
        "",
        "  step 2: do the people agree with each other?",
        f"    items                {human['n_items']} (need {MIN_ITEMS})",
        f"    raters               {', '.join(human['raters'])}",
        f"    worst pair           {human['worst_pair']}",
        f"    kappa                {human['kappa']:.4f}  ({human['interpretation']})",
        f"    required             {human['min_required']}",
        f"    verdict              {'PASS' if human['passed'] else 'FAIL'}",
    ]
    if not human["passed"]:
        lines += [
            "",
            "    The people do not agree well enough. Do not calibrate a judge against this.",
            "    Sharpen the rubric, relabel, and repeat step 2.",
        ]
        return "\n".join(lines + [""])

    if judge_scores is None:
        lines += ["", "    No judge scores given. Run the judge, then pass its scores in.", ""]
        return "\n".join(lines)

    judge = judge_agreement(items, judge_scores)
    lines += [
        "",
        "  step 4: does the judge agree with the people?",
        f"    compared             {judge['n_compared']}",
        f"    threshold            {judge['threshold']}",
        f"    raw agreement        {judge['raw_agreement']:.4f}",
        f"    kappa                {judge['kappa']:.4f}  ({judge['interpretation']})",
        f"    required             {judge['min_required']}",
        f"    verdict              {'PASS' if judge['passed'] else 'FAIL'}",
        "",
    ]
    return "\n".join(lines)
