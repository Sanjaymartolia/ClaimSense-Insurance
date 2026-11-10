"""L13 section 8.9: the A/B test on live traffic.

The offline suite compares two variants on the same fixed claims. Online, each member is routed to
one arm, so the two arms see different claims and the comparison needs a test:

    cost, latency      skewed, so compare ranks: Mann-Whitney U
    handled correctly  a yes/no per claim: Fisher's exact test on the 2 x 2 table

Both tests are written out here in plain Python (no SciPy in this project's dependencies) and
checked against published values in `eval/tests/test_monitoring.py`.

One difference from the notebook. It leaves blocked claims out, because its guardrail treats both
arms alike. Here the guardrail *is* the difference between the default arms (A = `v1`, B =
`guarded`), so blocked claims stay in and are scored like any other claim.

The result is evidence for a person, not a decision: nothing here says "ship".
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence


# ----------------------------------------------------------------------------------- tests
def mann_whitney_u(x: Sequence[float], y: Sequence[float]) -> tuple[float, float]:
    """Two-sided Mann-Whitney U test. Returns (U of x, p).

    Normal approximation with tie and continuity corrections, the same as
    `scipy.stats.mannwhitneyu(x, y, method="asymptotic")`. Good from about eight values a side.
    If every value is the same (stub mode: all costs are zero) the test has nothing to rank and
    p is 1.
    """
    n1, n2 = len(x), len(y)
    if not n1 or not n2:
        return math.nan, math.nan
    ordered = sorted([(v, 0) for v in x] + [(v, 1) for v in y])
    n = n1 + n2
    rank_sum_x, tie_term, i = 0.0, 0.0, 0
    while i < n:
        j = i
        while j < n and ordered[j][0] == ordered[i][0]:
            j += 1
        tied = j - i
        rank = (i + 1 + j) / 2  # the mean of ranks i+1 .. j
        rank_sum_x += rank * sum(1 for k in range(i, j) if ordered[k][1] == 0)
        tie_term += tied**3 - tied
        i = j
    u = rank_sum_x - n1 * (n1 + 1) / 2
    variance = n1 * n2 / 12 * ((n + 1) - tie_term / (n * (n - 1)))
    if variance <= 0:
        return u, 1.0
    z = (abs(u - n1 * n2 / 2) - 0.5) / math.sqrt(variance)
    return u, min(1.0, math.erfc(max(z, 0.0) / math.sqrt(2)))


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher's exact test on the table [[a, b], [c, d]]. Returns p.

    Sums the probability of every table with the same margins that is no more likely than the one
    observed (the usual two-sided rule, as in `scipy.stats.fisher_exact`).
    """
    row1, row2, col1, n = a + b, c + d, a + c, a + b + c + d
    if n == 0:
        return 1.0

    def log_choose(top: int, k: int) -> float:
        return math.lgamma(top + 1) - math.lgamma(k + 1) - math.lgamma(top - k + 1)

    def log_p(k: int) -> float:
        return log_choose(row1, k) + log_choose(row2, col1 - k) - log_choose(n, col1)

    observed = log_p(a)
    lo, hi = max(0, col1 - row2), min(row1, col1)
    total = sum(math.exp(log_p(k)) for k in range(lo, hi + 1) if log_p(k) <= observed + 1e-9)
    return min(1.0, total)


# --------------------------------------------------------------------------------- summary
def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def arm_summary(rows: Sequence[dict]) -> dict:
    """One arm's numbers. Latency, cost and model calls are over claims that reached the agents."""
    ran = [r for r in rows if r["outcome"] != "blocked"]
    checked = [r for r in rows if r["payload_ok"] is not None]
    correct = sum(bool(r["correct"]) for r in rows)
    return {
        "claims": len(rows),
        "correct": correct,
        "correct_share": _share(correct, len(rows)),
        "blocked": sum(r["outcome"] == "blocked" for r in rows),
        "errors": sum(r["outcome"] == "error" for r in rows),
        "cost_per_claim_usd": round(statistics.mean(r["cost_usd"] for r in rows), 6)
        if rows
        else None,
        "p50_seconds": round(statistics.median(r["seconds"] for r in ran), 4) if ran else None,
        "mean_llm_calls": round(statistics.mean(r["llm_calls"] for r in ran), 2) if ran else None,
        "payload_ok_share": _share(sum(bool(r["payload_ok"]) for r in checked), len(checked)),
    }


def _correct_test(a_rows: Sequence[dict], b_rows: Sequence[dict]) -> dict:
    a_ok = sum(bool(r["correct"]) for r in a_rows)
    b_ok = sum(bool(r["correct"]) for r in b_rows)
    return {
        "A": {"claims": len(a_rows), "correct": a_ok, "share": _share(a_ok, len(a_rows))},
        "B": {"claims": len(b_rows), "correct": b_ok, "share": _share(b_ok, len(b_rows))},
        "fisher_p": round(fisher_exact(a_ok, len(a_rows) - a_ok, b_ok, len(b_rows) - b_ok), 6),
    }


def compare(records: Sequence[dict], arms: dict[str, str]) -> dict:
    """The whole 8.9 result from the live rows: per-arm summary, three tests, two slices."""
    a = [r for r in records if r["arm"] == "A"]
    b = [r for r in records if r["arm"] == "B"]
    ran_a = [r for r in a if r["outcome"] != "blocked"]
    ran_b = [r for r in b if r["outcome"] != "blocked"]
    _, p_seconds = mann_whitney_u([r["seconds"] for r in ran_a], [r["seconds"] for r in ran_b])
    _, p_cost = mann_whitney_u([r["cost_usd"] for r in a], [r["cost_usd"] for r in b])
    return {
        "arms": dict(arms),
        "A": arm_summary(a),
        "B": arm_summary(b),
        "tests": {
            "handled_correctly": _correct_test(a, b),
            "seconds_mann_whitney_p": None if math.isnan(p_seconds) else round(p_seconds, 6),
            "cost_mann_whitney_p": None if math.isnan(p_cost) else round(p_cost, 6),
        },
        "slices": {
            "attacked claims": _correct_test(
                [r for r in a if r["attacked"]], [r for r in b if r["attacked"]]
            ),
            "clean claims": _correct_test(
                [r for r in a if not r["attacked"]], [r for r in b if not r["attacked"]]
            ),
        },
        # A clean claim the guardrail stopped is a false alarm: work for a person, for nothing.
        "clean_claims_blocked": {
            arm: sum(r["outcome"] == "blocked" and not r["attacked"] for r in rows)
            for arm, rows in (("A", a), ("B", b))
        },
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _p(value: float | None) -> str:
    if value is None:
        return "n/a"
    return "< 0.0001" if value < 0.0001 else f"{value:.4f}"


def format_report(result: dict) -> str:
    """The 8.9 printout."""
    arms = result["arms"]
    lines = [f"{'':<26}{'A (' + arms['A'] + ')':>18}{'B (' + arms['B'] + ')':>18}"]
    rows = (
        ("claims", "claims", str),
        ("handled correctly", "correct_share", _pct),
        ("blocked by the guardrail", "blocked", str),
        ("pipeline errors", "errors", str),
        (
            "cost per claim (USD)",
            "cost_per_claim_usd",
            lambda v: "n/a" if v is None else f"{v:.4f}",
        ),
        ("P50 seconds", "p50_seconds", lambda v: "n/a" if v is None else f"{v:.3f}"),
        ("model calls per claim", "mean_llm_calls", lambda v: "n/a" if v is None else f"{v:.1f}"),
        ("payload code checks ok", "payload_ok_share", _pct),
    )
    for label, key, fmt in rows:
        lines.append(f"{label:<26}{fmt(result['A'][key]):>18}{fmt(result['B'][key]):>18}")
    tests = result["tests"]
    overall = _p(tests["handled_correctly"]["fisher_p"])
    lines += ["", f"handled correctly, all claims   Fisher's exact p = {overall}"]
    for name, t in result["slices"].items():
        lines.append(
            f"  {name:<16} A {t['A']['correct']}/{t['A']['claims']} ({_pct(t['A']['share'])})   "
            f"B {t['B']['correct']}/{t['B']['claims']} ({_pct(t['B']['share'])})   "
            f"p = {_p(t['fisher_p'])}"
        )
    blocked = result["clean_claims_blocked"]
    lines += [
        f"clean claims blocked (false alarms)   A {blocked['A']}   B {blocked['B']}",
        f"seconds per claim   Mann-Whitney p = {_p(tests['seconds_mann_whitney_p'])}",
        f"cost per claim      Mann-Whitney p = {_p(tests['cost_mann_whitney_p'])}",
        "",
        "This is evidence, not a decision: a p-value does not weigh a false alarm against a",
        "missed injection. A person decides.",
    ]
    return "\n".join(lines)
