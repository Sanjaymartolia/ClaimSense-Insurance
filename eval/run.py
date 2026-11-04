"""Shim so `python -m eval.run` works, which is what the CI gate already expects.

`.github/workflows/ci.yml` has a commented-out T48 job that calls
`python -m eval.run --split dev --min-score 0.80`. That module did not exist (EVAL-01). This file
is it. The harness itself lives in `eval.harness.run`; everything here is forwarding.
"""

from __future__ import annotations

import sys

from eval.harness.run import main

if __name__ == "__main__":
    sys.exit(main())
