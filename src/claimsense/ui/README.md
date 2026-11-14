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
uvicorn claimsense.api.main:app --port 8000
# 2. the UI, in a second terminal
python -m claimsense.ui      # open http://127.0.0.1:8501
```

`CLAIMSENSE_API_URL` points the UI at another API (default `http://127.0.0.1:8000`). Arguments
after `python -m claimsense.ui` go to `streamlit run` and win over the defaults, for example
`--server.port 8600`.

With Docker: `docker compose up --build api ui` starts both (the agents stay in stub mode unless
`CLAIMSENSE_LLM=real` is set); put `CLAIMSENSE_REVIEWERS` in `.env` first.

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
