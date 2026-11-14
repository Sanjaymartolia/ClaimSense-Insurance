# Case UI (Deploy & Ops, L16)

The claims adjudicator's screen: start or upload a claim, watch the run stream, approve, edit a
line or reject, read the letter, and an operations dashboard. It is a Streamlit client of the case
API (`src/claimsense/api/README.md`) and nothing else: no direct access to the graph, the tools or
any database. Why Streamlit: `docs/adr/0015-case-ui-streamlit.md`.

Files: `app.py` (the screens), `client.py` (API calls and stream parsing), `views.py` (what the
screens show, as plain functions), `__main__.py` (the launcher). Tests: `tests/ui/`.

## Run it

Two terminals, from the repository root (PowerShell shown; Git Bash: `export NAME=value`):

```powershell
pip install -e ".[agents,ui]"
# 1. the case API (stub agents: free and deterministic)
$env:CLAIMSENSE_LLM = "stub"
$env:CLAIMSENSE_REVIEWERS = "local-alice=alice:adjudicator,local-bob=bob:senior,local-alice-senior=alice:senior"
$env:CLAIMSENSE_CHECKPOINTS = "claimsense_checkpoints.sqlite"
uvicorn claimsense.api.main:app --port 8000
# 2. the UI, in a second terminal
python -m claimsense.ui      # open http://127.0.0.1:8501
```

`CLAIMSENSE_API_URL` points the UI at another API (default `http://127.0.0.1:8000`). Arguments
after `python -m claimsense.ui` go to `streamlit run` and win over the defaults, for example
`--server.port 8600`.

### Real models (they cost money)

The same two terminals; only the API's settings change. A claim costs about $0.0013 with the
current models (`docs/MODEL_CARD.md`).

```powershell
# 1. the case API with real models
$env:CLAIMSENSE_LLM = "real"
$env:CLAIMSENSE_REVIEWERS = "local-alice=alice:adjudicator,local-bob=bob:senior,local-alice-senior=alice:senior"
$env:CLAIMSENSE_CHECKPOINTS = "claimsense_checkpoints_real.sqlite"   # real cases apart from stub ones
[bool]$env:OPENROUTER_API_KEY      # must print True (it prints True or False, never the key)
uvicorn claimsense.api.main:app --port 8000
# 2. the UI, in a second terminal, as above
python -m claimsense.ui
```

- **The key.** A terminal opened inside VS Code usually has `OPENROUTER_API_KEY` already: VS Code
  loads `.env` into its terminals. If the check prints `False`, load the key from `.env` without
  printing it, then start the API:

  ```powershell
  $line = Select-String -Path .env -Pattern '^\s*OPENROUTER_API_KEY\s*=' | Select-Object -First 1
  $env:OPENROUTER_API_KEY = ($line.Line -split '=', 2)[1].Trim().Trim('"')
  ```

  Without a key the API still starts and reports `agents: real`, but the first claim fails at its
  first model call.
- **A checkpoints file per mode.** The API keeps each case under its case id. Without a second
  file, a scene already run in stub mode (CLM-0004, say) is refused in real mode: "the case exists
  already". `:memory:` keeps no case at all.
- **Switch modes:** Ctrl+C in the API terminal, run the other block, refresh the browser; the UI
  keeps running. The caption under the page title shows the mode (`agents: stub` or
  `agents: real`), and so does `Invoke-RestMethod http://127.0.0.1:8000/health`.
- **Real tools as well (optional).** The blocks above use the stub tools, which read each demo
  claim's built-in policy data. For the tool servers' own code, run once
  `python -m claimsense.mcp_servers.seed_dev_policies` and `python -m claimsense.retrieval.index`
  (needs `.[retrieval]`), then also set `$env:CLAIMSENSE_TOOLS = "real"` and
  `$env:CLAIMSENSE_APPROVAL_SECRET` to a long random string (`src/claimsense/api/README.md`).

### Docker

Docker is optional: the two terminals above run the same API and UI, and CI's `compose` job builds
and tests both images on every push. It needs Docker Desktop: `docker --version` must work. To
install it: `winget install -e --id Docker.DockerDesktop`, start Docker Desktop once (it may ask
for WSL 2 and a restart), then open a new terminal.

Run **one** of the two blocks. `docker compose up` keeps running until Ctrl+C.

```powershell
# stub agents (free)
$env:CLAIMSENSE_LLM = "stub"
$env:CLAIMSENSE_REVIEWERS = "local-alice=alice:adjudicator,local-bob=bob:senior,local-alice-senior=alice:senior"
docker compose up --build api ui
```

```powershell
# real models (paid): the key reaches the API container from .env
$env:CLAIMSENSE_LLM = "real"
$env:CLAIMSENSE_REVIEWERS = "local-alice=alice:adjudicator,local-bob=bob:senior,local-alice-senior=alice:senior"
docker compose up --build api ui
```

Without `CLAIMSENSE_REVIEWERS`, compose uses these same local demo tokens, so `docker compose up
--build` alone starts everything (the repository README). `$env:CLAIMSENSE_LLM` stays set in that terminal
until you change it or close the terminal, and other commands there read it too. Docker keeps
cases in its `case-data` volume between runs, so the case-id clash above applies here too. To
clear only the cases: `docker compose down`, then `docker volume ls`, and `docker volume rm` the
volume whose name ends in `_case-data`.

## The demo, step by step

Sign in twice in the sidebar, once with `local-alice` (adjudicator) and once with `local-bob`
(senior); "Acting as" switches between them. The scene buttons are under "Start or open a claim".
The tokens above are for a local run only: anywhere else use long random values.

1. **Room rent above the cap (CLM-0004).** Point at the worksheet: L02 and L03 are cut to the
   room-rent cap (clause 12.1, Rs 5,000 a day), and L01 and L05 take the proportional cut with
   the same factor (clause 4.1.1). "How each deduction was computed" gives the calculator's own
   explanation for every line; the 5% co-pay comes last. Approve: the claim settles and the
   letter names a reason for each deduction.
2. **Injected note (CLM-9001).** The flag "possible prompt injection" names the document; the
   worksheet is the normal one, so the note changed nothing. Then **the same bill again**
   (CLM-0004 under case `CLM-0004-again`, after scene 1 settled): the duplicate flags name the
   earlier claim and its lines.
3. **An edit voids the approval (CLM-0019, above Rs 1,00,000).** As alice, approve: the review
   now needs a senior. As bob, edit line CLM-0019-L04 to Rs 6,000 with a reason. The worksheet
   becomes v2 with a new hash and a new total, alice's approval shows **void**, and the audit
   trail says "earlier approvals void". Approve as bob now: the API refuses (the review needs an
   adjudicator). Approve as alice, then as bob: settled. For the four-eyes rule, also sign in
   `local-alice-senior`: on a fresh CLM-0019 case, alice approves as adjudicator and then cannot
   approve again as senior.

Every pending review shows **Approve · Edit a line · Reject** side by side, each with a line on
what it does. On a claim ruled not admissible (for example CLM-0001 from "Start a claim"), approve
means repudiate, and an edit **overrides the not-admissible finding**: give one line a clause id
(for example `new_india_arogya_sanjeevani:4.1`, hospitalisation) or a corrected amount, and a
reason. Coverage, the fraud screen and the calculator run again, and the claim comes back for
review with a worksheet.

The dashboard page shows claims processed, the edit rate, rupees deducted by reason, fraud flags,
turnaround and cost per claim, counted since the API started. Grafana keeps history and alerts
(Phase 4).

## Rules it keeps

- Every string from the API is shown as plain text or in a table, never as markdown: fraud flags
  quote the claim's documents (rule 2). `tests/ui/test_app.py` checks a flag written as markdown.
- Reviewer tokens stay in the session, go only to the API, and are never shown; the token field
  clears after each sign-in. The browser never holds a token: Streamlit calls the API itself.
- The page computes no amount; edits send a line, a clause or an amount, and a reason, never a
  total. Uploaded documents stay in the session's memory and are not logged.
- It listens on 127.0.0.1 and sends no usage statistics (`__main__.py`, `.streamlit/config.toml`).

## Limits

- Identity is the API's: static demo tokens. Approvals seen on an earlier worksheet are marked
  void from what this session saw; after a page reload, the audit trail still says it.
- "Upload a packet" with stub agents needs the extracted claim as JSON (or a whole packet JSON):
  stub agents read no documents. Real models read the documents and cost money.
