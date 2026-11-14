"""The adjudicator's case UI (L16): a Streamlit client of the case API (ADR-0015).

    python -m claimsense.ui      # http://127.0.0.1:8501, calls the API at CLAIMSENSE_API_URL

Start or open a case, watch the run stream, approve, edit a line or reject, read the letter; and
an operations dashboard from the API's metrics. Rules the page keeps:
- Every string that comes from the API is shown with st.text, st.code or a table, never as
  markdown: fraud flags quote the claim's documents (rule 2). Our own labels escape any id.
- Reviewer tokens stay in this session's state, go only to the API, and are never shown.
- The page computes no amount: the worksheet and its totals come from the calculator.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pandas as pd
import streamlit as st

from claimsense.ui import views
from claimsense.ui.client import ApiClient, ApiError, Event

API_URL = os.environ.get("CLAIMSENSE_API_URL", "http://127.0.0.1:8000")
#: The capstone demo (guide p. 10), in order: button key, label, claim id, case id.
SCENES = (
    ("scene_1", "1 · Room rent above the cap", "CLM-0004", "CLM-0004"),
    ("scene_2", "2 · Injected 'pre-approved' note", "CLM-9001", "CLM-9001"),
    ("scene_2b", "2 · The same bill sent again", "CLM-0004", "CLM-0004-again"),
    ("scene_3", "3 · An edit voids the approval", "CLM-0019", "CLM-0019"),
)
DOCUMENTS = (
    ("claim_form", "Claim form"),
    ("discharge_summary", "Discharge summary"),
    ("itemised_bill", "Itemised bill"),
    ("policy_schedule", "Policy schedule"),
)


# ------------------------------------------------------------------------------- callbacks
# Buttons only record what to do; the page body does it, so the run can stream where it shows.
def sign_in() -> None:
    s = st.session_state
    token, s.token = s.token.strip(), ""  # the field is cleared at once
    if not token:
        return
    try:
        me = s.api.me(token)
    except ApiError as exc:
        s.refusal = exc
        return
    label = f"{me['approver_id']} · {me['level']}"
    s.identities[label] = {"token": token, **me}
    s.acting = label


def sign_out() -> None:
    s = st.session_state
    s.identities.pop(s.get("acting"), None)
    if s.identities:
        s.acting = next(iter(s.identities))
    else:
        del s["acting"]


def queue(action: dict[str, Any]) -> None:
    st.session_state.action = action


def queue_demo() -> None:
    s = st.session_state
    if s.get("demo_claim"):
        queue({"kind": "demo", "claim_id": s.demo_claim, "case_id": s.demo_case_id.strip()})


def queue_upload() -> None:
    s = st.session_state
    try:
        if s.upload_mode == "Packet JSON":
            upload = s.get("up_packet_file")
            text = upload.getvalue().decode("utf-8", "replace") if upload else s.up_packet_json
            packet = views.packet_from_json(text)
        else:
            documents = {key: s.get(f"up_{key}", "") for key, _ in DOCUMENTS}
            for upload in s.get("up_files") or []:
                documents[upload.name] = upload.getvalue().decode("utf-8", "replace")
            packet = views.packet_from_documents(
                s.up_claim_id, s.up_policy, documents, s.up_claim_json
            )
    except ValueError as exc:
        s.notice = str(exc)
        return
    queue({"kind": "packet", "packet": packet, "case_id": s.up_case_id.strip()})


def open_case() -> None:
    s = st.session_state
    if s.open_case_id.strip():
        s.case_id = s.open_case_id.strip()


def queue_decision(decision: str) -> None:
    s = st.session_state
    body: dict[str, Any] = {"decision": decision}
    if decision == "reject" and s.get("reject_note", "").strip():
        body["note"] = s.reject_note.strip()
    queue({"kind": "decide", "body": body})


def queue_edit() -> None:
    s = st.session_state
    edit = {"line_id": s.edit_line, "reason": s.edit_reason.strip()}
    if s.edit_clause.strip():
        edit["clause_id"] = s.edit_clause.strip()
    if s.edit_amount.strip():
        edit["amount"] = s.edit_amount.strip().replace(",", "")
    if not edit["reason"]:
        s.notice = "An edit needs a reason."
    elif "clause_id" not in edit and "amount" not in edit:
        s.notice = "Give the line a new clause, a corrected amount, or both."
    else:
        s.edit_clause = s.edit_amount = s.edit_reason = ""
        queue({"kind": "decide", "body": {"decision": "edit", "edits": [edit]}})


# ------------------------------------------------------------------------------- page parts
def refused(exc: ApiError) -> None:
    """A refusal: our own headline, then the API's reason as plain text."""
    st.error(f"The API refused this ({exc.status})." if exc.status else "No answer from the API.")
    st.text(exc.detail)


def sidebar(s: Any) -> dict[str, str] | None:
    """API status, sign-in, the identity acting now, and the page switch."""
    bar = st.sidebar
    bar.title("ClaimSense")
    bar.caption("Case UI for the claims adjudicator")
    try:
        health = s.api.health()
        bar.caption(
            f"API {health.get('version', '?')} · agents: {health.get('llm', '?')} · "
            f"tools: {health.get('tools', '?')}"
        )
        s.llm = health.get("llm")
    except ApiError as exc:
        bar.error("No answer from the API.")
        bar.text(exc.detail)
        s.llm = None
    bar.radio("Page", ("Claims", "Dashboard"), key="page", horizontal=True)
    bar.subheader("Reviewer")
    bar.text_input("Reviewer token", type="password", key="token", placeholder="paste a token")
    bar.button("Sign in", key="sign_in", on_click=sign_in)
    if not s.identities:
        return None
    bar.radio("Acting as", tuple(s.identities), key="acting")
    bar.button("Sign out", key="sign_out", on_click=sign_out)
    return s.identities[s.acting]


def start_panel(s: Any, me: dict[str, str]) -> None:
    with st.expander("Start or open a claim", expanded=not s.get("case_id")):
        demo, upload, existing = st.tabs(["Demo claims", "Upload a packet", "Open a case"])
        with demo:
            st.caption("The capstone demo in order. Scene 2's second claim needs scene 1 settled.")
            for column, (key, label, claim_id, case_id) in zip(
                st.columns(len(SCENES)), SCENES, strict=True
            ):
                column.button(
                    label,
                    key=key,
                    width="stretch",
                    on_click=queue,
                    args=({"kind": "demo", "claim_id": claim_id, "case_id": case_id},),
                )
            st.selectbox("Any synthetic claim", demo_claim_ids(s, me), key="demo_claim")
            st.text_input("Case id (optional: a new id starts the claim again)", key="demo_case_id")
            st.button("Start", key="demo_start", on_click=queue_demo)
        with upload:
            upload_form(s)
        with existing:
            st.text_input("Case id", key="open_case_id")
            st.button("Open", key="open_case", on_click=open_case)


def demo_claim_ids(s: Any, me: dict[str, str]) -> list[str]:
    if "demo_ids" not in s:
        try:
            s.demo_ids = [claim["claim_id"] for claim in s.api.demo_claims(me["token"])]
        except ApiError:
            return []
    return s.demo_ids


def upload_form(s: Any) -> None:
    mode = st.radio("Upload as", ("Documents", "Packet JSON"), key="upload_mode", horizontal=True)
    if mode == "Documents":
        st.text_input("Claim id", key="up_claim_id")
        st.text_input("Policy number (as the claim was filed)", key="up_policy")
        st.file_uploader("Documents (.txt, .md)", ["txt", "md"], True, key="up_files")
        for key, label in DOCUMENTS:
            st.text_area(label, key=f"up_{key}", height=100)
        hint = (
            " The agents run in stub mode and read no documents: this is needed."
            if (s.get("llm") == "stub")
            else ""
        )
        st.text_area(f"Extracted claim (JSON, optional).{hint}", key="up_claim_json", height=100)
    else:
        st.file_uploader("Packet (.json)", ["json"], key="up_packet_file")
        st.text_area("or paste the packet", key="up_packet_json", height=160)
    st.text_input("Case id (optional)", key="up_case_id")
    st.button("Start", key="up_start", on_click=queue_upload)


def perform(s: Any, me: dict[str, str], action: dict[str, Any]) -> None:
    """Run what a button asked for, streaming the run where the page shows it."""
    token = me["token"]
    if action["kind"] == "decide":
        case_id = s.case_id
        events = s.api.decide(token, case_id, action["body"])
        title = f"{action['body']['decision']} by {me['approver_id']}"
    elif action["kind"] == "demo":
        case_id = action["case_id"] or action["claim_id"]
        events = s.api.start_demo(token, action["claim_id"], case_id)
        title = f"Start {action['claim_id']}"
    else:
        case_id = action["case_id"] or action["packet"]["claim_id"]
        events = s.api.start_packet(token, action["packet"], case_id)
        title = f"Start {action['packet']['claim_id']}"
    s.case_id = case_id  # a case that exists already (409) is then simply shown
    stream(f"{title} · case {case_id}", events)


def stream(title: str, events: Iterator[Event]) -> None:
    """The run as it streams: the plan, each step's trace lines, the worksheet when it changes."""
    label, failure = views.md_escape(title), None
    with st.status(label, expanded=True) as box:
        plan_slot, trace_slot, sheet_slot = st.empty(), st.empty(), st.empty()
        trace: list[str] = []
        try:
            for name, data in events:
                if name == "run":  # the run id the audit trail and the trace carry (rubric D3)
                    label = f"{label} · run {views.md_escape(str(data['run_id'])[:8])}"
                    box.update(label=label)
                elif name == "plan":
                    plan_slot.dataframe(pd.DataFrame(views.plan_rows(data)), hide_index=True)
                elif name == "step":
                    trace += data.get("trace", [])
                    trace_slot.code("\n".join(trace), language=None)
                elif name == "worksheet":
                    sheet_slot.dataframe(pd.DataFrame(views.worksheet_rows(data)), hide_index=True)
                elif name == "review":  # collapsed: the case below is what to look at now
                    who = views.a_level(data["level"])
                    box.update(
                        label=f"{label}: waiting for {who} reviewer",
                        state="complete",
                        expanded=False,
                    )
                elif name == "done":
                    box.update(label=f"{label}: {data['status']}", state="complete", expanded=False)
                elif name == "error":
                    box.update(label=f"{label}: stopped ({data['error']})", state="error")
        except ApiError as exc:
            failure = exc
            box.update(label=f"{label}: refused", state="error", expanded=False)
    if failure:
        refused(failure)


def case_panel(s: Any, me: dict[str, str]) -> None:
    try:
        case = s.api.case(me["token"], s.case_id)
    except ApiError as exc:
        refused(exc)
        return
    seen = views.remember_approvals(s.seen.get(case["case_id"], []), case)
    s.seen[case["case_id"]] = seen
    review, sheet, now = case.get("review"), case.get("worksheet"), views.current_hash(case)

    st.header(f"Case {views.md_escape(case['case_id'])}")
    status, claim, version, edits = st.columns(4)
    status.metric("Status", case["status"].replace("_", " "))
    claim.metric("Claim", case["claim_id"])
    version.metric("Worksheet", f"v{sheet['version']}" if sheet else "none")
    edits.metric("Edits", case.get("edits", 0))
    if now:
        st.caption(f"Worksheet hash {now[:12]}: an approval binds to this exact worksheet.")
    if review:
        needed = views.a_level(review["level"])
        st.subheader(f"Waiting for {needed} reviewer")
        if review["level"] != me["level"]:
            st.info(
                f"This review needs {needed} reviewer. You are acting as "
                f"{views.md_escape(me['approver_id'])} ({me['level']})."
            )
    flags(case.get("fraud_flags") or [])
    review_findings(review or {})
    if sheet:
        worksheet(sheet)
    approvals(views.mark_void(seen, now))
    if review and case["status"] == "awaiting_review":
        decision_box(review, views.edit_line_ids(case))
    outcome(case)
    if case.get("trace"):
        with st.expander("Audit trail"):
            st.code("\n".join(case["trace"]), language=None, wrap_lines=True)


def flags(found: list[str]) -> None:
    if not found:
        return
    st.subheader("Flags")
    for kind, flag in views.flag_rows(found):
        badge, text = st.columns([1, 6])
        badge.badge(kind, color="red" if kind in ("injection", "duplicate") else "orange")
        text.text(flag)


def review_findings(review: dict[str, Any]) -> None:
    admissibility = review.get("admissibility") or {}
    if admissibility and (
        not admissibility.get("admissible", True) or admissibility.get("needs_review")
    ):
        st.subheader("Admissibility")
        st.text("Not admissible." if not admissibility.get("admissible") else "Needs a person.")
        for reason in admissibility.get("reasons", []):
            st.text(str(reason))
        if admissibility.get("clause_ids"):
            st.text("Clauses: " + ", ".join(admissibility["clause_ids"]))
    if review.get("critic"):
        st.subheader("Critic")
        for finding in review["critic"]:
            st.text(str(finding))
    if review.get("escalation"):
        st.subheader("Escalated")
        st.text(str(review["escalation"]))


def worksheet(sheet: dict[str, Any]) -> None:
    st.subheader("Worksheet")
    st.dataframe(pd.DataFrame(views.worksheet_rows(sheet)), hide_index=True, width="stretch")
    total = views.totals(sheet)
    for column, (label, key) in zip(
        st.columns(4),
        (
            ("Claimed", "claimed"),
            ("Deducted", "deducted"),
            ("Co-pay", "co_pay"),
            ("Payable", "payable"),
        ),
        strict=True,
    ):
        column.metric(label, total[key])
    with st.expander("How each deduction was computed", expanded=True):
        st.dataframe(pd.DataFrame(views.deduction_rows(sheet)), hide_index=True, width="stretch")


def approvals(marked: list[dict[str, Any]]) -> None:
    if not marked:
        return
    st.subheader("Approvals")
    rows = [
        {
            "approver": a["approver_id"],
            "level": a["level"],
            "decided at": a["decided_at"],
            "worksheet": (a.get("worksheet_hash") or "")[:12],
            "state": "void: the worksheet changed after it" if a["void"] else "valid",
        }
        for a in marked
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def decision_box(review: dict[str, Any], line_ids: list[str]) -> None:
    """Approve · Edit a line · Reject, side by side, on every review. On a claim ruled not
    admissible an edit overrides the ruling (`apply_edits`), so it is offered there too."""
    st.subheader("Decision")
    says = views.decision_texts(review.get("kind", "worksheet"))
    approve, edit, reject = st.columns(3)
    with approve:
        st.markdown("**Approve**")
        st.caption(says["approve"])
        st.button(
            "Approve", key="approve", type="primary", on_click=queue_decision, args=("approve",)
        )
    with edit:
        st.markdown("**Edit a line**")
        st.caption(says["edit"])
        if line_ids:
            with st.form("edit"):
                st.selectbox("Line", line_ids, key="edit_line")
                st.text_input(
                    "New clause id (optional)",
                    key="edit_clause",
                    help="A policy clause id, e.g. new_india_arogya_sanjeevani:4.1",
                )
                st.text_input("Corrected amount in Rs (optional)", key="edit_amount")
                st.text_input("Reason", key="edit_reason")
                st.form_submit_button("Submit edit", key="edit_submit", on_click=queue_edit)
        else:
            st.caption("This case has no lines to edit.")
    with reject:
        st.markdown("**Reject**")
        st.caption(says["reject"])
        st.text_input("Reason for rejecting (optional)", key="reject_note")
        st.button("Reject", key="reject", on_click=queue_decision, args=("reject",))


def outcome(case: dict[str, Any]) -> None:
    settlement = case.get("settlement") or {}
    if settlement:
        st.subheader("Settlement")
        parts = [str(settlement.get("status", ""))]
        if settlement.get("amount"):
            parts.append(views.inr(settlement["amount"]))
        if settlement.get("worksheet_hash"):
            parts.append(f"worksheet {str(settlement['worksheet_hash'])[:12]}")
        st.text(" · ".join(parts))
    if case.get("letter"):
        st.subheader("Letter")
        st.code(case["letter"], language=None, wrap_lines=True)


def dashboard_page(api: ApiClient) -> None:
    st.header("Operations dashboard")
    try:
        numbers = views.dashboard(api.metrics_text())
    except ApiError as exc:
        refused(exc)
        return
    st.caption(
        "Counts since the API process started. Grafana keeps the history and alerts when the "
        "edit rate rises (Phase 4)."
    )
    rate, cost, turnaround = (
        numbers["edit_rate"],
        numbers["cost_per_claim_usd"],
        numbers["turnaround_mean_s"],
    )
    tiles = (
        ("Claims processed", numbers["processed_total"]),
        ("Edit rate", "none yet" if rate is None else f"{rate:.0%}"),
        ("Fraud flags", sum(numbers["flags"].values())),
        ("Mean turnaround", _duration(turnaround)),
        ("Cost per claim", "none yet" if cost is None else f"${cost:.4f}"),
        ("Claims running now", numbers["in_flight"]),
    )
    for column, (label, value) in zip(st.columns(3) + st.columns(3), tiles, strict=True):
        column.metric(label, value)
    st.subheader("Rupees deducted by reason")
    if numbers["deducted"]:
        frame = pd.DataFrame(
            {"reason": list(numbers["deducted"]), "rupees": list(numbers["deducted"].values())}
        )
        st.bar_chart(frame, x="reason", y="rupees")
    else:
        st.caption("No claim decided yet.")
    outcomes, kinds = st.columns(2)
    with outcomes:
        st.subheader("Claims by outcome")
        _counts(numbers["processed"], "outcome")
    with kinds:
        st.subheader("Fraud flags by kind")
        _counts(numbers["flags"], "kind")
    decisions, tools = st.columns(2)
    with decisions:
        st.subheader("Review decisions")
        _counts(numbers["decisions"], "level and decision")
    with tools:
        st.subheader("Tool calls")
        _counts(numbers["tool_calls"], "status")


def _counts(counts: dict[str, int], name: str) -> None:
    if counts:
        st.dataframe(
            pd.DataFrame({name: list(counts), "count": list(counts.values())}), hide_index=True
        )
    else:
        st.caption("None yet.")


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "none yet"
    if seconds < 120:
        return f"{seconds:.0f} s"
    return f"{seconds / 60:.1f} min" if seconds < 7200 else f"{seconds / 3600:.1f} h"


# ------------------------------------------------------------------------------- the page
def main() -> None:
    st.set_page_config(page_title="ClaimSense case UI", page_icon="🩺", layout="wide")
    s = st.session_state
    if s.get("api") is None:
        s.api = ApiClient.from_url(API_URL)
    s.setdefault("identities", {})  # "alice · adjudicator" -> token, approver id, level
    s.setdefault("seen", {})  # case id -> approvals seen, with the worksheet hash of each
    me = sidebar(s)
    if refusal := s.pop("refusal", None):
        refused(refusal)
    if notice := s.pop("notice", None):
        st.warning(views.md_escape(notice))
    if s.page == "Dashboard":
        dashboard_page(s.api)
        return
    if me is None:
        st.info("Sign in with a reviewer token (sidebar) to start or open claims.")
        return
    start_panel(s, me)
    if action := s.pop("action", None):
        perform(s, me, action)
    if s.get("case_id"):
        case_panel(s, me)


main()
