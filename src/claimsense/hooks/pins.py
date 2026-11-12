"""Tool pinning (L15 notebook section 8, the poisoned tool update / rug pull).

What a model sees of a tool is its name, its description and its arguments. A changed description
can carry an instruction no person reads (MCPTox: 36.5% of agents followed one). So the reviewed
definition of every tool is fingerprinted into `config/tool_pins.json`, and a tool whose
definition has changed since review does not load (`real_services()` calls `check_pins`).

After a deliberate, reviewed change to a tool, record the new pins:

    python -m claimsense.hooks.pins --update

Plain Python only (inspect, hashlib, json), so CI can run the check with `.[dev]`.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


def pins_file() -> Path:
    """Where the reviewed pins are: $CLAIMSENSE_TOOL_PINS, else config/tool_pins.json in the
    working directory (a container runs from its app folder), else in this source checkout. A
    non-editable install puts this module in site-packages, where the checkout path is wrong."""
    override = os.environ.get("CLAIMSENSE_TOOL_PINS")
    if override:
        return Path(override)
    cwd = Path.cwd() / "config" / "tool_pins.json"
    return (
        cwd if cwd.exists() else Path(__file__).resolve().parents[3] / "config" / "tool_pins.json"
    )


class ToolPinError(PermissionError):
    """A tool's definition changed since it was reviewed, or it was never reviewed."""


def definition(name: str, fn: Callable[..., Any]) -> dict:
    """What a model is shown of a tool: name, docstring, and each argument with its type."""
    params = [
        {
            "name": p.name,
            "type": str(p.annotation) if p.annotation is not inspect.Parameter.empty else "",
            "required": p.default is inspect.Parameter.empty,
        }
        for p in inspect.signature(fn).parameters.values()
        if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
    ]
    return {"name": name, "doc": inspect.getdoc(fn) or "", "params": params}


def fingerprint(name: str, fn: Callable[..., Any]) -> str:
    text = json.dumps(definition(name, fn), sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_pins(path: Path | None = None) -> dict[str, str]:
    """The reviewed pins. A missing file is an error, never "no pins": that would read as every
    tool having changed, and invite an unreviewed `--update`."""
    path = path or pins_file()
    if not path.exists():
        raise ToolPinError(
            f"tool pins file not found: {path}. Set CLAIMSENSE_TOOL_PINS to the reviewed "
            "config/tool_pins.json; do not run --update to make one."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def check_pins(registry: dict[str, Callable[..., Any]], pins: dict[str, str] | None = None) -> None:
    """Raise ToolPinError if any tool is unpinned or differs from its reviewed fingerprint."""
    pins = load_pins() if pins is None else pins
    changed = [n for n, fn in sorted(registry.items()) if pins.get(n) != fingerprint(n, fn)]
    if changed:
        raise ToolPinError(
            f"tool definitions changed or never reviewed: {', '.join(changed)}. Review the change, "
            "then run `python -m claimsense.hooks.pins --update`."
        )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m claimsense.hooks.pins", description=__doc__)
    p.add_argument("--update", action="store_true", help="record the current definitions")
    args = p.parse_args(argv)
    from claimsense.agents.services import real_services

    registry = real_services(check=False).registry()
    if args.update:
        pins = {n: fingerprint(n, fn) for n, fn in sorted(registry.items())}
        target = pins_file()
        target.write_text(json.dumps(pins, indent=1) + "\n", encoding="utf-8")
        print(f"pinned {len(pins)} tools in {target}")
        return 0
    try:
        check_pins(registry)
    except ToolPinError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"all {len(registry)} tools match their pins")
    return 0


if __name__ == "__main__":
    sys.exit(main())
