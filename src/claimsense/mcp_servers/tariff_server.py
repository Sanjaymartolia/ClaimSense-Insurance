"""tariff MCP server (READ-ONLY). ClaimSense Role 4 (Tools, Control & Security).

Loads the actual synthetic tariff table shipped in the repo
(``data/tariffs/synthetic_tariffs.csv`` - 30 procedures x 3 city tiers = 90 rows) and lets the
fraud analyst look up an expected cost range by procedure and city tier.

Role 3 reaches it through ``Services.tariff_range`` (registry name ``tariff_range``; used by the
fraud analyst - see ``agents/permissions.TOOL_ACL`` -> FRAUD). ``tariff_range`` returns a
``(low, high)`` tuple of :class:`~decimal.Decimal`, exactly as the fraud agent consumes it
(``rng[0]``, ``rng[1]``).

The ranges are **synthetic** ("not an official tariff, negotiated rate, or coverage limit" per the
dataset) and must only be used to flag unusual prices for human review, never to decide coverage.
Tariff lookup is kept strictly separate from claim deduction logic.

``fastmcp`` is imported lazily in :func:`main`, so the module imports and runs for tests without it.
"""

from __future__ import annotations

import csv
import os
import sys
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel


def _repo_root() -> Path:
    env = os.environ.get("CLAIMSENSE_REPO")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for cand in (here.parent.parent / "ClaimSense-Insurance", here.parent / "ClaimSense-Insurance"):
        if cand.is_dir():
            return cand
    return here.parent.parent / "ClaimSense-Insurance"


def _default_tariff_path() -> Path:
    env = os.environ.get("CLAIMSENSE_TARIFF_CSV")
    if env:
        return Path(env)
    return _repo_root() / "data" / "tariffs" / "synthetic_tariffs.csv"


class ToolError(BaseModel):
    """Structured error returned at the MCP boundary instead of raising to an agent."""

    error: str
    code: str = "tariff_error"
    retryable: bool = False


class TariffRecord(BaseModel):
    """One expected-cost range for a procedure in a city tier (actual units preserved)."""

    procedure_code: str
    procedure_name: str
    city_tier: str
    city_tier_label: str
    minimum_expected_cost: Decimal
    maximum_expected_cost: Decimal
    currency: str
    source_type: str
    dataset_version: str


def _norm(text: str) -> str:
    return (text or "").strip().casefold()


@dataclass
class TariffTable:
    """In-memory tariff index with data-quality validation (duplicates, missing values)."""

    _by_name: dict[tuple[str, str], TariffRecord] = field(default_factory=dict)
    _by_code: dict[tuple[str, str], TariffRecord] = field(default_factory=dict)
    tiers: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_csv(cls, path: Path | str | None = None) -> "TariffTable":
        csv_path = Path(path) if path else _default_tariff_path()
        if not csv_path.is_file():
            raise FileNotFoundError(
                f"tariff CSV not found at {csv_path}. Set CLAIMSENSE_TARIFF_CSV to override."
            )
        table = cls()
        with csv_path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for lineno, row in enumerate(reader, start=2):
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
        if low < 0 or high < 0 or high < low:
            self.warnings.append(f"row {lineno}: invalid range {low}-{high} for {name!r}/{tier}; skipped")
            return
        record = TariffRecord(
            procedure_code=code,
            procedure_name=name,
            city_tier=tier,
            city_tier_label=(row.get("city_tier_label") or "").strip(),
            minimum_expected_cost=low,
            maximum_expected_cost=high,
            currency=(row.get("currency") or "INR").strip(),
            source_type=(row.get("source_type") or "").strip(),
            dataset_version=(row.get("dataset_version") or "").strip(),
        )
        self.tiers.add(tier)
        name_key = (_norm(name), tier)
        if name_key in self._by_name:
            self.warnings.append(f"row {lineno}: duplicate tariff for {name!r}/{tier}; kept first")
        else:
            self._by_name[name_key] = record
        if code:
            self._by_code[(_norm(code), tier)] = record

    def lookup(self, procedure: str, city_tier: str) -> TariffRecord | None:
        """Exact match by procedure name, then procedure code. No fuzzy guessing, no fabrication."""
        tier = (city_tier or "").strip()
        name_key = (_norm(procedure), tier)
        if name_key in self._by_name:
            return self._by_name[name_key]
        code_key = (_norm(procedure), tier)
        return self._by_code.get(code_key)

    def range(self, procedure: str, city_tier: str = "tier_1") -> tuple[Decimal, Decimal] | None:
        rec = self.lookup(procedure, city_tier)
        return (rec.minimum_expected_cost, rec.maximum_expected_cost) if rec else None


@lru_cache(maxsize=1)
def _table() -> TariffTable:
    return TariffTable.from_csv()


def load_tariffs(path: Path | str | None = None) -> TariffTable:
    """Public loader (used by tests and by ``role4_services``)."""
    return TariffTable.from_csv(path)


# --------------------------------------------------------------------------------------------
# Services-facing callable (registry name ``tariff_range``) - matches the fraud agent's usage.
# --------------------------------------------------------------------------------------------
def tariff_range(procedure: str, city_tier: str = "tier_1") -> tuple[Decimal, Decimal] | None:
    """[read] Expected ``(low, high)`` cost for a procedure in a city tier, or ``None`` if unknown."""
    if not procedure or not procedure.strip():
        return None
    return _table().range(procedure, city_tier)


# --------------------------------------------------------------------------------------------
# MCP tool wrapper: structured result / error.
# --------------------------------------------------------------------------------------------
def _tool_tariff_lookup(procedure: str, city_tier: str):
    """[read] Look up the expected cost range for a procedure and city tier."""
    if not procedure or not procedure.strip():
        return ToolError(error="procedure is required", code="empty_procedure")
    try:
        table = _table()
    except (FileNotFoundError, ValueError) as exc:
        return ToolError(error=str(exc), code="tariff_unavailable", retryable=True)
    tier = (city_tier or "").strip()
    if table.tiers and tier not in table.tiers:
        return ToolError(
            error=f"unknown city_tier {tier!r}; known tiers: {sorted(table.tiers)}",
            code="unknown_tier",
        )
    record = table.lookup(procedure, tier)
    if record is None:
        return ToolError(
            error=f"no tariff for procedure {procedure!r} in {tier}", code="no_match"
        )
    return record


def main() -> None:
    """Start the tariff MCP server (stdio). Requires the optional ``[mcp]`` extra."""
    from fastmcp import FastMCP  # lazy: optional dependency

    mcp = FastMCP("tariff")
    mcp.tool(name="tariff_lookup")(_tool_tariff_lookup)
    mcp.run()


if __name__ == "__main__":
    main()
