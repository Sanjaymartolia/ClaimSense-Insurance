"""Set-up for the DeepEval suite. pytest loads this file before it imports any test module, so
before `deepeval` is imported (unless the `deepeval test run` CLI imported it already)."""

from __future__ import annotations

import os

import pytest

# `import deepeval` copies .env into the environment (a key there switches the stub tests to paid
# models). `-p no:deepeval` stops only the pytest plugin, not this. setdefault: a person can still
# choose DEEPEVAL_DISABLE_DOTENV=0. The `deepeval test run` CLI imports deepeval before pytest
# starts, so for that command export the variable first (see README.md).
os.environ.setdefault("DEEPEVAL_DISABLE_DOTENV", "1")

# DeepEval sends anonymous usage events to PostHog unless told not to. Nothing about a claim is in
# them, but no part of this project reports to a third party it does not need. This covers the
# events raised during the pytest session; the CLI's own "CLI Command" event fires before pytest
# starts, so `deepeval test run` needs DEEPEVAL_TELEMETRY_OPT_OUT=1 exported first.
os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "1"


def _langsmith_problem() -> str | None:
    try:
        from eval.observability.otel import langsmith_problem
    except ImportError:  # no OpenTelemetry, so no deepeval either: the tests skip
        return None
    return langsmith_problem()


# LangSmith's own LangChain tracing would upload error text from the real-mode agents (rule 4).
# Checked here, at import, so it holds for `pytest eval` too (session hooks run only for the
# conftest files of the paths given on the command line).
if _problem := _langsmith_problem():
    pytest.exit(_problem, returncode=2)


def _mode_line() -> str:
    try:
        from eval.deepeval_suite.support import mode
    except ImportError:
        return 'DeepEval suite: skipped, needs pip install -e ".[agents,deepeval]"'
    if mode() == "stub":
        return "ClaimSense agents: stub (deterministic, no model calls, free)"
    return "ClaimSense agents: REAL MODELS via OpenRouter (costs money; CLAIMSENSE_LLM=stub: free)"


def pytest_sessionstart(session: pytest.Session) -> None:
    """Say stub or real, straight to the terminal: `-q` (addopts) and deepeval's `--quiet` hide
    the report header."""
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(_mode_line())
