"""Generates the ClaimSense flow diagram as an Excalidraw file and a matching SVG.

python scripts/build_diagram.py   ->  docs/diagrams/claimsense-flow.excalidraw / .svg
Edit the BOXES / ARROWS tables below, then re-run.
"""

import json
import random
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parents[1] / "docs" / "diagrams"

STYLES = {
    "control": ("#c92a2a", "#ffe3e3"),
    "orch": ("#1971c2", "#e7f5ff"),
    "agent": ("#343a40", "#f8f9fa"),
    "mcp": ("#0c8599", "#e3fafc"),
    "store": ("#e67700", "#fff4e6"),
    "ops": ("#495057", "#f1f3f5"),
}

W = 190
# id: (x, y, w, h, style, label)
BOXES = {
    "user": (40, 40, 220, 70, "control", "Claims adjudicator\ninsurer / TPA desk"),
    "ui": (
        300,
        40,
        220,
        70,
        "agent",
        "① Case UI + FastAPI  [L16]\nupload packet · stream worksheet",
    ),
    "ing": (560, 40, 240, 70, "control", "Input guardrails  [L15]\nmask health data · docs = data"),
    "outg": (
        840,
        40,
        240,
        70,
        "control",
        "⑧ Output guardrails  [L15]\ndeductions cited · totals · right patient",
    ),
    "sup": (
        40,
        170,
        1040,
        70,
        "orch",
        "② Supervisor + Planner (LangGraph)  [L8 · L10]\nplan: extract → admissibility → line items → fraud screen → critic → approve → settle · checkpointer",
    ),
    "mem": (
        1120,
        170,
        240,
        200,
        "store",
        "⑨ Memory  [L9]\n\nclaim history per policy\nsub-limits used\nbills already seen\n\napproved adjudicator lessons",
    ),
    "ext": (
        40,
        300,
        W,
        70,
        "agent",
        "③ Extraction agent  [L11]\nfields + line items\nwith source spans",
    ),
    "cov": (
        250,
        300,
        W,
        70,
        "agent",
        "④ Coverage analyst  [L11]\nclause per line ·\ncalls calculator",
    ),
    "fra": (
        460,
        300,
        W,
        70,
        "agent",
        "⑤ Fraud analyst  [L11]\nduplicates · tariff\noutliers · dates",
    ),
    "cri": (
        670,
        300,
        W,
        70,
        "agent",
        "⑥ Critic  [L11]\nre-checks citations\n+ arithmetic (1 revision)",
    ),
    "set": (
        890,
        300,
        W,
        70,
        "agent",
        "Settlement agent  [L11]\nworksheet + letter ·\nsettles after approval",
    ),
    "hooks": (
        40,
        420,
        820,
        50,
        "ops",
        "Hooks  [L14]   pre-tool: permission + budget check   ·   post-tool: trace, health data scrubbed",
    ),
    "gate": (
        890,
        410,
        W,
        70,
        "control",
        "⑦ Approval gate  [L14]\ninterrupt() on worksheet hash\n2 levels above threshold",
    ),
    "human": (
        1120,
        410,
        240,
        70,
        "control",
        "Adjudicator (+ senior)\napprove · edit a line · reject",
    ),
    "kb": (40, 520, W, 60, "mcp", "policy-kb  [L7]  (read)\nsearch wording · get clause"),
    "calc": (
        250,
        520,
        W,
        60,
        "mcp",
        "adjudication-calc  [L7]  (read)\ncaps · proportional cut · co-pay",
    ),
    "tar": (460, 520, W, 60, "mcp", "tariff  [L7]  (read)\nexpected cost range"),
    "db": (890, 520, W, 60, "mcp", "claims-db  [L7]\nhistory (read) · settle_claim (WRITE)"),
    "idx": (40, 630, W, 60, "store", "Hybrid index  [L5 · L6]\nBM25 + vectors + reranker"),
    "code": (250, 630, W, 60, "store", "Calculator\nplain Python, Decimal, unit-tested"),
    "tt": (460, 630, W, 60, "store", "Tariff table\n30 procedures × 3 city tiers"),
    "cdb": (890, 630, W, 60, "store", "Claims DB\npolicies · claims · settlements"),
    "ingest": (40, 750, W, 60, "store", "Ingestion  [L4 · L5]\npolicy PDF → numbered clauses"),
    "tr": (270, 750, 170, 60, "ops", "Traces  [L13]\nhealth data masked"),
    "graf": (
        455,
        750,
        170,
        60,
        "ops",
        "Metrics + Grafana  [L13 · L16]\nedit rate · ₹ deducted by reason",
    ),
    "eval": (640, 750, 170, 60, "ops", "Eval harness  [L13 · L15]\n80 claims · judge · red team"),
    "refl": (825, 750, 170, 60, "ops", "Improvement loop  [L12]\nplaybook from adjudicator edits"),
    "ci": (1010, 750, 170, 60, "ops", "CI/CD  [L16]\neval gate · Docker Compose"),
}
LABELS = [(270, 725, "Operate and measure (runs alongside every request)")]


def anchor(box_id, side):
    x, y, w, h, *_ = BOXES[box_id]
    return {
        "top": (x + w / 2, y),
        "bottom": (x + w / 2, y + h),
        "left": (x, y + h / 2),
        "right": (x + w, y + h / 2),
    }[side]


def at(box_id, side, dx=0):
    px, py = anchor(box_id, side)
    return (px + dx, py)


# list of point lists; optional "both" for two-way arrows
ARROWS = [
    ([anchor("user", "right"), anchor("ui", "left")], True),
    ([anchor("ui", "right"), anchor("ing", "left")], False),
    ([anchor("ing", "bottom"), (680, 170)], False),
    ([(985, 170), anchor("outg", "bottom")], False),
    ([at("outg", "top"), (960, 18), (410, 18), at("ui", "top")], False),
    ([anchor("sup", "right"), (1120, 205)], True),
    ([(135, 240), anchor("ext", "top")], True),
    ([(345, 240), anchor("cov", "top")], True),
    ([(555, 240), anchor("fra", "top")], True),
    ([(765, 240), anchor("cri", "top")], True),
    ([(985, 240), anchor("set", "top")], True),
    ([anchor("ext", "bottom"), (135, 420)], False),
    ([anchor("cov", "bottom"), (345, 420)], False),
    ([anchor("fra", "bottom"), (555, 420)], False),
    ([anchor("cri", "bottom"), (765, 420)], False),
    ([anchor("set", "bottom"), anchor("gate", "top")], False),
    ([anchor("gate", "right"), anchor("human", "left")], True),
    ([anchor("gate", "bottom"), anchor("db", "top")], False),
    ([(135, 470), anchor("kb", "top")], False),
    ([(345, 470), anchor("calc", "top")], False),
    ([(555, 470), anchor("tar", "top")], False),
    ([anchor("kb", "bottom"), anchor("idx", "top")], False),
    ([anchor("calc", "bottom"), anchor("code", "top")], False),
    ([anchor("tar", "bottom"), anchor("tt", "top")], False),
    ([anchor("db", "bottom"), anchor("cdb", "top")], False),
    ([anchor("ingest", "top"), anchor("idx", "bottom")], False),
]
REPLY_LABEL = (660, 10, "reply")

rnd = random.Random(7)


def base(eid, etype, x, y, w, h, stroke="#1e1e1e", bg="transparent", dashed=False):
    return {
        "id": eid,
        "type": etype,
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "angle": 0,
        "strokeColor": stroke,
        "backgroundColor": bg,
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "dashed" if dashed else "solid",
        "roughness": 1,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "roundness": None,
        "seed": rnd.randint(1, 2**31),
        "version": 1,
        "versionNonce": rnd.randint(1, 2**31),
        "isDeleted": False,
        "boundElements": [],
        "updated": 1,
        "link": None,
        "locked": False,
    }


def text_el(eid, x, y, w, h, text, size=14, container=None, color="#1e1e1e", align="center"):
    el = base(eid, "text", x, y, w, h, stroke=color)
    el.update(
        {
            "text": text,
            "originalText": text,
            "fontSize": size,
            "fontFamily": 2,
            "textAlign": align,
            "verticalAlign": "middle",
            "containerId": container,
            "lineHeight": 1.25,
            "autoResize": True,
        }
    )
    return el


def build_excalidraw():
    elements = []
    for bid, (x, y, w, h, style, label) in BOXES.items():
        stroke, bg = STYLES[style]
        rect = base(bid, "rectangle", x, y, w, h, stroke, bg, dashed=(bid == "hooks"))
        rect["roundness"] = {"type": 3}
        rect["boundElements"] = [{"type": "text", "id": f"{bid}-t"}]
        lines = label.count("\n") + 1
        th = lines * 14 * 1.25
        elements.append(rect)
        elements.append(
            text_el(f"{bid}-t", x + 4, y + (h - th) / 2, w - 8, th, label, size=12, container=bid)
        )
    for i, (pts, both) in enumerate(ARROWS):
        x0, y0 = pts[0]
        rel = [[px - x0, py - y0] for px, py in pts]
        xs, ys = [p[0] for p in rel], [p[1] for p in rel]
        arr = base(f"a{i}", "arrow", x0, y0, max(xs) - min(xs), max(ys) - min(ys))
        arr.update(
            {
                "points": rel,
                "lastCommittedPoint": None,
                "startBinding": None,
                "endBinding": None,
                "startArrowhead": "arrow" if both else None,
                "endArrowhead": "arrow",
                "roundness": {"type": 2},
            }
        )
        elements.append(arr)
    for i, (x, y, t) in enumerate(LABELS + [REPLY_LABEL]):
        elements.append(
            text_el(f"lbl{i}", x, y, len(t) * 7, 18, t, size=13, color="#868e96", align="left")
        )
    return {
        "type": "excalidraw",
        "version": 2,
        "source": "claimsense/scripts/build_diagram.py",
        "elements": elements,
        "appState": {"viewBackgroundColor": "#ffffff", "gridSize": None},
        "files": {},
    }


def build_svg():
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 840" '
        'font-family="Arial, Helvetica, sans-serif">',
        '<rect width="1400" height="840" fill="#ffffff"/>',
        '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" '
        'fill="#495057"/></marker></defs>',
        '<rect x="250" y="715" width="945" height="110" rx="10" fill="#f8f9fa" stroke="#dee2e6"/>',
    ]
    for pts, both in ARROWS:
        d = " ".join(f"{'M' if i == 0 else 'L'}{x},{y}" for i, (x, y) in enumerate(pts))
        start = ' marker-start="url(#ah)"' if both else ""
        out.append(
            f'<path d="{d}" fill="none" stroke="#495057" stroke-width="1.6" '
            f'marker-end="url(#ah)"{start}/>'
        )
    for bid, (x, y, w, h, style, label) in BOXES.items():
        stroke, bg = STYLES[style]
        dash = ' stroke-dasharray="6 4"' if bid == "hooks" else ""
        out.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{bg}" '
            f'stroke="{stroke}" stroke-width="1.8"{dash}/>'
        )
        lines = label.split("\n")
        lh = 14
        y0 = y + h / 2 - (len(lines) - 1) * lh / 2 + 4
        for i, line in enumerate(lines):
            weight = "bold" if i == 0 else "normal"
            out.append(
                f'<text x="{x + w / 2}" y="{y0 + i * lh}" font-size="11" '
                f'font-weight="{weight}" text-anchor="middle" fill="#212529">'
                f"{escape(line)}</text>"
            )
    for x, y, t in LABELS + [REPLY_LABEL]:
        out.append(
            f'<text x="{x}" y="{y + 13}" font-size="12" fill="#868e96" '
            f'font-style="italic">{escape(t)}</text>'
        )
    out.append("</svg>")
    return "\n".join(out)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "claimsense-flow.excalidraw").write_text(
        json.dumps(build_excalidraw(), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    (OUT / "claimsense-flow.svg").write_text(build_svg(), encoding="utf-8")
    print("wrote", OUT)
