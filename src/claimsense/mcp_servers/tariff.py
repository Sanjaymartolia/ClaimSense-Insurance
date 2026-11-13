"""tariff MCP server (READ-ONLY). ClaimSense Role 4 (Tools, Control & Security).

Final module for ``claimsense.mcp_servers.tariff``. It loads the synthetic tariff table shipped in
the repo (``data/tariffs/synthetic_tariffs.csv`` - 30 procedures x 3 city tiers = 90 rows) and lets
the fraud analyst look up an expected cost range for a procedure in a city tier.

Role 3 integration
------------------
Role 3 reaches this through ``claimsense.agents.services.Services.tariff_range`` (registry name
``tariff_range``; permitted for the FRAUD agent only - see ``agents/permissions.TOOL_ACL``). The
fraud agent calls it as ``rng = tariff_range(procedure=..., city_tier=...)`` and then reads
``rng[0]`` / ``rng[1]``, so the plain callable returns a ``(low, high)`` tuple of
:class:`~decimal.Decimal` (or ``None`` when unknown). Import it directly - no MCP client and no
FastMCP instance are required::

    from claimsense.mcp_servers.tariff import tariff_range

The MCP tool wrapper (:func:`_tool_tariff_lookup`, exposed as the ``tariff_lookup`` tool) is a thin
layer over the SAME lookup table; it returns a structured record or a :class:`ToolError`.
``fastmcp`` is imported lazily in :func:`main`, so importing this module never constructs a server
and pulls in no heavy dependencies.

Data caveat
-----------
The ranges are SYNTHETIC - per the dataset's own notes, "not an official tariff, negotiated rate, or
coverage limit". They may only be used to flag unusual prices for human review; they are never
policy limits, guaranteed payable amounts, or an input to any deduction/settlement decision. Tariff
lookup is kept strictly separate from claim adjudication.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

SYNTHETIC_DATA_DISCLAIMER = (
    "Synthetic reference range for anomaly screening only; not an official insurer tariff, "
    "policy limit, negotiated rate, or guaranteed payable amount."
)

_CSV_RELPATH = Path("data") / "tariffs" / "synthetic_tariffs.csv"

# Columns the loader depends on; the rest of the CSV header is carried through but optional.
_REQUIRED_COLUMNS = frozenset(
    {"procedure_name", "city_tier", "reference_low_inr", "reference_high_inr"}
)


# --------------------------------------------------------------------------------------------
# Path resolution - machine-independent: env overrides first, otherwise derived from this file's
# location. Works whether the module lives at ``src/claimsense/mcp_servers/tariff.py`` inside the
# repo or ships next to a sibling ``ClaimSense-Insurance`` checkout. No absolute paths are baked in.
# --------------------------------------------------------------------------------------------
def _candidate_csv_paths() -> list[Path]:
    env_csv = os.environ.get("CLAIMSENSE_TARIFF_CSV")
    if env_csv:
        return [Path(env_csv)]

    candidates: list[Path] = []
    env_repo = os.environ.get("CLAIMSENSE_REPO")
    if env_repo:
        candidates.append(Path(env_repo) / _CSV_RELPATH)

    here = Path(__file__).resolve()
    for ancestor in here.parents:
        candidates.append(ancestor / _CSV_RELPATH)  # in-repo: data/ above us
        candidates.append(ancestor / "ClaimSense-Insurance" / _CSV_RELPATH)  # sibling checkout
    return candidates


def _resolve_tariff_csv() -> Path:
    """Return the first existing tariff CSV path, or raise a clear, actionable error."""
    for cand in _candidate_csv_paths():
        if cand.is_file():
            return cand
    raise FileNotFoundError(
        f"tariff CSV not found: looked for {_CSV_RELPATH.as_posix()} near "
        f"{Path(__file__).resolve().parent} and in a sibling ClaimSense-Insurance checkout. "
        "Set CLAIMSENSE_TARIFF_CSV (full path to the CSV) or CLAIMSENSE_REPO (repo root) "
        "to override."
    )


# --------------------------------------------------------------------------------------------
# Contracts - defined locally so importing the plain callable stays
# dependency-light (pydantic only).
# --------------------------------------------------------------------------------------------
class ToolError(BaseModel):
    """Structured error returned at the MCP boundary instead of raising to an agent."""

    error: str
    code: str = "tariff_error"
    retryable: bool = False


class TariffRecord(BaseModel):
    """One expected-cost range for a procedure in a city tier. Monetary values are Decimal."""

    procedure_code: str
    procedure_name: str
    city_tier: str
    city_tier_label: str
    minimum_expected_cost: Decimal
    maximum_expected_cost: Decimal
    currency: str
    source_type: str
    dataset_version: str
    disclaimer: str = SYNTHETIC_DATA_DISCLAIMER


def _norm_name(text: str) -> str:
    """Deterministic procedure key: strip, collapse internal whitespace, casefold.

    This is case-insensitive matching with whitespace tolerance only - NOT fuzzy matching. It never
    reorders tokens, drops punctuation, or guesses a near neighbour, so it cannot return the wrong
    procedure; an unknown name simply fails to match and yields ``None``.
    """
    return " ".join((text or "").split()).casefold()


def _norm_tier(text: str) -> str:
    return (text or "").strip().casefold()


# --------------------------------------------------------------------------------------------
# Tariff table: load once, validate every row, index by (name, tier) and (code, tier).
# --------------------------------------------------------------------------------------------
@dataclass
class TariffTable:
    _by_name: dict[tuple[str, str], TariffRecord] = field(default_factory=dict)
    _by_code: dict[tuple[str, str], TariffRecord] = field(default_factory=dict)
    tiers: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_csv(cls, path: Path | str | None = None) -> TariffTable:
        csv_path = Path(path) if path is not None else _resolve_tariff_csv()
        if not csv_path.is_file():
            raise FileNotFoundError(f"tariff CSV not found at {csv_path}.")
        table = cls()
        with csv_path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            missing = _REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise ValueError(
                    f"tariff CSV {csv_path} is missing required column(s): {sorted(missing)}"
                )
            for lineno, row in enumerate(reader, start=2):  # start=2: header is line 1
                table._ingest_row(row, lineno)
        if not table._by_name:
            raise ValueError(f"tariff CSV {csv_path} contained no usable rows")
        return table

    def _ingest_row(self, row: dict, lineno: int) -> None:
        name = (row.get("procedure_name") or "").strip()
        code = (row.get("procedure_code") or "").strip()
        tier = (row.get("city_tier") or "").strip()
        if not name or not tier:
            self.warnings.append(f"row {lineno}: missing procedure_name or city_tier; skipped")
            return
        try:
            low = Decimal((row.get("reference_low_inr") or "").strip())
            high = Decimal((row.get("reference_high_inr") or "").strip())
        except (InvalidOperation, AttributeError):
            self.warnings.append(f"row {lineno}: non-numeric cost for {name!r}/{tier}; skipped")
            return
        if low < 0 or high < 0:
            self.warnings.append(
                f"row {lineno}: negative cost {low}/{high} for {name!r}/{tier}; skipped"
            )
            return
        if low > high:
            self.warnings.append(
                f"row {lineno}: min {low} > max {high} for {name!r}/{tier}; skipped"
            )
            return

        record = TariffRecord(
            procedure_code=code,
            procedure_name=name,
            city_tier=tier,
            city_tier_label=(row.get("city_tier_label") or "").strip(),
            minimum_expected_cost=low,
            maximum_expected_cost=high,
            currency=(row.get("currency") or "INR").strip() or "INR",
            source_type=(row.get("source_type") or "").strip(),
            dataset_version=(row.get("dataset_version") or "").strip(),
        )
        self.tiers.add(_norm_tier(tier))

        # Duplicate handling is explicit and deterministic: the first occurrence wins and every
        # repeat is recorded. A repeat with the SAME range is harmless; a repeat with a DIFFERENT
        # range is a data-quality conflict and is flagged as such rather than silently resolved.
        name_key = (_norm_name(name), _norm_tier(tier))
        existing = self._by_name.get(name_key)
        if existing is not None:
            if (existing.minimum_expected_cost, existing.maximum_expected_cost) == (low, high):
                self.warnings.append(
                    f"row {lineno}: duplicate (identical) tariff for {name!r}/{tier}; kept first"
                )
            else:
                self.warnings.append(
                    f"row {lineno}: CONFLICTING duplicate tariff for {name!r}/{tier} "
                    f"({existing.minimum_expected_cost}-{existing.maximum_expected_cost} vs "
                    f"{low}-{high}); kept first occurrence"
                )
        else:
            self._by_name[name_key] = record
        if code:
            self._by_code.setdefault((_norm_name(code), _norm_tier(tier)), record)

    def lookup(self, procedure: str, city_tier: str) -> TariffRecord | None:
        """Exact match by procedure name, then by procedure code, within the city
        tier. No guessing."""
        key = (_norm_name(procedure), _norm_tier(city_tier))
        hit = self._by_name.get(key)
        if hit is not None:
            return hit
        return self._by_code.get(key)

    def range(self, procedure: str, city_tier: str) -> tuple[Decimal, Decimal] | None:
        rec = self.lookup(procedure, city_tier)
        return (rec.minimum_expected_cost, rec.maximum_expected_cost) if rec else None


@lru_cache(maxsize=1)
def _table() -> TariffTable:
    """Load and index the tariff CSV once per process (cached across calls)."""
    return TariffTable.from_csv()


def load_tariffs(path: Path | str | None = None) -> TariffTable:
    """Public loader used by tests and tooling; bypasses the process cache."""
    return TariffTable.from_csv(path)


# --------------------------------------------------------------------------------------------
# Services-facing plain callable (registry name ``tariff_range``) - what the fraud agent imports.
# Signature is fixed by Role 3: (procedure, city_tier) -> (low, high) | None.
# --------------------------------------------------------------------------------------------
def tariff_range(procedure: str, city_tier: str) -> tuple[Decimal, Decimal] | None:
    """[read] Expected ``(low, high)`` cost for ``procedure`` in ``city_tier``.

    Returns a ``(Decimal, Decimal)`` tuple, or ``None`` when the procedure/tier is unknown (an empty
    procedure also yields ``None``). Matching is case-insensitive with whitespace tolerance and never
    fuzzy-guesses an alternative procedure. A missing or unreadable tariff CSV raises (it is a
    configuration error, deliberately NOT reported as ``None``/"no match"). This callable never
    returns a ``ToolError`` - that is reserved for the MCP boundary.
    """  # noqa: E501 - pinned tool docstring (config/tool_pins.json): change only with a pin review
    if not procedure or not procedure.strip():
        return None
    return _table().range(procedure, city_tier)


# --------------------------------------------------------------------------------------------
# MCP tool wrapper: structured record / ToolError. Same table; lookup logic is not duplicated.
# --------------------------------------------------------------------------------------------
def _tool_tariff_lookup(procedure: str, city_tier: str) -> TariffRecord | ToolError:
    """[read] Look up the expected cost range for a procedure in a city tier.

    Returns a :class:`TariffRecord` (a SYNTHETIC reference range, for anomaly review only) or a
    :class:`ToolError`. The result is never a coverage limit or a payable amount.
    """
    if not procedure or not procedure.strip():
        return ToolError(error="procedure is required", code="empty_procedure")
    try:
        table = _table()
    except (FileNotFoundError, ValueError) as exc:
        return ToolError(error=str(exc), code="tariff_unavailable", retryable=True)
    tier = _norm_tier(city_tier)
    if table.tiers and tier not in table.tiers:
        return ToolError(
            error=f"unknown city_tier {city_tier!r}; known tiers: {sorted(table.tiers)}",
            code="unknown_tier",
        )
    record = table.lookup(procedure, city_tier)
    if record is None:
        return ToolError(
            error=f"no tariff for procedure {procedure!r} in {city_tier!r}", code="no_match"
        )
    return record


def main() -> None:
    """Start the tariff MCP server over stdio. Requires the optional ``[mcp]`` extra (fastmcp).

    FastMCP is constructed here, never at import time, so ``import`` stays cheap and side-effect
    free. The Services-facing ``tariff_range`` is exposed to agents through Role 3's registry, not
    through this server, so the MCP tool keeps its own descriptive name (``tariff_lookup``).
    """
    server().run(show_banner=False)


def server():
    """The tariff MCP app, built without loading the table (tool listing, pins, tests)."""
    from fastmcp import FastMCP  # lazy: optional dependency (pip install -e ".[mcp]")

    mcp = FastMCP("tariff")
    mcp.tool(name="tariff_lookup")(_tool_tariff_lookup)
    return mcp


if __name__ == "__main__":
    main()
