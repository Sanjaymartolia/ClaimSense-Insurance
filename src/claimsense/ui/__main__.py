"""`python -m claimsense.ui`: the case UI on http://127.0.0.1:8501 (ADR-0015).

Arguments pass through to `streamlit run` after the defaults, so they win:
`python -m claimsense.ui --server.port 8600`; in a container, `--server.address 0.0.0.0`.
"""

from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).with_name("app.py")
DEFAULTS = (
    "--server.address", "127.0.0.1",  # this machine only: a session holds reviewer tokens
    "--server.port", "8501",
    "--browser.gatherUsageStats", "false",  # no usage statistics leave the machine
    "--server.headless", "true",  # no first-run prompt; it prints the URL to open
)  # fmt: skip


def argv(extra: list[str]) -> list[str]:
    return ["streamlit", "run", str(APP), *DEFAULTS, *extra]


def main() -> None:
    from streamlit.web import cli

    sys.argv = argv(sys.argv[1:])
    sys.exit(cli.main())


if __name__ == "__main__":
    main()
