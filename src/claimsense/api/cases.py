"""Case routes (L16): start a claim, read it, answer its review. Runs stream as server-sent events.

Every route here needs a reviewer token (`auth.py`). Who decides, and at which level, comes from
the token. Before the graph resumes, the API checks that the reviewer holds the level the pending
review asks for, and the four-eyes rule: the senior review is done by someone other than the
adjudicator who approved. The review gate then signs the approval with that same identity.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any

import anyio
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from claimsense.contracts import ApprovalLevel

from . import demo, metrics
from .auth import Reviewer, find_reviewer
from .runner import CaseService, Event, error_event
from .schemas import CASE_ID, ClaimPacketIn, DecisionIn

log = logging.getLogger("claimsense.api")
router = APIRouter()
_bearer = HTTPBearer(auto_error=False)
_END = object()

CaseId = Annotated[str, Path(pattern=CASE_ID)]
NewCaseId = Annotated[
    str | None,
    Query(pattern=CASE_ID, description="Case id for this run; defaults to the claim id"),
]


def _json(value: Any) -> Any:
    """Money stays exact: a Decimal goes out as a string, never as a float (rule 1)."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def dumps(data: Any) -> str:
    return json.dumps(data, default=_json)


# ---------------------------------------------------------------------- dependencies
def reviewer(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Reviewer:
    reviewers = request.app.state.settings.reviewers
    if not reviewers:
        raise HTTPException(503, "no reviewers configured: set CLAIMSENSE_REVIEWERS")
    found = find_reviewer(reviewers, credentials.credentials) if credentials else None
    if found is None:
        raise HTTPException(
            401, "a reviewer token is required", headers={"WWW-Authenticate": "Bearer"}
        )
    return found


Who = Annotated[Reviewer, Depends(reviewer)]


def service(request: Request, _: Who) -> CaseService:
    """The case service, built on the first case request (it needs the `agents` extra)."""
    state = request.app.state
    with state.cases_lock:
        if state.cases is None:
            try:
                state.cases = CaseService(state.settings)
            except ImportError as exc:
                raise HTTPException(
                    503, "the case service needs .[agents] (and .[mcp] for CLAIMSENSE_TOOLS=mcp)"
                ) from exc
            except Exception as exc:  # e.g. a tool server whose definitions changed (pins)
                log.exception("the case service did not start")
                raise HTTPException(
                    503, f"the case service did not start ({type(exc).__name__})"
                ) from exc
    return state.cases


Cases = Annotated[CaseService, Depends(service)]


def _stream(events: Iterator[Event]) -> StreamingResponse:
    """Run the graph in a worker thread and send each event as it happens. If the client goes
    away, the run still reaches its next pause, so the checkpoint stays whole; read it with GET."""
    pending: queue.Queue[Any] = queue.Queue()

    def work() -> None:
        try:
            for event in events:
                pending.put(event)
        except Exception as exc:  # noqa: BLE001 - reported as an event, never a crash
            pending.put(error_event(type(exc).__name__))
        finally:
            pending.put(_END)

    async def body() -> AsyncIterator[str]:
        while (event := await anyio.to_thread.run_sync(pending.get)) is not _END:
            yield f"event: {event['event']}\ndata: {dumps(event['data'])}\n\n"

    threading.Thread(target=work, name="claimsense-case", daemon=True).start()
    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _start(cases: CaseService, case_id: str, packet: dict[str, Any], who: Reviewer):
    from claimsense.agents.llm import stub_mode

    if "claim" not in packet and stub_mode():
        raise HTTPException(422, "stub mode reads no documents: send a pre-extracted claim")
    if cases.busy(case_id) or cases.exists(case_id):
        raise HTTPException(409, f"case {case_id} exists; start the claim under another case_id")
    packet["received_at"] = datetime.now(UTC).isoformat()
    return _stream(cases.start(case_id, packet, who))


# ---------------------------------------------------------------------- routes
@router.post("/claims", tags=["cases"])
def start_claim(
    body: ClaimPacketIn, who: Who, cases: Cases, case_id: NewCaseId = None
) -> StreamingResponse:
    """Start a claim and stream the run until its first review pause."""
    packet = {k: v for k, v in body.model_dump(mode="json").items() if v is not None}
    return _start(cases, case_id or body.claim_id, packet, who)


@router.get("/me", tags=["reviewers"])
def who_am_i(who: Who) -> dict[str, str]:
    """The reviewer behind the token: the approver id and level the review gate signs with."""
    return {"approver_id": who.approver_id, "level": who.level.value}


@router.get("/demo/claims", tags=["demo"])
def list_demo_claims(who: Who) -> dict[str, Any]:
    """The synthetic claims the demo can start (dev and red-team fixtures)."""
    return {"claims": demo.demo_claims()}


@router.post("/demo/claims/{claim_id}", tags=["demo"])
def start_demo_claim(
    claim_id: CaseId, who: Who, cases: Cases, case_id: NewCaseId = None
) -> StreamingResponse:
    """Start a synthetic claim. Send it again under a new `case_id` to see the duplicate check."""
    packet = demo.demo_packet(claim_id)
    if packet is None:
        raise HTTPException(404, f"no synthetic claim {claim_id}")
    return _start(cases, case_id or claim_id, packet, who)


@router.get("/claims/{case_id}", tags=["cases"])
def read_case(case_id: CaseId, who: Who, cases: Cases) -> Response:
    """Status, plan, worksheet, pending review, approvals, settlement and trace of one case."""
    if not cases.exists(case_id):
        raise HTTPException(404, f"no case {case_id}")
    return Response(dumps(cases.summary(case_id)), media_type="application/json")


@router.post("/claims/{case_id}/decision", tags=["cases"])
def decide(case_id: CaseId, body: DecisionIn, who: Who, cases: Cases) -> StreamingResponse:
    """Approve, edit or reject the pending review; stream the run to its next pause or its end."""
    if not cases.exists(case_id):
        raise HTTPException(404, f"no case {case_id}")
    if cases.busy(case_id):
        raise HTTPException(409, "a run of this case is in progress")
    review = cases.pending_review(case_id)
    if review is None:
        raise HTTPException(409, "no decision is pending on this case")
    if review["level"] != who.level.value:
        article = "an" if review["level"] == "adjudicator" else "a"
        raise HTTPException(403, f"this review needs {article} {review['level']} reviewer")
    if who.level == ApprovalLevel.SENIOR and cases.approved_by(case_id, who.approver_id):
        raise HTTPException(
            403, "four eyes: the senior review needs someone other than the adjudicator"
        )
    metrics.record_decision(who.level.value, body.decision)
    decision = {
        "decision": body.decision,
        "approver_id": who.approver_id,
        "edits": [edit.model_dump(mode="json", exclude_none=True) for edit in body.edits],
        "note": body.note,
    }
    return _stream(cases.decide(case_id, decision, who))
