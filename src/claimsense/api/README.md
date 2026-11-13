# ClaimSense case API (L16)

The claim flow over HTTP. A reviewer starts a claim, watches the agents work as a live event
stream, and answers the review: approve, edit lines, or reject. Every rupee still comes from the
calculator, and a person still approves the exact worksheet (rules 1 and 3). The graph is the same
one `scripts/run_one.py` drives (`graph/build.py`), paused at each review with LangGraph
`interrupt()` and kept in a SQLite checkpoint between requests.

Owner: Deploy & Ops. Files: `main.py` (app), `cases.py` (routes), `runner.py` (runs the graph,
builds the events), `auth.py`, `metrics.py`, `demo.py`, `schemas.py`. Tests: `tests/api/`.

## Run it

```powershell
pip install -e ".[dev,agents]"
$env:CLAIMSENSE_LLM = "stub"        # free and deterministic; leave it out to use real models
$env:CLAIMSENSE_REVIEWERS = "local-alice=alice:adjudicator,local-bob=bob:senior"
uvicorn claimsense.api.main:app --port 8000
```

Git Bash: `export CLAIMSENSE_LLM=stub CLAIMSENSE_REVIEWERS="local-alice=alice:adjudicator,local-bob=bob:senior"`.
The keys above are for a local run only. Anywhere else, use long random values and keep them out
of the repository. Interactive docs: <http://127.0.0.1:8000/docs>.

Run one process (no `--workers`): the per-case lock and the stub stores live in that process.

## Settings (environment)

| Variable | Default | Meaning |
|---|---|---|
| `CLAIMSENSE_REVIEWERS` | none: case routes answer 503 | `<token>=<approver_id>:<adjudicator\|senior>`, comma-separated |
| `CLAIMSENSE_TOOLS` | `stub` | `stub`: in-process tools fed by the packet's `fixture_policy`. `real`: the tool servers' code in this process (`real_services()`). `mcp`: the four tool servers as their own processes, every agent tool call over the MCP protocol (ADR-0012). `real` and `mcp` use the signed approval store of the claims database |
| `CLAIMSENSE_CHECKPOINTS` | `claimsense_checkpoints.sqlite` | SQLite file that keeps paused cases across restarts (`:memory:` keeps nothing) |
| `CLAIMSENSE_LLM` | unset | `stub` forces the deterministic agents. Unset with `OPENROUTER_API_KEY` set means real models, which cost money |
| `CLAIMSENSE_DEMO_CLAIMS` | dev and red-team fixtures | JSONL files the demo routes read (synthetic claims only) |
| `LANGGRAPH_STRICT_MSGPACK` | unset | `true`: LangGraph loads only the checkpoint types the graph state names, and stops its "unregistered type" warnings. CI runs `tests/api` this way |

`real` tools need what `run_one.py --real-tools` needs: `CLAIMSENSE_APPROVAL_SECRET`, the seeded
policies (`python -m claimsense.mcp_servers.seed_dev_policies`) and the retrieval index
(`python -m claimsense.retrieval.index`).

`mcp` tools need the same, plus `pip install -e ".[mcp]"`. The API starts the four servers when it
starts (policy-kb opens its index first: up to about two minutes cold), so `/health` answers once
they are up, and it stops them on shutdown. A server whose advertised tools differ from
`config/tool_pins.json` is refused and the API does not start. Each server gets only the settings
it reads (`agents/mcp_services.py::SERVER_ENV`); the model key never reaches one.

## Endpoints

| Method and path | Who | What it does |
|---|---|---|
| `GET /health` | anyone | `{"status": "ok", "version": ...}` |
| `GET /metrics/` | anyone | Prometheus metrics (below) |
| `POST /claims[?case_id=]` | reviewer | Start a claim from a packet; stream the run to its first review |
| `GET /demo/claims` | reviewer | The synthetic claims the demo can start |
| `POST /demo/claims/{claim_id}[?case_id=]` | reviewer | Start a synthetic claim; stream the run |
| `GET /claims/{case_id}` | reviewer | Status, plan, worksheet, pending review, approvals, settlement, letter, trace |
| `POST /claims/{case_id}/decision` | reviewer of the level the review asks for | Approve, edit or reject; stream the run to its next review or its end |

A request names its reviewer with `Authorization: Bearer <token>`. The approver id and level come
from the token, never from the body, and the review gate signs the approval with that identity.
The case id is the checkpoint thread id and defaults to the claim id. Start the same claim again
under another `case_id` to see the duplicate check.

Packet body for `POST /claims`: `claim_id`, `policy_number` (the policy the intake system filed the
claim under, never read from the documents), `documents` (`{name: text}`), and optionally `claim`
(a hand-extracted claim), `fixture_policy` and `fixture_history` (what the stub claims database
returns). In stub mode `claim` is required: the stub agents read no documents.

Decision body: `{"decision": "approve" | "edit" | "reject", "edits": [...], "note": "..."}`. An
edit is `{"line_id", "clause_id"?, "amount"?, "reason"}`: re-point a line to another clause, or
correct a misread amount. Totals are never typed in: the calculator recomputes the worksheet, every
earlier approval becomes void, and the claim goes back to the adjudicator.

| Status | Means |
|---|---|
| 401 | no token, or a token not in `CLAIMSENSE_REVIEWERS` |
| 403 | the pending review needs the other level, or four eyes: the senior who reviews must be another person than the adjudicator who approved |
| 404 | no such case, or no such synthetic claim |
| 409 | the case exists already, a run of it is in progress, or no decision is pending |
| 422 | the body or a case id is invalid |
| 503 | no reviewers configured, or the `agents` extra is not installed |

## Stream events

The start and decision routes answer `text/event-stream`. Each event is `event: <name>` and
`data: <json>`. Money is a string (`"67067.10"`), never a float.

| Event | When | Data |
|---|---|---|
| `plan` | the plan changes | `revision`, `steps` (`name`, `agent`, `status`), `text` |
| `step` | a graph node finished | `node`, `trace` (the lines it added) |
| `worksheet` | the worksheet changed | the worksheet: lines, deductions with clause and reason, totals. Not sent while the claim is ruled not admissible |
| `review` | the run paused for a person | the review payload: `kind` (`worksheet` or `repudiation`), `level`, `worksheet`, `worksheet_hash`, `admissibility`, `fraud_flags`, `critic`, `escalation`, `plan` |
| `done` | the claim ended | `status` (`settled`, `repudiated`, `rejected`, `escalated`), `settlement`, `letter` |
| `error` | the run stopped | `error`: a class name or a condition (`CaseBusy`), never a message |

If the client goes away, the run still reaches its next pause; read the case with `GET`.

Rule 4: the packet (documents, diagnosis, bill descriptions) stays in the checkpoint. Events and
responses carry ids, amounts, clauses, flags and trace lines; `tests/api` checks that no diagnosis
or bill description reaches a response.

## The demo, step by step (Git Bash)

```bash
A="Authorization: Bearer local-alice"; B="Authorization: Bearer local-bob"; U=http://127.0.0.1:8000
J="Content-Type: application/json"

# 1. Room rent above the cap: proportionate deduction, adjudicator approves, claim settles.
curl -N -X POST -H "$A" $U/demo/claims/CLM-0004
curl -N -X POST -H "$A" -H "$J" -d '{"decision":"approve"}' $U/claims/CLM-0004/decision

# 2. An injected "pre-approved" note is flagged, and the same bill sent again is a duplicate.
curl -N -X POST -H "$A" $U/demo/claims/CLM-9001
curl -N -X POST -H "$A" "$U/demo/claims/CLM-0004?case_id=CLM-0004-again"

# 3. An edit voids the approval. CLM-0019 is above Rs 1,00,000, so it needs a senior too.
curl -N -X POST -H "$A" $U/demo/claims/CLM-0019
curl -N -X POST -H "$A" -H "$J" -d '{"decision":"approve"}' $U/claims/CLM-0019/decision
curl -N -X POST -H "$B" -H "$J" \
  -d '{"decision":"edit","edits":[{"line_id":"CLM-0019-L04","amount":"6000","reason":"bill shows Rs 6,000"}]}' \
  $U/claims/CLM-0019/decision            # new worksheet hash; approvals cleared; back to alice
curl -s -H "$A" $U/claims/CLM-0019       # "approvals": [], "edits": 1
curl -N -X POST -H "$A" -H "$J" -d '{"decision":"approve"}' $U/claims/CLM-0019/decision
curl -N -X POST -H "$B" -H "$J" -d '{"decision":"approve"}' $U/claims/CLM-0019/decision
```

PowerShell: use `curl.exe` (not the `curl` alias) for the streams. For a JSON body, use
`Invoke-RestMethod -Method Post -Uri $U/claims/CLM-0004/decision -Headers @{Authorization="Bearer local-alice"} -ContentType application/json -Body '{"decision":"approve"}'`;
it returns the whole stream when the run pauses or ends.

## Metrics

The first group uses the names and labels `eval/monitoring` defines, so the alert rules in
`eval/monitoring/alert_rules.yml` apply to live traffic unchanged (`tests/api/test_metrics.py`
checks it). The second group is the operations dashboard from the brief.

| Metric | Labels | For |
|---|---|---|
| `claimsense_claims_total` | `outcome`: `ready_for_approval`, `needs_review`, `error` | the agents' route at the first review |
| `claimsense_latency_seconds` | | receipt to the first review |
| `claimsense_tokens_total`, `claimsense_cost_usd_total` | `kind` (tokens) | model use; cost per claim = cost / claims |
| `claimsense_tool_calls_total` | `tool`, `status`: `ok`, `error`, `blocked` | tool health; `blocked` = the tool ACL refused |
| `claimsense_guardrail_trips_total` | `rule`: `prompt_injection`, `tool_acl` | guardrails that stopped something |
| `claimsense_in_flight` | | claim runs executing now |
| `claimsense_claims_processed_total` | `outcome`: `settled`, `repudiated`, `rejected`, `escalated`, `error` | claims processed |
| `claimsense_review_decisions_total` | `level`, `decision` | adjudicator edit rate = `edit` / all decisions |
| `claimsense_rupees_deducted_total` | `reason` (`DeductionReason`, co-pay included) | rupees deducted by reason, on settled and repudiated claims |
| `claimsense_fraud_flags_total` | `kind`: `duplicate`, `tariff`, `sub_limit`, `bill_total`, `dates`, `injection`, `other` | fraud flags on decided claims |
| `claimsense_turnaround_seconds` | | receipt to the final outcome |

No claim id, approver id or claim text is ever a label. `error` in the processed counter counts a
run that stopped with an error; the case stays where it was, so a retry can still finish it.

## Limits

- Identity is demo-grade: static tokens from the environment. A deployment replaces
  `auth.ApiIdentityProvider` with single sign-on; the review gate needs no change.
- With stub tools, approvals and the claim history live in memory: a restart keeps the paused cases
  (checkpoint) but forgets earlier claims, so the duplicate check starts empty.
- Each request runs with a fresh tool budget, as a claim resumed after a restart does
  (`graph/nodes.py`).
