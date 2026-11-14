"""The audit trail's sink (rubric D3): every tool call and every claim run, one JSON object a line.

`CLAIMSENSE_AUDIT_LOG=<path>` turns it on (the API attaches it at start-up). It writes the
structured `audit` data that two loggers carry, and nothing else:

- `claimsense.hooks.audit`: one record per tool call (`hooks/hooks.py` `AuditRecord`): run id,
  agent, tool, allowed, status, error class, claim id, duration;
- `claimsense.api.audit`: `run.start` and `run.end` for every run (a start or a decision): run id,
  case id, claim id, kind, decision, the approver id and level from the token, the worksheet hash,
  the outcome.

Ids, names, codes, hashes and times only: never a document, a diagnosis, a bill description, a
reviewer token or an approval signature (rule 4). `tests/api/test_audit.py` checks it.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOGGERS = ("claimsense.hooks.audit", "claimsense.api.audit")
log = logging.getLogger("claimsense.api.audit")


class JsonLinesHandler(logging.Handler):
    """Appends each record's `audit` data as one JSON line; ignores records without it."""

    def __init__(self, path: str | Path) -> None:
        super().__init__(level=logging.INFO)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, record: logging.LogRecord) -> None:
        data = getattr(record, "audit", None)
        if not isinstance(data, dict):
            return
        line = json.dumps(data, default=str, sort_keys=True)
        try:  # open per line: nothing stays open, and each line is written whole
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            self.handleError(record)


def attach(path: str) -> tuple[JsonLinesHandler, dict[str, int]] | None:
    """Send the audit loggers to `path`. Returns what `detach` needs; None when `path` is empty."""
    if not path:
        return None
    handler = JsonLinesHandler(path)
    levels = {}
    for name in LOGGERS:
        logger = logging.getLogger(name)
        levels[name] = logger.level
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
    return handler, levels


def detach(attached: tuple[JsonLinesHandler, dict[str, int]] | None) -> None:
    if attached is None:
        return
    handler, levels = attached
    for name in LOGGERS:
        logger = logging.getLogger(name)
        logger.removeHandler(handler)
        logger.setLevel(levels[name])
    handler.close()


def run_event(event: str, **fields: Any) -> None:
    """Log `run.start` or `run.end` with its fields (ids, codes and hashes only)."""
    data = {"event": event, "timestamp": datetime.now(UTC).isoformat(), **fields}
    log.info(
        "%s run=%s case=%s",
        event,
        fields.get("run_id"),
        fields.get("case_id"),
        extra={"audit": data},
    )
