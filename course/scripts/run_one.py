"""Run one claim and print the whole trace — your main debugging tool.

python scripts/run_one.py CLM-0004
python scripts/run_one.py CLM-0004 --pause                      # stop before settle (TODO 6c)
python scripts/run_one.py CLM-0004 --thread t1 --question "Why was nursing cut?"   # memory
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claimsense_hw import config, trace  # noqa: E402
from claimsense_hw.agent import ClaimAgent  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("claim_id")
    ap.add_argument("--question", default=None)
    ap.add_argument("--thread", default=None, help="reuse a thread id to continue a conversation")
    ap.add_argument("--pause", action="store_true", help="interrupt before the settle step")
    a = ap.parse_args()

    claims = {c["claim_id"]: c for c in trace.read_jsonl(config.DEV_CLAIMS)}
    agent = ClaimAgent(
        persist=bool(a.pause or a.thread), interrupt_before=["settle"] if a.pause else None
    )
    out = agent.resolve(claims[a.claim_id], a.question, a.thread)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    if out["meta"].get("paused_before"):
        thread = a.thread or a.claim_id
        print(
            f"\nPAUSED before {out['meta']['paused_before']}. Decide with:\n"
            f"  python scripts/approve.py {thread} --yes     (or --no)"
        )


if __name__ == "__main__":
    main()
