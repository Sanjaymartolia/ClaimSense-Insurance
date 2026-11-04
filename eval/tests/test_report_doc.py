"""The report is a deliverable, so its integrity is tested like code.

Two kinds of test here.

The **document** tests read `docs/EVAL_HARNESS_REPORT.md` and check it is internally consistent.
They exist because an earlier edit silently deleted subsection 9.5 and left a cross-reference
pointing at a heading that had moved. Nobody notices a renumbering by reading; a test does.

The **builder** test checks that the DOCX can still be produced from that Markdown. It skips when
`python-docx` is absent, because the builder is not on the scoring path and its dependency is
optional.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPORT = Path(__file__).resolve().parents[2] / "docs" / "EVAL_HARNESS_REPORT.md"


@pytest.fixture(scope="module")
def report_lines() -> list[str]:
    if not REPORT.exists():
        pytest.skip(f"{REPORT.name} not present")
    return REPORT.read_text(encoding="utf-8").splitlines()


def subsections(lines: list[str]) -> dict[int, list[int]]:
    """`{major: [minor, ...]}` in document order."""
    found: dict[int, list[int]] = {}
    for line in lines:
        match = re.match(r"^### (\d+)\.(\d+) ", line)
        if match:
            found.setdefault(int(match.group(1)), []).append(int(match.group(2)))
    return found


def headings(lines: list[str]) -> set[str]:
    """Every heading a cross-reference may legitimately name: "10" and "10.8" alike."""
    out: set[str] = set()
    for line in lines:
        major = re.match(r"^## (\d+)\.\s", line)
        if major:
            out.add(major.group(1))
        minor = re.match(r"^### (\d+)\.(\d+) ", line)
        if minor:
            out.add(f"{minor.group(1)}.{minor.group(2)}")
    return out


def test_subsection_numbers_have_no_gaps(report_lines):
    """Guards the real regression: an edit replaced the 9.5 heading instead of inserting above it,
    so the report jumped from 9.4 to 9.6."""
    for major, minors in sorted(subsections(report_lines).items()):
        assert minors == list(range(1, len(minors) + 1)), (
            f"section {major} is numbered {minors}; expected 1..{len(minors)} with no gaps"
        )


def test_every_cross_reference_resolves(report_lines):
    """A reference to a section that does not exist sends the reader nowhere."""
    text = "\n".join(report_lines)
    referenced = set(re.findall(r"[Ss]ection (\d+(?:\.\d+)?)", text))
    dangling = sorted(referenced - headings(report_lines))
    assert dangling == [], f"these references name no heading: {dangling}"


def test_the_test_count_in_the_report_matches_reality(report_lines):
    """The report states a test total in two places. Both drift the moment a test is added.

    This compares them with the real count, so the report cannot quietly go stale.
    """
    import subprocess  # noqa: S404 - collecting our own tests, no external input
    import sys

    # `sys.executable`, not "python": the same interpreter that is running this test must do the
    # collecting, or a different environment could report a different count.
    #
    # `-o addopts=` clears the `-q` that pyproject.toml adds. With -q, pytest suppresses the
    # "N tests collected" line this test needs.
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            "eval/tests",
            "--collect-only",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
        ],
        capture_output=True,
        text=True,
        cwd=REPORT.parents[1],
        check=False,
    )
    match = re.search(r"(\d+) tests? collected", result.stdout)
    if not match:
        pytest.skip("could not collect the test count")
    actual = int(match.group(1))

    # Targeted patterns, not a bare `(\d+) tests`: the report also discusses the 9 tests in
    # tests/orchestration (section 9.1), and that number must not be mistaken for this suite's.
    text = "\n".join(report_lines)
    claimed = {
        int(n)
        for pattern in (
            r"harness has (\d+) tests",
            r"All (\d+) tests must pass",
            r"`eval/tests/`\s*\|\s*(\d+) tests",
        )
        for n in re.findall(pattern, text)
    }
    assert claimed, "the report states no test count for this suite at all"
    assert claimed == {actual}, (
        f"the report says {sorted(claimed)} tests, but {actual} are collected. "
        "Update docs/EVAL_HARNESS_REPORT.md and rebuild the DOCX."
    )


def test_the_docx_can_still_be_built(tmp_path):
    pytest.importorskip("docx", reason='needs pip install -e ".[docs]"')
    from eval.tools.build_report_docx import build

    if not REPORT.exists():
        pytest.skip(f"{REPORT.name} not present")
    target = tmp_path / "out.docx"
    written = build(source=REPORT, target=target)
    assert written == target
    assert target.stat().st_size > 10_000

    from docx import Document

    document = Document(target)
    style_names = {p.style.name for p in document.paragraphs}
    assert "Heading 1" in style_names, "section headings did not survive the conversion"
    assert document.tables, "the report's tables did not survive the conversion"
