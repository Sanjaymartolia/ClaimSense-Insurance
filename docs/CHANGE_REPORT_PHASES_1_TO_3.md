# ClaimSense: what changed in Phases 1 to 3

**For:** the whole team, including anyone who did not follow the work day by day.
**Period:** 12 to 14 November 2026. **Written by:** Eval & Red-Team.
**State:** Phases 1, 2 and 3 are on `main` (commits `4e46e8d`, `2462975` and `49f705e`). CI run
#110 on Phase 3 passed every job, including the first Docker build.

This report says what the project could do before, what it can do now, why each change was made,
how it was checked, and what each role should look at next. Commands are for Windows PowerShell
from the repository root; Git Bash works the same with `export NAME=value`.

---

## 1. Summary

- **CI is green again.** It was red from 12 November (113 lint errors). Phase 1 fixed lint and added
  a free eval gate. Runs #106 to #109 on `main` passed.
- **The product now has a working API.** Before, it answered only `/health` and `/metrics`. Now a
  reviewer can start a claim, watch the agents work live (streaming), and approve, edit or reject
  it, with two approval levels and a four-eyes rule.
- **The agents can now call their tools over MCP.** Before, they imported the tool servers as
  Python modules. Now each server can run as its own process, and the client refuses a server
  whose tools changed since review.
- **There is a user interface.** Before, `src/claimsense/ui/` was empty. Now a Streamlit case UI
  runs the three capstone demo scenes, and a dashboard page shows the L16 numbers.
- **Docker Compose and CI cover the UI.** Compose starts the API and the UI together. A new CI job
  builds both images and checks that they work.
- **Settlement is safer.** A claim cannot be paid twice, and an approval works only for its own
  purpose (Phase 1).

---

## 2. Before and after, at a glance

| Area | Before (12 November) | After (14 November) |
|---|---|---|
| CI | Red at `ruff check` since 12 November (runs #93 to #98) | Green (runs #106 to #110). Phase 3 added a `compose` job; its first run (#110) passed |
| Eval gate in CI | None | Keyless and free: tool pins, harness self-check, harness gate (composite 0.964 against 0.85), release gate, tool use, eval package tests |
| Case API | `GET /health` and `GET /metrics/` only | Start a claim, stream the run, decide (approve, edit, reject), read a case, demo claims, `GET /me` |
| Approvals through the API | None | Bearer tokens per reviewer; the level and four-eyes checks are in the API; an edit voids every earlier approval |
| Agent tools | Imported in process; no MCP client; `langchain-mcp-adapters` unused | `CLAIMSENSE_TOOLS=mcp`: four MCP servers over stdio, pinned at the protocol, each with only its own settings |
| Calculator over MCP | No server | New `adjudication-calc` server that wraps the same calculator (no second calculator) |
| User interface | Empty package | Streamlit case UI (`python -m claimsense.ui`) and an operations dashboard |
| Docker Compose | `api`, `chroma`, `prometheus`, `grafana`. `.env` required; ports on every network interface; no healthchecks; the demo claims missing from the image; `.env` and the course keys sent to every build | Adds `ui`. `.env` optional; agents in stub mode unless `CLAIMSENSE_LLM=real`; ports on 127.0.0.1 only; healthchecks; demo claims in the image; `.dockerignore` keeps keys out |
| Settlement safety | A claim could be paid twice; an approval could be used for the other purpose | One final decision per claim; approvals signed for a purpose and spent only after the write commits |
| Model IDs | `config/models.yaml` and the code disagreed (AGT-09) | The code reads every agent role from `config/models.yaml` v2 |
| Product tests | 276 passed, 7 skipped (CI, before Phase 1) | 449 tests: 442 passed and 4 skipped in the last full run, plus 3 UI tests added and passing since |
| Ship check (stub) | Not run on these changes | REHEARSAL PASSED for Phase 2a, Phase 2b and Phase 3 |

---

## 3. Phase 1 (13 November, commit `4e46e8d`): CI green, settlement safety, model IDs

**Why.** CI had been red for days, so nobody could tell a real failure from lint noise. The
tool-use evaluation (`eval/agentic/`) had found settlement defects (AGENTIC-02 to -07).

| Change | Before | After |
|---|---|---|
| Lint | 113 `ruff check` errors and 3 unformatted files | Clean. Two prompts, a diagram and a pinned docstring kept their text, so no prompt and no tool pin changed |
| Eval gate | Not in CI | Job `eval-gate` after `test`, stub mode, free. `eval-real` runs the same gate with real models, manual only |
| One final decision | A claim could be settled twice, or repudiated after payment | `ClaimsDatabase._refuse_second_decision` refuses a second decision |
| Approval purpose | A settlement approval could repudiate, and the reverse | Approvals are signed for `SETTLE` or `REPUDIATE` |
| Spending approvals | Spent before the write committed | Spent only after the write commits |
| claims-db errors | The MCP wrappers raised exceptions to the agent | They return `ToolError(db_error)` |
| Model IDs | YAML and code named different models | `config/models.yaml` v2 names the models the agents run; `CLAIMSENSE_MODEL_<ROLE>` still overrides one role |

Result: the tool-use eval went from 12 open defects to 6. The CI and CD guide
(`docs/CI_CD_PIPELINE.md`) was written the same day.

---

## 4. Phase 2a (13 November, commit `2462975`): the case API

**Why.** The capstone needs FastAPI with streaming, and the L14 demo (an edit voids the old
approval) through a real interface. The graph could already do it; nothing exposed it.

**What a reviewer can do now** (`src/claimsense/api/README.md`):

| Route | What it does |
|---|---|
| `POST /claims` | Start a claim from a packet; stream the run to its first review |
| `GET /demo/claims`, `POST /demo/claims/{claim_id}` | List and start the synthetic dev and red-team claims |
| `GET /claims/{case_id}` | Status, plan, worksheet, pending review, approvals, settlement, letter, audit trail |
| `POST /claims/{case_id}/decision` | Approve, edit a line, or reject; stream the run to its next pause or its end |
| `GET /me` (Phase 3) | Who a token belongs to: approver id and level |
| `GET /health` | Now also says whether the agents are stubbed (`llm`) and which tools run (`tools`) |

**Streaming.** The start and decision routes answer with server-sent events: `plan`, `step`,
`worksheet`, `review`, `done`, `error`. Money is a string such as `"67067.10"`, never a float.

**Who decides.** Each reviewer has a token in `CLAIMSENSE_REVIEWERS`
(`<token>=<approver_id>:<adjudicator|senior>`). The approver's id and level come from the token,
never from the request body. The API refuses the wrong level (403), and refuses a senior approval
by the same person who approved as adjudicator (403, four eyes). A claim above the senior threshold
(`CLAIMSENSE_SENIOR_THRESHOLD_INR`; CLM-0019, above Rs 1,00,000, is the demo case) or with any fraud
flag needs both levels.

**Rule 4 (no health details).** Responses carry ids, amounts, clauses, flags and trace lines,
never the documents, the diagnosis or bill descriptions. The tests check this.

**Metrics** (`/metrics/`, same names as `eval/monitoring`, so its alert rules apply to live
traffic): claims processed by outcome, review decisions (edit rate), rupees deducted by reason,
fraud flags, turnaround, model cost, tool calls. No claim id or claim text is ever a label.

**State.** One SQLite checkpointer (`CLAIMSENSE_CHECKPOINTS`) keeps paused cases across restarts.
Reads go through a compiled graph, so LangGraph's strict checkpoint loading works; CI runs the API
tests that way.

---

## 5. Phase 2b (14 November, commit `2462975`, ADR-0012): agent tools over MCP

**Why.** The rubric (D2) noted that no code was an MCP client: the tool servers had MCP entry
points, but the agents imported them as Python modules.

| Change | Before | After |
|---|---|---|
| How agents reach tools | `real_services()` imports the server code | Also `CLAIMSENSE_TOOLS=mcp`: `agents/mcp_services.py` starts the four servers as their own processes over stdio, loads their tools with `langchain-mcp-adapters`, and gives the agents the same `Services` interface. The graph, agents and hooks did not change |
| Calculator | In process only | New `adjudication-calc` MCP server; it wraps `real_calculate`, so there is still one calculator |
| Tool pins | 8 in-process pins | Also 8 MCP pins (`<server>/<tool>` in `config/tool_pins.json`). The client refuses a server whose advertised tools differ |
| Settings each server sees | Everything in the environment | Only its own list (`SERVER_ENV`). No model key reaches a tool server; the approval secret goes to claims-db only |
| Tool errors | Not applicable | A `ToolError` comes back the way the in-process tool behaves (`None`, `[]`, or `PermissionError`) |

**Checked:** the calculator over MCP equals the in-process calculator on every dev claim, hash
included, so an approval survives the trip. A settlement over MCP needs the signed approval for
the exact worksheet and pays only once. With all four servers, CLM-0004, CLM-0001 and CLM-9001
reach the same first review as in process (opt-in test, about 2 minutes). Through the API in
`mcp` mode, CLM-0004 settled at Rs 67,067.10 with the same worksheet hash as in process.

---

## 6. Phase 3 (14 November, ADR-0015): case UI, Docker Compose, CI

**Why.** The capstone guide (pp. 9-10) puts a "case UI + FastAPI: upload packet, stream worksheet"
in front of the adjudicator and demos three scenes through it. L16 adds a dashboard, Docker
Compose and GitHub Actions. The brief allows Streamlit, Chainlit or Gradio. We chose **Streamlit**:
Chainlit is built for chat, Gradio for one-model demos, and the adjudicator works with tables,
forms and a two-level approval. Streamlit's AppTest also lets pytest click through the screens.

**The case UI** (`src/claimsense/ui/`, run with `python -m claimsense.ui`):

| Part | What it does |
|---|---|
| Sidebar | API status (version, stub or real agents, tools); sign in with a reviewer token; "Acting as" switch between signed-in reviewers |
| Start | Four scene buttons for the demo; any synthetic claim; upload a packet (documents as text or files, or a whole packet as JSON); open a case by id |
| Live run | The plan as it advances, each step's trace lines, the worksheet as soon as it exists |
| Case view | Status; fraud flags with their kind; admissibility, critic and escalation findings; the worksheet with each deduction's clause and the calculator's explanation; totals in Indian grouping (Rs 2,01,962.52); approvals, with those given on an earlier worksheet marked **void**; approve, edit one line, or reject; settlement and letter; audit trail |
| Dashboard | Claims processed, edit rate, rupees deducted by reason, fraud flags, mean turnaround, cost per claim, tool calls (since the API started) |

**The three demo scenes** (step by step in `src/claimsense/ui/README.md`):
1. CLM-0004: the room-rent cut and the proportional cut, explained line by line, then settled.
2. CLM-9001: the injected "pre-approved" note is flagged and changes nothing. CLM-0004 sent again
   (as case `CLM-0004-again`): the duplicate bill is caught from claim history.
3. CLM-0019: the adjudicator approves; a senior edits one line; the worksheet becomes v2 with a new
   total; the first approval is shown void; both levels approve again.

**Safety rules the UI keeps:**
- Every string from the API is shown as plain text or in a table, never as markdown. Fraud flags
  quote the claim's documents, so a document could otherwise inject a link or an image (rule 2).
  A test proves it.
- Tokens stay in the server-side session, are never shown, and the field clears after sign-in.
  The browser never holds a token: the UI process calls the API itself.
- The UI computes no amount. An edit sends a line, a clause or an amount, and a reason; the
  calculator recomputes the totals.
- It listens on 127.0.0.1 only and sends no usage statistics.

**Docker** (`Dockerfile`, `Dockerfile.ui`, `docker-compose.yml`, `.dockerignore`):

| Change | Before | After |
|---|---|---|
| UI image | None | `Dockerfile.ui`: core dependencies and Streamlit only (no agents, no data), healthcheck |
| API image | Demo routes failed (the demo claims were not in the image); no healthcheck | Copies the synthetic dev and red-team claims; healthcheck on `/health` |
| `.env` | Required: compose stopped without it | Optional |
| Model cost | A key in `.env` meant paid model calls | Stub agents unless `CLAIMSENSE_LLM=real` |
| Reviewers, checkpoints | Not set; checkpoints inside the container | `CLAIMSENSE_REVIEWERS` from `.env` or the shell; checkpoints on the `case-data` volume |
| Ports | Published on every network interface (Grafana with anonymous access) | Published on 127.0.0.1 only |
| Build context | The whole folder, `.env` and the course notebooks with real keys included | `.dockerignore` keeps keys, the held-out set, `runs/`, virtual environments and `.git/` out |

**CI** (`.github/workflows/ci.yml`): job `test` now installs `.[dev,agents,mcp,ui]` and runs the UI
tests. New job `compose` (after `test`) checks the compose file, builds both images, waits until
both are healthy, serves a demo claim through the API container, and calls the API from inside the
UI container. Its first run (#110) passed in 76 seconds: the first build of both images anywhere.

**API additions for the UI:** `GET /me` and the `llm` and `tools` fields on `/health`. The 403
message now reads "needs an adjudicator reviewer" (it said "a adjudicator").

---

## 7. How to run it

```powershell
pip install -e ".[dev,agents,mcp,ui]"     # or: pip install -r requirements.txt (everything)

# Terminal 1: the case API, stub agents (free, no key)
$env:CLAIMSENSE_LLM = "stub"
$env:CLAIMSENSE_REVIEWERS = "local-alice=alice:adjudicator,local-bob=bob:senior,local-alice-senior=alice:senior"
uvicorn claimsense.api.main:app --port 8000

# Terminal 2: the case UI, then open http://127.0.0.1:8501
python -m claimsense.ui

# Or both in Docker (put CLAIMSENSE_REVIEWERS in .env first)
docker compose up --build api ui

# Tests
pytest                                     # all product tests (stub mode)
pytest tests/ui tests/api                  # just the UI and the API
```

These tokens are for a local run only; anywhere else use long random values. To use real models
(costs money), leave out `CLAIMSENSE_LLM=stub` with your key loaded. For MCP tools, set
`CLAIMSENSE_TOOLS=mcp` (the servers start with the API; policy-kb takes about two minutes).

---

## 8. Problems found on the way, and what was done

| Problem | Effect | What was done |
|---|---|---|
| A fresh install picked fastmcp 4, which brings MCP SDK 2; pip then fell back to `langchain-mcp-adapters` 0.3.1, which fails on import | CI would have failed on every MCP test | `fastmcp<4` and `langchain-mcp-adapters>=0.3.2` in `pyproject.toml` and `requirements.txt` (ADR-0012) |
| `McpTools.start()` waited its whole 600 s timeout when a start failed early, and then hid the cause | A broken install looked like a hang | Failures now reach the caller at once; a test reproduces the case |
| The CLM-0022 removal (13 November) rewrote the dev gold and broke CLM-0021's worksheet | 34 product tests failed; CI runs #103 to #105 red | Reverted by the team (`9b82c5f`); CI green from run #106 |
| The held-out set was committed into the repository (13 November) | The repository is public, so the held-out claims and gold answers became visible | The team moved it to `data/claimsense-heldout/` (ADR-0013) and updated the deny rules; `.dockerignore` keeps it out of images. See section 11 |
| `.env` and the course notebooks went to the Docker daemon with every build | One careless `COPY . .` would put real keys in an image | `.dockerignore` |
| Two ADRs numbered 0013 | Confusing references | The UI decision is ADR-0015 |
| Stub runs had replaced the two real-model runs the reports quote (`runs/full/real-dev`, `runs/full/rr-release-1112c`), through copy-paste of documented commands | The files no longer matched the model card and the technical report | Restored from git. `eval.full` and `eval.agent_suite` now refuse a stub run whose label holds a real-model run |

---

## 9. How it was checked

| Check | Result |
|---|---|
| Product tests, full run on the current `main` plus Phase 3 | 442 passed, 4 skipped, 0 failed (then 3 more UI tests, passing) |
| UI tests (`tests/ui`, 43) | Pass: the three demo scenes, four eyes, repudiation, packet upload, dashboard, markdown in a flag shown as text, no token on any screen |
| Live smoke: API with uvicorn and UI with `python -m claimsense.ui`, real HTTP | Scene 1 streamed, the claim settled, the letter showed; the UI listened on 127.0.0.1 only |
| Fresh environment, installed as CI installs | Installs cleanly; `pip check` clean; strict-checkpoint API and UI tests 76 passed; `requirements.txt` resolves with Streamlit |
| UI alone, installed as `Dockerfile.ui` installs it | No agent packages installed; the page runs without error |
| Lint and format, tool pins | `ruff check` and `ruff format --check` clean (372 files); 8 in-process and 8 MCP pins match |
| CI on GitHub, Python 3.12 | Phase 2: green from run #106 (#105 failed on the broken dev gold, not on Phase 2). Phase 3: run #110 passed, `test` 110 s, `compose` 76 s, `eval-gate` 66 s |
| Ship check, stub mode | REHEARSAL PASSED for Phase 2a, Phase 2b and Phase 3 (`ss-1114-phase3`: all seven blocking stages passed; the security and retrieval reports passed; the two judges were skipped, as stub mode does) |
| Docker images | Built and checked by the `compose` CI job (run #110): both healthy, a demo claim served, the UI reached the API. Not built on the Windows machine used, which has no Docker |

---

## 10. What each role should look at

| Role | Please review or do |
|---|---|
| Deploy & Ops | `src/claimsense/api/`, `src/claimsense/ui/`, `docker-compose.yml`, both Dockerfiles, `.dockerignore`, `ci.yml` (ADR-0015). Next: adopt the edit-rate alert and the operations dashboard into `monitoring/` (ready and tested: `python -m eval.monitoring export`, steps in `eval/monitoring/README.md`); real sign-in instead of static tokens; image publishing |
| Tools & Security | `mcp_servers/adjudication_calc.py`, the MCP pins and `SERVER_ENV` (ADR-0012). Open: make `record_history` a claims-db write tool |
| Agents & Orchestration | `agents/mcp_services.py` (ADR-0012); the case API runs your graph unchanged |
| Eval & Red-Team | One real-model run through the API to record cost per claim; the held-out decision (section 11) |
| Domain & Product | A corrected CLM-0022 change, with its follow-ups: rebuild the red-team set, update the pinned suite rows and the counts in the reports |
| Everyone | Run the demo once from `src/claimsense/ui/README.md`. New rules are in `CLAUDE.md` (Case API, Tools over MCP, Case UI) |

---

## 11. Open items and limits

- **Held-out set.** It has been inside the public repository since 13 November (now
  `data/claimsense-heldout/`). Rule 5 still applies: nobody but Eval & Red-Team reads it, and it
  is run once with everything frozen. The final held-out score should state that the set was
  visible from that date.
- **Scoring.** `docs/FRAMEWORK_RUBRIC_SCORE.md` Issues 3 and 4 (14 November): **3.30 out of 5**
  (Issue 2: 2.85). Issue 3 scored D2 3 and D9 4 (the API serves claims, the agents speak MCP);
  Issue 4 scored D3 4 after the audit work below. D6 stays at 1 (cost measured, not limited) and D8
  at 4 (until the `mypy` owners' list is empty). The next team review should confirm both Issues.
- **Audit trail, tracing, type checking (added 14 November, after Phase 3).** Every API run has a
  run id (first stream event, every tool's audit record); `CLAIMSENSE_AUDIT_LOG` writes the trail
  as JSON lines (on in Docker Compose); `CLAIMSENSE_OTEL` traces each run, with the same redaction
  as the evaluation, now in `claimsense/tracing.py`. `mypy` runs in CI; six packages with 31 errors
  are on an owners' list in `pyproject.toml` (`docs/CI_CD_PIPELINE.md`).
- **Identity** is demo-grade: static tokens from the environment.
- **Shared database file.** Approvals and claim history are written straight to the claims
  database file, which the claims-db server also reads: one machine or one shared volume.
- **MCP over HTTP** between containers is not built; today the servers run inside the API
  container over stdio.
- **The API image has no policy index** (`data/` and `.[retrieval]` are not in it), so containers
  use stub tools.
- **fastmcp 4 is capped out** until `langchain-mcp-adapters` supports MCP SDK 2.
- **Dashboard history.** The UI dashboard counts since the API started. Grafana keeps history and
  raises the edit-rate alert once Deploy & Ops mounts the bundle from `python -m eval.monitoring
  export` (the alert passes its promtool unit test; the dashboard ran against a live API).

---

## 12. Where to read more

| Topic | Document |
|---|---|
| Case API: routes, events, settings, demo with curl | `src/claimsense/api/README.md` |
| Case UI: run, demo script, rules | `src/claimsense/ui/README.md` |
| Why MCP this way | `docs/adr/0012-agent-tools-over-mcp.md` |
| Why Streamlit, and the Docker and CI changes | `docs/adr/0015-case-ui-streamlit.md` |
| CI jobs, red builds, local commands | `docs/CI_CD_PIPELINE.md` |
| Every check at once | `docs/SHIP_CHECK.md` |
| Project rules for people and for Claude | `CLAUDE.md` |
