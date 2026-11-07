"""Run ONE claim from eval/golden_dev/claims.jsonl through the LangGraph with a real LLM,
printing a node-by-node trace.

Usage (from repo root):
    python scripts/run_one.py --list                       # show the 20 claim ids
    python scripts/run_one.py <claim_id>                   # auto-approve every pause
    python scripts/run_one.py <claim_id> --reviewer console
    python scripts/run_one.py <claim_id> --sqlite          # durable checkpointer
    python scripts/run_one.py <claim_id> --file eval/golden_dev/claims.jsonl
    python scripts/run_one.py <claim_id> --real-tools      # policy-kb / claims-db / tariff
    python scripts/run_one.py <claim_id> --no-tool-hooks   # skip the ACL/budget/audit hooks

Agents use OpenRouter models (agents/llm.py). Tools are stubs (make_stub_services) by default.
--real-tools uses agents/services.real_services() and signs approvals into the claims-db approval
store that settle_claim verifies against. It needs CLAIMSENSE_APPROVAL_SECRET set, the policy
seeded (python -m claimsense.mcp_servers.seed_dev_policies) and the policy index built.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CLAIMS = REPO_ROOT / "eval" / "golden_dev" / "claims.jsonl"

# Make `import claimsense` work even without `pip install -e .`
sys.path.insert(0, str(REPO_ROOT / "src"))

# ---- 1. Load .env BEFORE importing claimsense, so get_llm() sees the key ----
try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass  # fine if the key is already exported in the shell


# ---- 2. Read claims.jsonl ----
ID_KEYS = ("claim_id", "id", "case_id")


def record_id(rec: dict) -> str | None:
    """Find the claim id at the top level or inside rec['packet']."""
    for source in (rec, rec.get("packet") or {}):
        for key in ID_KEYS:
            if source.get(key):
                return str(source[key])
    return None


def read_claims(path: Path) -> list[dict]:
    if not path.exists():
        sys.exit(f"Claims file not found: {path}")
    records = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as err:
                sys.exit(f"{path}:{line_no} is not valid JSON: {err}")
    return records


def find_claim(path: Path, claim_id: str) -> dict:
    records = read_claims(path)
    for rec in records:
        if record_id(rec) == claim_id:
            return rec
    ids = ", ".join(str(record_id(r)) for r in records)
    sys.exit(f"Claim id '{claim_id}' not in {path}.\nAvailable: {ids}")


def to_packet(rec: dict) -> dict:
    """Map a starter-pack fixture to a graph packet using the team's single ADR-0002 adapter.
    Returns {"claim_id", "claim", "documents": {}, "fixture_policy"}; scenario_label and
    fixture_notes are dropped there, so the agents never see them."""
    from claimsense.reflexion.cases import packet_from_fixture

    return packet_from_fixture(rec)


# ---- 3. Reviewers for the human-review pauses ----
def auto_reviewer(payload: dict) -> dict:
    return {"decision": "approve", "approver_id": "trace-run"}


def console_reviewer(payload: dict) -> dict:
    print("\n" + "=" * 70 + f"\n⏸  PAUSED for human review: {payload.get('kind')}")
    print(json.dumps(payload, indent=2, default=str)[:4000])
    choice = input("approve / reject? [approve]: ").strip() or "approve"
    return {"decision": choice, "approver_id": input("approver id [adj-1]: ").strip() or "adj-1"}


# ---- 4. Trace printing ----
def to_text(value) -> str:
    if hasattr(value, "model_dump_json"):
        return value.model_dump_json(indent=2)
    return json.dumps(
        value, indent=2, default=lambda o: o.model_dump() if hasattr(o, "model_dump") else str(o)
    )


def show(node: str, update) -> None:
    print("\n" + "-" * 70 + f"\n▶ {node}")
    if not isinstance(update, dict):
        print(f"  {update!r}")
        return
    for key, value in update.items():
        text = to_text(value)
        print(f"  {key}: {text[:1500]}{' …' if len(text) > 1500 else ''}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run one golden_dev claim with full trace")
    ap.add_argument("claim_id", nargs="?", help="claim id as stored in claims.jsonl")
    ap.add_argument("--file", type=Path, default=DEFAULT_CLAIMS)
    ap.add_argument("--list", action="store_true", help="list claim ids and exit")
    ap.add_argument("--reviewer", choices=["auto", "console"], default="auto")
    ap.add_argument("--sqlite", action="store_true", help="use the durable SQLite checkpointer")
    ap.add_argument("--max-rounds", type=int, default=8)
    ap.add_argument(
        "--real-tools", action="store_true", help="real MCP-backed tools instead of stubs"
    )
    ap.add_argument(
        "--no-tool-hooks",
        action="store_true",
        help="do not install the per-claim tool hooks (ACL, budget, audit)",
    )
    args = ap.parse_args()

    if args.list:
        for rec in read_claims(args.file):
            print(record_id(rec))
        return
    if not args.claim_id:
        ap.error("give a claim_id, or use --list")

    rec = find_claim(args.file, args.claim_id)
    packet = to_packet(rec)

    # Real-mode guards, checked before spending tokens
    if os.environ.get("CLAIMSENSE_LLM") == "stub":
        sys.exit("CLAIMSENSE_LLM=stub is set; run `unset CLAIMSENSE_LLM` first.")
    if not os.environ.get("OPENROUTER_API_KEY"):
        sys.exit("OPENROUTER_API_KEY not found (put it in .env or export it).")
    if args.real_tools and not os.environ.get("CLAIMSENSE_APPROVAL_SECRET"):
        sys.exit("--real-tools needs CLAIMSENSE_APPROVAL_SECRET (put it in .env or export it).")

    from langgraph.types import Command

    from claimsense.agents import PolicyInfo, Team, make_stub_services
    from claimsense.agents.llm import get_llm
    from claimsense.agents.services import real_services
    from claimsense.graph.build import (
        build_graph,
        memory_checkpointer,
        production_review_kwargs,
        sqlite_checkpointer,
    )
    from claimsense.graph.state import initial_state

    llm = get_llm("coverage")
    if llm is None:
        sys.exit("get_llm() returned None: still in stub mode. Check agents/llm.py.")
    print(f"LLM mode ON  (coverage model: {getattr(llm, 'model_name', '?')})")

    pol = PolicyInfo.model_validate(packet["fixture_policy"])
    if args.real_tools:
        services = real_services()
        if services.get_policy(pol.policy_number) is None:
            sys.exit(
                f"Policy {pol.policy_number} is not in the claims DB. Seed it first:\n"
                "    python -m claimsense.mcp_servers.seed_dev_policies"
            )
        # Approvals must land in the store claims_db.settle_claim verifies against.
        review_kwargs = production_review_kwargs()
    else:
        # Same as reflexion.cases.stub_services_factory: policy record keyed by policy_number
        services = make_stub_services(policies={pol.policy_number: pol})
        review_kwargs = {}  # in-memory approval store; stub settle_claim checks hashes only
    team = Team(services)
    print(f"Tools: {'REAL (real_services)' if args.real_tools else 'stubs'}")

    checkpointer = sqlite_checkpointer() if args.sqlite else memory_checkpointer()
    # Tool hooks (hooks/hooks.py): installed once for this claim, with a fresh tool budget.
    tool_hooks = not args.no_tool_hooks
    print(f"Tool hooks: {'ON' if tool_hooks else 'off'}")
    app = build_graph(team, checkpointer, tool_hooks=tool_hooks, **review_kwargs)
    cfg = {"configurable": {"thread_id": args.claim_id}}
    reviewer = console_reviewer if args.reviewer == "console" else auto_reviewer

    print(f"Running claim {args.claim_id} from {args.file}")
    # Full initial state: nodes read max_revisions, approvals, trace ... from the start.
    graph_input = initial_state(packet)

    for _ in range(args.max_rounds):
        interrupt_payload = None
        for chunk in app.stream(graph_input, cfg, stream_mode="updates"):
            for node, update in chunk.items():
                if node == "__interrupt__":
                    interrupt_payload = update[0].value
                else:
                    show(node, update)
        if interrupt_payload is None:
            break  # graph reached END
        decision = reviewer(interrupt_payload)
        print(f"\n↩ resume with {decision}")
        graph_input = Command(resume=decision)
    else:
        print(f"\n⚠ stopped after {args.max_rounds} rounds")

    final = app.get_state(cfg).values
    print("\n" + "=" * 70 + "\nFINAL")
    for key in ("plan", "worksheet", "fraud_flags", "coverage_notes", "settlement"):
        if key in final:
            show(key, {key: final[key]})
    print("\nTool log:")
    for entry in services.tool_log:
        print("  ", entry)


if __name__ == "__main__":
    main()
