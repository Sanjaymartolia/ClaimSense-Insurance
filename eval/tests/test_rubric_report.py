"""The framework rubric report checks its own arithmetic.

A scorecard whose sum is wrong is worse than no scorecard: it looks authoritative and misleads.
Writing this report produced exactly that error once — an "insurance-adjusted weights" example
whose weights added up to 105 and whose total was wrong by 0.06. A reader would not have caught
it. These tests do.

The structural checks (headings, cross-references) mirror `test_report_doc.py`, which guards the
evaluation harness report in the same way.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPORT = Path(__file__).resolve().parents[2] / "docs" / "FRAMEWORK_RUBRIC_SCORE.md"

#: The book's weights, from Table 3.2. The report must not silently change them: the user asked
#: for this exact rubric so the score stays comparable with any other project scored on it.
BOOK_WEIGHTS = {
    "D1": 15,
    "D2": 10,
    "D3": 15,
    "D4": 15,
    "D5": 5,
    "D6": 10,
    "D7": 15,
    "D8": 10,
    "D9": 5,
}


@pytest.fixture(scope="module")
def report_text() -> str:
    if not REPORT.exists():
        pytest.skip(f"{REPORT.name} not present")
    return REPORT.read_text(encoding="utf-8")


def section(text: str, number: int) -> str:
    """The text of one top-level section, `## <number>. ...` up to the next `## `.

    Parsing is scoped to a section rather than the whole document on purpose. The first version of
    these tests matched row shapes document-wide, and silently swallowed the weight-comparison
    table in Section 6, which has the same four-column shape as the scorecard. The tests then
    failed for the wrong reason. Narrow the input, not the pattern.
    """
    match = re.search(rf"^## {number}\. .*?(?=^## |\Z)", text, re.M | re.S)
    assert match, f"section {number} not found"
    return match.group(0)


def scorecard_rows(text: str) -> list[tuple[str, int, int, int]]:
    """Parse the Section 3 scorecard: (dimension, weight, score, weighted)."""
    pattern = re.compile(r"^\|\s*(D\d)\b[^|]*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|", re.M)
    return [
        (m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)))
        for m in pattern.finditer(section(text, 3))
    ]


def improvement_gains(text: str) -> list[float]:
    """Every `+N.NN` in a Section 7 **table row**, ignoring the prose around it.

    The prose repeats the totals ("worth +1.20", "T16 alone is worth +0.55"). Counting those would
    double-count the very figures the test is checking.
    """
    rows = [ln for ln in section(text, 7).splitlines() if ln.strip().startswith("|")]
    return [float(g) for row in rows for g in re.findall(r"\+(\d\.\d\d)", row)]


def stated_total(text: str) -> float:
    """The total the report prints, from the `**Result: X out of 5.**` line near the top."""
    match = re.search(r"\*\*Result:\s*([\d.]+)\s*out of 5", text)
    assert match, "the report does not state a result"
    return float(match.group(1))


# ------------------------------------------------------------------ the scorecard
def test_the_scorecard_has_all_nine_dimensions(report_text):
    rows = scorecard_rows(report_text)
    assert [r[0] for r in rows] == list(BOOK_WEIGHTS), f"got {[r[0] for r in rows]}"


def test_the_weights_are_the_books_weights_unchanged(report_text):
    """The user asked for this exact rubric. Changing a weight silently would break the comparison
    the rubric exists to make."""
    for dim, weight, _score, _weighted in scorecard_rows(report_text):
        assert weight == BOOK_WEIGHTS[dim], f"{dim}: weight {weight}, book says {BOOK_WEIGHTS[dim]}"


def test_the_weights_sum_to_one_hundred(report_text):
    assert sum(r[1] for r in scorecard_rows(report_text)) == 100


def test_every_score_is_in_range(report_text):
    for dim, _weight, score, _weighted in scorecard_rows(report_text):
        assert 0 <= score <= 5, f"{dim}: score {score} is outside 0-5"


def test_each_weighted_cell_equals_score_times_weight(report_text):
    for dim, weight, score, weighted in scorecard_rows(report_text):
        assert weighted == score * weight, (
            f"{dim}: table says {weighted}, but {score} x {weight} = {score * weight}"
        )


def test_the_stated_total_equals_the_recomputed_sum(report_text):
    """The check that would have caught the 105-weight error."""
    rows = scorecard_rows(report_text)
    recomputed = sum(r[3] for r in rows) / 100
    assert stated_total(report_text) == pytest.approx(recomputed, abs=0.005), (
        f"the report states {stated_total(report_text)}, the table sums to {recomputed}"
    )


def test_the_total_row_matches_the_recomputed_sum(report_text):
    """Section 3's total row prints the raw weighted sum. It must agree with the rows above it."""
    rows = scorecard_rows(report_text)
    expected = sum(r[3] for r in rows)
    assert f"**{expected}**" in report_text, f"no total row showing {expected}"


# ------------------------------------------------------------------ the improvement table
def test_the_headline_improvement_claim_is_arithmetically_sound(report_text):
    """Section 7.1 states what the top four items are worth and where they land. Check the claim
    against the table and the scorecard. It is read from the report, not pinned here: each Issue
    changes it (Issue 2: +0.80 to 3.65; Issue 4: +0.65 to 3.95)."""
    claim = re.search(
        r"worth \+(\d\.\d\d) together, and they take the score from (\d\.\d\d) to\s+"
        r"about \*\*(\d\.\d\d)\*\*",
        section(report_text, 7),
    )
    assert claim, "Section 7.1 states no headline claim"
    worth, start, land = (float(g) for g in claim.groups())
    current = sum(r[3] for r in scorecard_rows(report_text)) / 100
    gains = improvement_gains(report_text)
    assert gains, "no gain figures found in the Section 7 table"
    top_four = sum(sorted(gains, reverse=True)[:4])
    assert start == pytest.approx(current, abs=0.005), f"7.1 starts at {start}, not {current}"
    assert worth == pytest.approx(top_four, abs=0.005), f"7.1 says +{worth}, rows sum {top_four}"
    assert land == pytest.approx(current + top_four, abs=0.005)


# ------------------------------------------------------------------ structure
def test_subsection_numbers_have_no_gaps(report_text):
    found: dict[int, list[int]] = {}
    for line in report_text.splitlines():
        match = re.match(r"^### (\d+)\.(\d+) ", line)
        if match:
            found.setdefault(int(match.group(1)), []).append(int(match.group(2)))
    for major, minors in sorted(found.items()):
        assert minors == list(range(1, len(minors) + 1)), f"section {major} is numbered {minors}"


def test_every_cross_reference_resolves(report_text):
    headings: set[str] = set()
    for line in report_text.splitlines():
        major = re.match(r"^## (\d+)\.\s", line)
        if major:
            headings.add(major.group(1))
        minor = re.match(r"^### (\d+)\.(\d+) ", line)
        if minor:
            headings.add(f"{minor.group(1)}.{minor.group(2)}")
    referenced = set(re.findall(r"[Ss]ection (\d+(?:\.\d+)?)", report_text))
    assert sorted(referenced - headings) == []


# ------------------------------------------------------------------ the scorer command
def test_the_scorer_agrees_with_the_report(report_text):
    """`python -m eval.tools.rubric_score` recomputes the total from the parsed table rather than
    reading the report's stated total. The two must therefore agree independently."""
    from eval.tools.rubric_score import parse_scorecard

    rows = parse_scorecard(report_text)
    assert len(rows) == 9
    recomputed = sum(r["weighted"] for r in rows) / 100
    assert recomputed == pytest.approx(stated_total(report_text), abs=0.005)


def test_the_scorer_runs_and_prints_the_score(capsys, report_text):
    """A guard against the tool crashing on a default Windows console: the report contains
    characters (an arrow) that cp1252 cannot encode, which raised UnicodeEncodeError once. The
    score it prints is the report's own, not a number pinned here (each Issue changes it)."""
    from eval.tools.rubric_score import main

    assert main(["--plan", "--insurance"]) == 0
    out = capsys.readouterr().out
    assert f"SCORE: {stated_total(report_text):.2f} out of 5" in out
    assert "->" in out, "the arrow should be transliterated, not dropped"
    assert out.isascii(), "output must be printable on a cp1252 console"


def test_the_scorer_json_is_valid_and_self_consistent(capsys):
    import json as _json

    from eval.tools.rubric_score import main

    assert main(["--json"]) == 0
    payload = _json.loads(capsys.readouterr().out)
    assert payload["weights_sum"] == 100
    assert payload["score"] == pytest.approx(payload["weighted_sum"] / 100, abs=0.005)
    assert len(payload["dimensions"]) == 9


def test_the_docx_can_be_built(tmp_path):
    pytest.importorskip("docx", reason='needs pip install -e ".[docs]"')
    if not REPORT.exists():
        pytest.skip(f"{REPORT.name} not present")
    from eval.tools.build_report_docx import build

    target = tmp_path / "rubric.docx"
    build(source=REPORT, target=target)
    assert target.stat().st_size > 10_000

    from docx import Document

    document = Document(target)
    assert document.tables, "the scorecard table did not survive the conversion"
