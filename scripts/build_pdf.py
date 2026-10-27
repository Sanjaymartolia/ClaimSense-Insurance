"""Renders docs/TECHNICAL_WORKFLOW.md to HTML and PDF (via headless Edge or Chrome).

python scripts/build_pdf.py   ->  docs/ClaimSense_Technical_Workflow.html / .pdf
Supports the Markdown subset the paper uses: headings, paragraphs, lists, tables,
indented code blocks, images, **bold**, *italic*, `code`.
"""

import html
import re
import shutil
import subprocess
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"
SRC = DOCS / "TECHNICAL_WORKFLOW.md"
HTML_OUT = DOCS / "ClaimSense_Technical_Workflow.html"
PDF_OUT = DOCS / "ClaimSense_Technical_Workflow.pdf"
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "msedge",
    "google-chrome",
    "chromium",
]

CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: Georgia, 'Times New Roman', serif; font-size: 10.5pt; line-height: 1.45;
       color: #1a1a1a; max-width: 900px; margin: 0 auto; }
h1 { font-size: 20pt; color: #1f3864; margin: 0 0 6px; line-height: 1.2; }
h2 { font-size: 14pt; color: #1f3864; border-bottom: 1.5px solid #1f3864; padding-bottom: 3px;
     margin-top: 22px; page-break-after: avoid; }
h3 { font-size: 11.5pt; color: #2f5496; margin-top: 14px; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 12px; font-size: 9pt;
        font-family: Arial, Helvetica, sans-serif; page-break-inside: avoid; }
th { background: #1f3864; color: #fff; text-align: left; padding: 5px 6px; }
td { border: 1px solid #c9ced6; padding: 4px 6px; vertical-align: top; }
tr:nth-child(even) td { background: #f4f6fa; }
code { font-family: Consolas, monospace; font-size: 9pt; background: #f1f3f5; padding: 0 3px;
       border-radius: 3px; }
pre { background: #f6f8fa; border: 1px solid #dde1e6; padding: 8px 10px; font-size: 8.8pt;
      line-height: 1.35; page-break-inside: avoid; white-space: pre-wrap; }
pre code { background: none; padding: 0; }
img { width: 100%; border: 1px solid #dde1e6; margin: 6px 0; }
hr { border: none; border-top: 1px solid #c9ced6; margin: 14px 0; }
em { color: #444; }
ul, ol { margin: 4px 0 8px 20px; padding: 0; }
"""


def inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img alt="\1" src="\2">', text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![*\w])\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    return text


def convert(md: str) -> str:
    lines = md.splitlines()
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif line.startswith("    "):
            block = []
            while i < len(lines) and (lines[i].startswith("    ") or not lines[i].strip()):
                block.append(lines[i][4:])
                i += 1
            out.append("<pre><code>" + html.escape("\n".join(block).rstrip()) + "</code></pre>")
        elif m := re.match(r"(#{1,3}) (.*)", line):
            n = len(m.group(1))
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
            i += 1
        elif line.strip() == "---":
            out.append("<hr>")
            i += 1
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head, body = rows[0], [r for r in rows[2:]]
            t = ["<table>"]
            if any(head):
                t.append("<tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr>")
            for r in body:
                t.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
            out.append("".join(t) + "</table>")
        elif re.match(r"(\d+\.|-) ", line):
            ordered = line[0].isdigit()
            items = []
            while i < len(lines) and (
                re.match(r"(\d+\.|-) ", lines[i])
                or (lines[i].startswith("   ") and lines[i].strip())
            ):
                if re.match(r"(\d+\.|-) ", lines[i]):
                    items.append(re.sub(r"^(\d+\.|-) ", "", lines[i]))
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
        else:
            para = []
            while (
                i < len(lines)
                and lines[i].strip()
                and not re.match(r"(#{1,3} |\||---$|    |(\d+\.|-) )", lines[i])
            ):
                para.append(lines[i].strip())
                i += 1
            out.append(f"<p>{inline(' '.join(para))}</p>")
    return "\n".join(out)


def find_browser() -> str:
    for b in BROWSERS:
        if Path(b).exists() or shutil.which(b):
            return b
    raise SystemExit("No Edge/Chrome found; open the HTML file and print to PDF instead.")


def main() -> None:
    body = convert(SRC.read_text(encoding="utf-8"))
    HTML_OUT.write_text(
        f'<!doctype html><html><head><meta charset="utf-8"><title>ClaimSense Technical '
        f"Workflow</title><style>{CSS}</style></head><body>{body}</body></html>",
        encoding="utf-8",
    )
    subprocess.run(
        [
            find_browser(),
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={PDF_OUT}",
            HTML_OUT.as_uri(),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    print("wrote", HTML_OUT, "and", PDF_OUT)


if __name__ == "__main__":
    main()
