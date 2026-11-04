"""Build the evaluation harness report DOCX from its Markdown source.

    python -m eval.tools.build_report_docx

Needs `python-docx`, which is in the `docs` extra:

    pip install -e ".[docs]"

The Markdown is the source of truth. `CLAUDE.md` says to edit the Markdown and then build again,
and never to edit a generated PDF, DOCX or HTML by hand. This script is what makes that possible
for `docs/EVAL_HARNESS_REPORT.md`; `scripts/build_team_guide.py` does the same job for the team
guide.

It handles the Markdown that the report actually uses, and no more: ATX headings, pipe tables,
fenced and indented code, bullet and numbered lists, bold and inline-code runs, and horizontal
rules. It is not a general Markdown converter, and it should not grow into one. If the report
starts needing a feature that is missing, prefer rewording the report.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

#: Repository root, found from this file, so the script runs from any working directory.
REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "docs" / "EVAL_HARNESS_REPORT.md"
TARGET = REPO_ROOT / "docs" / "ClaimSense_Eval_Harness_Report.docx"

#: One pattern for both inline spans, so a single pass keeps them in document order.
INLINE = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`")


def add_runs(paragraph, text: str) -> None:
    """Write `text` into `paragraph`, honouring `**bold**` and `` `code` `` spans."""
    from docx.shared import Pt

    position = 0
    for match in INLINE.finditer(text):
        if match.start() > position:
            paragraph.add_run(text[position : match.start()])
        if match.group(1) is not None:
            paragraph.add_run(match.group(1)).bold = True
        else:
            run = paragraph.add_run(match.group(2))
            run.font.name = "Consolas"
            run.font.size = Pt(9.5)
        position = match.end()
    if position < len(text):
        paragraph.add_run(text[position:])


def split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_separator(line: str) -> bool:
    """True for a table's `|---|---|` rule, which marks the row above it as the header."""
    return bool(re.fullmatch(r"\|[\s\-:|]+\|", line.strip()))


def _add_code_line(document, text: str) -> None:
    from docx.shared import Pt, RGBColor

    paragraph = document.add_paragraph()
    paragraph.paragraph_format.left_indent = Pt(18)
    paragraph.paragraph_format.space_after = Pt(0)
    run = paragraph.add_run(text)
    run.font.name = "Consolas"
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)


def build(source: Path = SOURCE, target: Path = TARGET) -> Path:
    """Convert `source` to `target`. Returns the path written."""
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Pt
    except ImportError as e:  # pragma: no cover - depends on the optional extra
        raise SystemExit(
            f'python-docx is not installed ({e}). Run: pip install -e ".[docs]"'
        ) from e

    if not source.exists():
        raise SystemExit(f"{source} not found")

    lines = source.read_text(encoding="utf-8").splitlines()
    document = Document()
    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        # fenced code block
        if stripped.startswith("```"):
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                _add_code_line(document, lines[index])
                index += 1
            index += 1
            continue

        # pipe table: a header row followed by a separator rule
        if stripped.startswith("|") and index + 1 < len(lines) and is_separator(lines[index + 1]):
            header = split_row(stripped)
            index += 2
            body: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                body.append(split_row(lines[index].strip()))
                index += 1
            table = document.add_table(rows=1, cols=len(header))
            table.style = "Light Grid Accent 1"
            for cell, cell_text in zip(table.rows[0].cells, header, strict=False):
                cell.text = ""
                add_runs(cell.paragraphs[0], cell_text)
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.bold = True
            for row in body:
                cells = table.add_row().cells
                for cell, cell_text in zip(cells, row, strict=False):
                    cell.text = ""
                    add_runs(cell.paragraphs[0], cell_text)
            document.add_paragraph()
            continue

        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading:
            level = len(heading.group(1))
            if level == 1:
                paragraph = document.add_heading("", level=0)
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            else:
                paragraph = document.add_heading("", level=level - 1)
            add_runs(paragraph, heading.group(2))
            index += 1
            continue

        if stripped == "---":
            document.add_paragraph("_" * 78).alignment = WD_ALIGN_PARAGRAPH.CENTER
            index += 1
            continue

        if not stripped:
            index += 1
            continue

        # four-space indented code, but not an indented list item
        if line.startswith("    ") and not re.match(r"^\s*[-*\d]", stripped):
            _add_code_line(document, stripped)
            index += 1
            continue

        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        if bullet:
            add_runs(document.add_paragraph(style="List Bullet"), bullet.group(1))
            index += 1
            continue

        numbered = re.match(r"^\d+\.\s+(.*)$", stripped)
        if numbered:
            add_runs(document.add_paragraph(style="List Number"), numbered.group(1))
            index += 1
            continue

        # ordinary paragraph: join the wrapped lines back into one
        buffer = [stripped]
        index += 1
        while index < len(lines):
            nxt = lines[index].strip()
            if (
                not nxt
                or nxt.startswith(("|", "#", "```", "---"))
                or re.match(r"^([-*]|\d+\.)\s", nxt)
                or lines[index].startswith("    ")
            ):
                break
            buffer.append(nxt)
            index += 1
        add_runs(document.add_paragraph(), " ".join(buffer))

    target.parent.mkdir(parents=True, exist_ok=True)
    document.save(target)
    return target


def main() -> int:
    written = build()
    print(f"wrote {written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
