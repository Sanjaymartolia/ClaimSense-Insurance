"""Cut the policy into chunks and embed them into .index/ (first run downloads the embedder).

python scripts/build_index.py --force                       # fixed 600-char pieces
python scripts/build_index.py --force --strategy clauses    # after TODO 1
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claimsense_hw import retrieval  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--force", action="store_true", help="rebuild even if an index exists")
ap.add_argument("--strategy", choices=["fixed", "clauses"], default=None)
a = ap.parse_args()
retrieval.build_index(a.strategy, a.force)
