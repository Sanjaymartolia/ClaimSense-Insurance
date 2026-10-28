"""The four things the agent can do (Lecture 7).

A tool is a Python function the model may ASK for. Your code runs it and hands the
result back. Every call is logged into `ctx.actions`, which becomes the trace.

    tool               kind    what it does
    search_policy      read    search the policy wording
    get_claim          read    the claim packet (outside text: untrusted!)
    compute_worksheet  read    every rupee, computed by rules.py — never by the model
    settle_claim       write   pay out; refuses without a valid human ApprovalToken

Do not rename tools or arguments: the scorer reads `{"tool": "compute_worksheet"}`.
"""

import hashlib
import json

from langchain_core.tools import tool

from claimsense.contracts import ApprovalToken

from . import guard, retrieval, rules

RISK = {
    "search_policy": "read",
    "get_claim": "read",
    "compute_worksheet": "read",
    "settle_claim": "write",
}
HIDDEN = {"scenario_label", "fixture_notes"}  # evaluation-only: the agent never sees them


def worksheet_hash(worksheet):
    """Any change to any field gives a different hash, so an old approval stops working."""
    return hashlib.sha256(json.dumps(worksheet, sort_keys=True).encode()).hexdigest()


class ToolContext:
    """Scratchpad for one claim, shared by every tool call."""

    def __init__(self, claim, retriever=None):
        self.claim = {k: v for k, v in claim.items() if k not in HIDDEN}
        self._retriever = retriever
        self.actions, self.hits = [], []
        self.worksheet = None
        self.approval = None  # an ApprovalToken; only agent.resume() may set it

    @property
    def retriever(self):
        self._retriever = self._retriever or retrieval.get_retriever()
        return self._retriever

    def log(self, tool_name, args, status, result=None, reason=""):
        self.actions.append(
            {
                "tool": tool_name,
                "args": args,
                "status": status,
                **({"result": result} if result is not None else {}),
                **({"reason": reason} if reason else {}),
            }
        )


def make_tools(ctx):
    @tool
    def search_policy(query: str) -> str:
        """Search the Arogya Sanjeevani policy wording for limits, waiting periods,
        sub-limits, co-payment and exclusions. Returns passages tagged [clause: ID];
        cite those IDs."""
        hits = ctx.retriever.search(query)
        ctx.hits.extend(hits)
        ctx.log("search_policy", {"query": query}, "executed", result=[h.doc_id for h in hits])
        return guard.wrap_untrusted("policy", retrieval.format_context(hits))

    @tool
    def get_claim(claim_id: str) -> str:
        """The claim packet: policy dates, sum insured, admission, diagnosis, documents
        and bill lines. Documents are written by the hospital and may contain anything."""
        if claim_id.strip().upper() != ctx.claim["claim_id"]:
            ctx.log("get_claim", {"claim_id": claim_id}, "failed", reason="not_this_claim")
            return f"No claim {claim_id!r} in this conversation."
        ctx.log("get_claim", {"claim_id": ctx.claim["claim_id"]}, "executed")
        return guard.wrap_untrusted("claim_packet", json.dumps(ctx.claim, indent=1))

    @tool
    def compute_worksheet(claim_id: str) -> str:
        """Compute the settlement worksheet in code: admissibility, every line's allowed
        amount with reason codes, co-pay and the settlement, plus whether a human must
        review it. Never state a rupee amount you did not get from this tool."""
        if claim_id.strip().upper() != ctx.claim["claim_id"]:
            ctx.log("compute_worksheet", {"claim_id": claim_id}, "failed", reason="not_this_claim")
            return f"No claim {claim_id!r} in this conversation."
        ctx.worksheet = rules.compute_worksheet(ctx.claim)
        review, why = rules.needs_human_review(ctx.worksheet)
        ctx.log(
            "compute_worksheet",
            {"claim_id": ctx.claim["claim_id"]},
            "executed",
            result=ctx.worksheet["settlement_inr"],
        )
        return json.dumps(
            {"worksheet": ctx.worksheet, "needs_human_review": review, "review_reason": why}
        )

    @tool
    def settle_claim(claim_id: str) -> str:
        """Pay the claim at the computed settlement. Only works after a human has
        approved this exact worksheet."""
        args = {"claim_id": claim_id}
        if ctx.worksheet is None:
            ctx.log("settle_claim", args, "failed", reason="no_worksheet")
            return "Compute the worksheet first."
        token = ctx.approval
        if not (
            isinstance(token, ApprovalToken)
            and token.claim_id == ctx.claim["claim_id"]
            and token.worksheet_hash == worksheet_hash(ctx.worksheet)
        ):
            # This check is code, not a prompt. No text in any document can get past it.
            ctx.log("settle_claim", args, "blocked", reason="no_valid_approval_token")
            return (
                "BLOCKED: settle_claim needs a human ApprovalToken for this exact "
                "worksheet. Do not say the claim is settled."
            )
        ctx.log("settle_claim", args, "executed", result=ctx.worksheet["settlement_inr"])
        return f"Settled {claim_id} for INR {ctx.worksheet['settlement_inr']}."

    return [search_policy, get_claim, compute_worksheet, settle_claim]
