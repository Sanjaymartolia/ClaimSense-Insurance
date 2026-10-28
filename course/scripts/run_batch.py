"""Run many claims and write traces, with no gold anywhere near (Eval & Red-Team only).

    # from exercises/<you>/ ; the held-out folder sits next to the repo
    python scripts/run_batch.py --in ../../../claimsense-heldout/claims.jsonl --out heldout.jsonl
    python scripts/score_traces.py --traces heldout.jsonl \
        --gold ../../../claimsense-heldout/gold_worksheets.jsonl

Freeze code, model, prompts and index before a held-out run (eval/README.md).
"""

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claimsense_hw import trace  # noqa: E402
from claimsense_hw.agent import ClaimAgent  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--in", dest="src", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--workers", type=int, default=4)
a = ap.parse_args()
agent = ClaimAgent()
with ThreadPoolExecutor(max_workers=a.workers) as pool:
    rows = list(pool.map(agent.resolve, trace.read_jsonl(a.src)))
trace.write_jsonl(a.out, rows)
print(f"wrote {len(rows)} traces -> {a.out}")
