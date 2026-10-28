"""The human in the loop: approve or reject a run paused before settle (TODO 6c).

python scripts/approve.py CLM-0004 --yes
python scripts/approve.py CLM-0004 --no
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claimsense_hw.agent import ClaimAgent  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("thread_id")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--yes", action="store_true")
    group.add_argument("--no", action="store_true")
    ap.add_argument("--approver", default="adjudicator-demo")
    a = ap.parse_args()
    out = ClaimAgent(persist=True).resume(a.thread_id, approved=a.yes, approver_id=a.approver)
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
