"""Call the real tools directly and compare what they do with `tool_cases.jsonl`.

The pipeline runs use stub tools, so this file is where the real claims database, approval checks,
tariff table and policy-kb wrappers are tested. Writes are judged by the final `settlements` table.
Calculator amounts come from hand-worked cases in `tests/test_adjudication_integration.py`; the
calculator is never its own oracle.
"""

# ruff: noqa: S106 - the approval "secrets" here are throwaway test values
from __future__ import annotations

import contextlib
import inspect
import os
import sqlite3
import tempfile
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from claimsense.agents import clauses as C
from claimsense.agents.services import real_calculate
from claimsense.contracts import ApprovalLevel, ApprovalToken, Claim, Worksheet, WorksheetLine
from claimsense.mcp_servers import approvals, claims_db, policy_kb, tariff
from claimsense.retrieval.index import StaleIndexError
from eval.harness.claimsense_adapter import ClaimSenseAdapter
from eval.harness.loader import load_split

from . import fixtures
from .cases import judge, load

CLAIM_ID = "CLM-TOOL-1"
Db = claims_db.ClaimsDatabase


@contextlib.contextmanager
def _env(**values: str | None) -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextlib.contextmanager
def _db() -> Iterator[Db]:
    """A throwaway database, installed as the module default. Nothing is written to disk."""
    db = Db(":memory:")
    previous = claims_db._DB  # noqa: SLF001
    claims_db.set_db(db)
    try:
        yield db
    finally:
        claims_db.set_db(previous)
        with contextlib.suppress(sqlite3.Error):
            db.close()


def _ws(total: str = "1000.00", version: int = 1, flags: list[str] | None = None) -> Worksheet:
    amount = Decimal(total)
    return Worksheet(
        claim_id=CLAIM_ID,
        version=version,
        lines=[WorksheetLine(line_id="L1", claimed=amount, payable=amount)],
        total_claimed=amount,
        total_payable=amount,
        fraud_flags=flags or [],
    )


def _who(level: ApprovalLevel = ApprovalLevel.ADJUDICATOR) -> approvals.AuthenticatedApprover:
    return approvals.DemoIdentityProvider().authenticate(CLAIM_ID, level)


def _bare(ws: Worksheet) -> ApprovalToken:
    return ApprovalToken(
        claim_id=ws.claim_id,
        worksheet_hash=ws.content_hash(),
        level=ApprovalLevel.ADJUDICATOR,
        approver_id="demo-adjudicator",
        decided_at=datetime.now(UTC),
    )


def _rows(db: Db) -> int:
    return db._conn.execute("SELECT COUNT(*) FROM settlements").fetchone()[0]  # noqa: SLF001


def _attempt(db: Db, fn: Callable[[], dict]) -> dict[str, Any]:
    try:
        result = fn()
    except PermissionError:
        return {"outcome": "refused", "rows": _rows(db)}
    return {
        "outcome": "ok",
        "rows": _rows(db),
        "amount": result.get("amount"),
        "status": result.get("status"),
    }


def _settle(db: Db, store: Any, ws: Worksheet, tokens: list, senior: bool = False) -> dict:
    return _attempt(db, lambda: db.settle_claim(CLAIM_ID, ws, tokens, senior, store=store))


def _fresh() -> tuple[Any, Worksheet, ApprovalToken]:
    store = approvals.InMemoryApprovalStore()
    ws = _ws()
    return store, ws, approvals.issue_approval(ws, _who(), store=store)


def _block_writes(db: Db) -> None:
    db._conn.execute(  # noqa: SLF001
        "CREATE TRIGGER block BEFORE INSERT ON settlements "
        "BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END"
    )


def _unblock_writes(db: Db) -> None:
    db._conn.execute("DROP TRIGGER block")  # noqa: SLF001


def _code(result: Any) -> dict[str, Any]:
    if hasattr(result, "code"):
        return {"code": result.code, "retryable": result.retryable, "outcome": "tool_error"}
    return {"outcome": "ok"}


# ------------------------------------------------------------------------- policies and history
def policy_found() -> dict:
    with _db() as db:
        db.upsert_policy(fixtures.policy())
        found = claims_db.get_policy("POL-AG")
        return {"policy_number": found.policy_number, "sum_insured": str(found.sum_insured)}


def policy_unknown_plain() -> dict:
    with _db():
        return {"result": claims_db.get_policy("NOPE")}


def policy_unknown_mcp() -> dict:
    with _db():
        return _code(claims_db._tool_get_policy("NOPE"))  # noqa: SLF001


def policy_db_error_mcp() -> dict:
    with _db() as db:
        db.close()
        return _code(claims_db._tool_get_policy("POL-AG"))  # noqa: SLF001


def history_empty() -> dict:
    with _db():
        return {"n_claims": len(claims_db.claim_history("POL-AG"))}


def _history_facts() -> dict:
    past = claims_db.claim_history("POL-AG")
    fingerprints = [fp for p in past for fp in p.bill_fingerprints]
    return {
        "n_claims": len(past),
        "n_fingerprints": len(fingerprints),
        "holds_description": any("Private room" in str(p.model_dump()) for p in past),
    }


def history_after_record() -> dict:
    with _db():
        claims_db.record_history(fixtures.claim(), None)
        return _history_facts()


def history_idempotent() -> dict:
    with _db():
        claims_db.record_history(fixtures.claim(), None)
        claims_db.record_history(fixtures.claim(), None)
        return _history_facts()


# ------------------------------------------------------------------------- tariff
@contextlib.contextmanager
def _tariff(csv_text: str | None = "default") -> Iterator[None]:
    body = (
        "procedure_code,procedure_name,city_tier,reference_low_inr,reference_high_inr\n"
        "P1,Synthetic Repair,tier_1,10000,20000\n"
    )
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "t.csv"
        if csv_text is not None:
            path.write_text(body, encoding="utf-8")
        tariff._table.cache_clear()  # noqa: SLF001
        with _env(CLAIMSENSE_TARIFF_CSV=str(path)):
            yield
        tariff._table.cache_clear()  # noqa: SLF001


def _range(procedure: str) -> dict:
    with _tariff():
        found = tariff.tariff_range(procedure, "tier_1")
    if found is None:
        return {"result": None}
    return {
        "low": str(found[0]),
        "high": str(found[1]),
        "is_decimal": all(isinstance(x, Decimal) for x in found),
    }


def tariff_found() -> dict:
    return _range("Synthetic Repair")


def tariff_normalised() -> dict:
    return _range("  synthetic   REPAIR ")


def tariff_near_miss() -> dict:
    return _range("Synthetic Repairs")


def tariff_mcp_found() -> dict:
    with _tariff():
        rec = tariff._tool_tariff_lookup("P1", "tier_1")  # noqa: SLF001
    return {"procedure_code": rec.procedure_code, "maximum": str(rec.maximum_expected_cost)}


def _tariff_code(procedure: str, tier: str, csv_text: str | None = "default") -> dict:
    with _tariff(csv_text):
        return _code(tariff._tool_tariff_lookup(procedure, tier))  # noqa: SLF001


def tariff_mcp_empty() -> dict:
    return _tariff_code("  ", "tier_1")


def tariff_mcp_unknown_tier() -> dict:
    return _tariff_code("P1", "tier_9")


def tariff_mcp_no_match() -> dict:
    return _tariff_code("Unknown", "tier_1")


def tariff_mcp_unavailable() -> dict:
    return _tariff_code("P1", "tier_1", csv_text=None)


# ------------------------------------------------------------------------- policy-kb wrappers
class _Retriever:
    def __init__(self, error: Exception | None = None, empty: bool = False):
        self.error = error
        self.empty = empty

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error

    def search(self, _query: str, k: int = 5, category: str | None = None) -> list:
        self._raise()
        if self.empty:
            return []
        hit = SimpleNamespace(
            clause_id="kb:1.1",
            clause_number="1.1",
            title="t",
            context_text="heading and clause",
            text="clause",
            document="policy.pdf",
            page_numbers=[1],
            score=0.9,
            rank=1,
        )
        return [hit][:k]

    def get_clause(self, clause_id: str) -> Any:
        self._raise()
        if self.empty:
            return None
        return SimpleNamespace(
            clause_id=clause_id,
            clause_number="1.1",
            title="t",
            context_text="Heading. full clause",  # get_clause now returns headings + text
            text="full clause",
            document="policy.pdf",
            page_numbers=[1],
            conflict=None,
        )


@contextlib.contextmanager
def _kb(retriever: _Retriever) -> Iterator[None]:
    meta = policy_kb._PolicyMeta(insurer="Synthetic", product="Synthetic")  # noqa: SLF001
    saved = policy_kb._ENGINE, policy_kb._ENGINE_ERROR  # noqa: SLF001
    policy_kb._ENGINE = policy_kb._Engine(retriever=retriever, meta=meta)  # noqa: SLF001
    policy_kb._ENGINE_ERROR = None  # noqa: SLF001
    policy_kb._cached_hits.cache_clear()  # noqa: SLF001  search results are cached per process
    try:
        yield
    finally:
        policy_kb._ENGINE, policy_kb._ENGINE_ERROR = saved  # noqa: SLF001
        policy_kb._cached_hits.cache_clear()  # noqa: SLF001


def _search(query: str, **retriever: Any) -> Any:
    with _kb(_Retriever(**retriever)):
        return policy_kb._tool_policy_search(query)  # noqa: SLF001


def _clause(clause_id: str, **retriever: Any) -> Any:
    with _kb(_Retriever(**retriever)):
        return policy_kb._tool_get_clause(clause_id)  # noqa: SLF001


def search_found() -> dict:
    found = _search("room rent")
    return {"clause_ids": [p.clause.clause_id for p in found], "rank": found[0].rank}


def search_empty() -> dict:
    return _code(_search("  "))


def search_no_match() -> dict:
    return _code(_search("room", empty=True))


def search_stale() -> dict:
    return _code(_search("room", error=StaleIndexError("stale")))


def search_unavailable() -> dict:
    return _code(_search("room", error=FileNotFoundError("gone")))


def search_crash() -> dict:
    return _code(_search("room", error=KeyError("boom")))


def clause_found() -> dict:
    found = _clause("kb:1.1")
    return {"clause_id": found.clause_id, "text": found.text}


def clause_empty() -> dict:
    return _code(_clause(" "))


def clause_unknown() -> dict:
    return _code(_clause("kb:9", empty=True))


def clause_stale() -> dict:
    return _code(_clause("kb:1.1", error=StaleIndexError("stale")))


def clause_unavailable() -> dict:
    return _code(_clause("kb:1.1", error=ImportError("no chroma")))


def clause_crash() -> dict:
    return _code(_clause("kb:1.1", error=KeyError("boom")))


# ------------------------------------------------------------------------- settlement
def settle_valid() -> dict:
    with _db() as db:
        store, ws, token = _fresh()
        return _settle(db, store, ws, [token])


def settle_signature() -> dict:
    params = {
        *inspect.signature(claims_db.settle_claim).parameters,
        *inspect.signature(claims_db._tool_settle_claim).parameters,  # noqa: SLF001
    }
    return {"has_amount": any("amount" in p for p in params)}


def settle_none() -> dict:
    with _db() as db:
        store, ws, _ = _fresh()
        return _settle(db, store, ws, [])


def settle_wrong_claim() -> dict:
    with _db() as db:
        store, ws, token = _fresh()
        return _attempt(db, lambda: db.settle_claim("OTHER", ws, [token], False, store=store))


def settle_stale() -> dict:
    with _db() as db:
        store, _, token = _fresh()
        return _settle(db, store, _ws(version=2), [token])


def settle_tampered() -> dict:
    with _db() as db:
        store, _, token = _fresh()
        return _settle(db, store, _ws(total="5000.00"), [token])


def settle_unsigned() -> dict:
    with _db() as db:
        ws = _ws()
        return _settle(db, approvals.InMemoryApprovalStore(), ws, [_bare(ws)])


def settle_wrong_secret() -> dict:
    with _db() as db, _env(CLAIMSENSE_APPROVAL_SECRET="first-test-value"):
        store, ws, token = _fresh()
        with _env(CLAIMSENSE_APPROVAL_SECRET="second-test-value"):
            return _settle(db, store, ws, [token])


def settle_expired() -> dict:
    with _db() as db:
        store = approvals.InMemoryApprovalStore()
        ws = _ws()
        old = approvals.AuthenticatedApprover(
            approver_id="demo-adjudicator",
            level=ApprovalLevel.ADJUDICATOR,
            auth_source="demo",
            authenticated_at=datetime.now(UTC) - timedelta(hours=25),
        )
        return _settle(db, store, ws, [approvals.issue_approval(ws, old, store=store)])


def settle_replay() -> dict:
    with _db() as db:
        store, ws, token = _fresh()
        _settle(db, store, ws, [token])
        return _settle(db, store, ws, [token])


def settle_consumed() -> dict:
    """The approval itself is spent, even before the already-settled check could help."""
    store, ws, token = _fresh()
    approvals.assert_can_settle(ws, [token], False, store=store)
    try:
        approvals.assert_can_settle(ws, [token], False, store=store)
    except PermissionError:
        return {"outcome": "refused"}
    return {"outcome": "ok"}


def settle_missing_senior() -> dict:
    with _db() as db:
        store, ws, token = _fresh()
        return _settle(db, store, ws, [token], senior=True)


def settle_with_senior() -> dict:
    with _db() as db:
        store, ws, token = _fresh()
        senior = approvals.issue_approval(ws, _who(ApprovalLevel.SENIOR), store=store)
        return _settle(db, store, ws, [token, senior], senior=True)


def settle_sqlite_store() -> dict:
    with _db() as db, _env(CLAIMSENSE_APPROVAL_SECRET="eval-only-value"):
        ws = _ws()
        token = approvals.issue_approval(ws, _who(), store=db.approval_store)
        return _attempt(db, lambda: claims_db.settle_claim(CLAIM_ID, ws, [token], False))


def settle_senior_bypass() -> dict:
    """The worksheet carries a fraud flag; the caller claims no senior is needed."""
    with _db() as db:
        store = approvals.InMemoryApprovalStore()
        ws = _ws(flags=["duplicate bill"])
        token = approvals.issue_approval(ws, _who(), store=store)
        return _settle(db, store, ws, [token], senior=False)


def settle_double() -> dict:
    with _db() as db:
        store, ws, token = _fresh()
        _settle(db, store, ws, [token])
        second = _ws(version=2)
        return _settle(db, store, second, [approvals.issue_approval(second, _who(), store=store)])


def settle_burned() -> dict:
    """A database failure after verification must leave the approval usable."""
    with _db() as db:
        store, ws, token = _fresh()
        _block_writes(db)
        with contextlib.suppress(sqlite3.Error):
            db.settle_claim(CLAIM_ID, ws, [token], False, store=store)
        _unblock_writes(db)
        return _settle(db, store, ws, [token])


def _mcp_settle(ws: Worksheet, tokens: list[ApprovalToken]) -> Any:
    return claims_db._tool_settle_claim(  # noqa: SLF001
        CLAIM_ID,
        ws.model_dump(mode="json"),
        [t.model_dump(mode="json") for t in tokens],
        False,
    )


def settle_mcp_ok() -> dict:
    """Hashes must survive the JSON trip an MCP call makes."""
    with _db() as db, _env(CLAIMSENSE_APPROVAL_SECRET="eval-only-value"):
        ws = _ws()
        result = _mcp_settle(ws, [approvals.issue_approval(ws, _who(), store=db.approval_store)])
        return {"status": getattr(result, "code", None) or result["status"]}


def settle_mcp_denied() -> dict:
    with _db(), _env(CLAIMSENSE_APPROVAL_SECRET="eval-only-value"):
        return _code(_mcp_settle(_ws(), []))


def settle_mcp_invalid() -> dict:
    with _db(), _env(CLAIMSENSE_APPROVAL_SECRET="eval-only-value"):
        return _code(claims_db._tool_settle_claim(CLAIM_ID, {"bad": 1}, [], False))  # noqa: SLF001


def settle_mcp_no_secret() -> dict:
    with _db(), _env(CLAIMSENSE_APPROVAL_SECRET=None):
        return _code(_mcp_settle(_ws(), []))


def settle_mcp_db_error() -> dict:
    with _db() as db, _env(CLAIMSENSE_APPROVAL_SECRET="eval-only-value"):
        ws = _ws()
        token = approvals.issue_approval(ws, _who(), store=db.approval_store)
        _block_writes(db)
        return _code(_mcp_settle(ws, [token]))


# ------------------------------------------------------------------------- repudiation
def _repudiation_token(store: Any, claim_id: str = CLAIM_ID) -> ApprovalToken:
    return approvals.issue_repudiation_approval(claim_id, "subject-hash", _who(), store=store)


def _repudiate(db: Db, store: Any, tokens: list, claim_id: str = CLAIM_ID) -> dict:
    return _attempt(db, lambda: db.record_repudiation(claim_id, ["reason"], tokens, store=store))


def repudiate_valid() -> dict:
    with _db() as db:
        store = approvals.InMemoryApprovalStore()
        return _repudiate(db, store, [_repudiation_token(store)])


def repudiate_none() -> dict:
    with _db() as db:
        return _repudiate(db, approvals.InMemoryApprovalStore(), [])


def repudiate_unsigned() -> dict:
    with _db() as db:
        return _repudiate(db, approvals.InMemoryApprovalStore(), [_bare(_ws())])


def repudiate_wrong_claim() -> dict:
    with _db() as db:
        store = approvals.InMemoryApprovalStore()
        return _repudiate(db, store, [_repudiation_token(store)], claim_id="OTHER")


def repudiate_replay() -> dict:
    with _db() as db:
        store = approvals.InMemoryApprovalStore()
        token = _repudiation_token(store)
        _repudiate(db, store, [token])
        return _repudiate(db, store, [token])


def repudiate_mcp_denied() -> dict:
    with _db(), _env(CLAIMSENSE_APPROVAL_SECRET="eval-only-value"):
        return _code(claims_db._tool_record_repudiation(CLAIM_ID, ["r"], []))  # noqa: SLF001


def repudiate_with_settlement_token() -> dict:
    with _db() as db:
        store, _, token = _fresh()
        return _repudiate(db, store, [token])


def repudiate_after_settle() -> dict:
    with _db() as db:
        store, ws, token = _fresh()
        _settle(db, store, ws, [token])
        return _repudiate(db, store, [_repudiation_token(store)])


# ------------------------------------------------------------------------- calculator
def calc_room_breach() -> dict:
    ws = real_calculate(fixtures.claim(), {"L5": C.NON_PAYABLE_ITEMS})
    return {
        "total_payable": str(ws.total_payable),
        "co_pay": str(ws.co_pay.amount),
        **{line.line_id: str(line.payable) for line in ws.lines},
    }


def _single_claim(**over: Any) -> Claim:
    data = fixtures.claim_dict()
    data.update(over)
    return Claim.model_validate(data)


def calc_no_breach() -> dict:
    claim = _single_claim(
        discharge_date="2026-05-12",
        sum_insured="500000.00",
        bill_lines=[
            {
                "line_id": "L1",
                "description": "Room",
                "category": "room",
                "amount": "6000.00",
                "days": 2,
                "source": fixtures.span(),
            },
            {
                "line_id": "L2",
                "description": "Doctor",
                "category": "doctor_fees",
                "amount": "4000.00",
                "source": fixtures.span(),
            },
        ],
        bill_total="10000.00",
    )
    ws = real_calculate(claim, {})
    return {
        "total_payable": str(ws.total_payable),
        "co_pay": str(ws.co_pay.amount),
        "n_line_deductions": sum(len(line.deductions) for line in ws.lines),
    }


def calc_missing_days() -> dict:
    claim = _single_claim(
        bill_lines=[
            {
                "line_id": "L1",
                "description": "Room",
                "category": "room",
                "amount": "21000.00",
                "source": fixtures.span(),
            }
        ],
        bill_total="21000.00",
    )
    line = real_calculate(claim, {}).lines[0]
    return {"L1": str(line.payable), "reason": line.deductions[0].reason.value}


def calc_zero_si() -> dict:
    claim = fixtures.claim().model_copy(update={"sum_insured": Decimal("0")})
    try:
        real_calculate(claim, {})
    except ValueError:
        return {"outcome": "ValueError"}
    return {"outcome": "returned a worksheet"}


def calc_invariants() -> dict:
    adapter = ClaimSenseAdapter(calculator="real")
    counts = {"n_not_decimal": 0, "n_not_reconciled": 0, "n_unclaused": 0, "n_not_repeatable": 0}
    cases = load_split("dev")
    for case in cases:
        claim = Claim.model_validate(adapter._packet(case.claim)["claim"])  # noqa: SLF001
        ws = real_calculate(claim, {})
        again = real_calculate(claim, {})
        amounts = [ws.total_payable, ws.total_claimed, *[line.payable for line in ws.lines]]
        counts["n_not_decimal"] += not all(isinstance(a, Decimal) for a in amounts)
        gross = sum((line.payable for line in ws.lines), Decimal(0))
        copay = ws.co_pay.amount if ws.co_pay else Decimal(0)
        counts["n_not_reconciled"] += gross - copay != ws.total_payable
        counts["n_unclaused"] += any(not d.clause_id for ln in ws.lines for d in ln.deductions)
        counts["n_not_repeatable"] += ws.content_hash() != again.content_hash()
    return {"n_claims": len(cases), **counts}


def run_case(case: dict) -> dict:
    try:
        observed = globals()[case["scenario"]]()
    except Exception as exc:  # noqa: BLE001 - a crash is an outcome: "raised to the agent"
        observed = {"outcome": f"crash:{type(exc).__name__}"}
    return {**judge("tool", case, observed), "tool": case["tool"]}


def run_all() -> list[dict]:
    return [run_case(case) for case in load("tool_cases.jsonl")]
