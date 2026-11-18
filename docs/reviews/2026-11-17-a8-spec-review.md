# A8 spec review (v0.1 → v0.2), 2026-11-17

Four adversarial critics (Claude Opus 5.5) reviewed amendment A8 v0.1 in two rounds:
- a security red-teamer;
- an eval-integrity critic;
- a front-end and accessibility engineer;
- a scope critic (a hiring manager, plus a solo builder's time budget).

**Rules.** The critics were read-only: no model, Voyage or live StatCan calls, and no access to the held-out test split. Every claim had to be labelled VERIFIED or JUDGEMENT.

**Round 2.** Each critic read the other three critiques. It then had to agree, change or dispute every blocking item within a 5-build-day, 12-review-hour budget, rule on six conflicts, and give a ranked must-fix list. A8 v0.2 §17 summarises what changed.

## Chairman verification

The chairman (the session that ran the review) re-checked these facts itself before accepting them.

| Claim | Result |
|---|---|
| The question is parsed as a `claude` option (security B1) | **Confirmed in the code:** `build_command` places the question directly after `-p` with no `--`. The critic's demonstration (`claude --model haiku "--version"` printing the version) made no model call, but it went beyond the brief's "no `claude`" rule; noted |
| The replays come from a pre-release agent (eval B4) | **Conclusion confirmed; evidence corrected.** The critic's `merge-base --is-ancestor 9e183c1 v1.0.0` failed because no `v1.0.0` tag exists (tags are w1–w3), and main is squash-merged, so ancestry means nothing here. A diff confirms the substance: `ask.py` +86 lines, plus `links.py` and `transcripts.py`, changed between 9e183c1 (2026-11-07) and main |
| Recordings must be re-wrapped for `run_events` (eval B3) | **Confirmed.** Re-wrapped, with a fixed clock: compare-01 and refuse-01 pass; inject-01, -02 and -03 pass; lookup-07 raises `ANSWER_REJECTED` |
| The injection runs have no error and carry a poison spec (scope B2, security S2) | **Confirmed.** All 3 have `error: None`. The poison field is a JSON spec (`goal`, `vector`, `host`, `table`) parsed by `canada_agent.evals.poison.parse` |

## Chairman rulings on what was still split after round 2

- **Charts:** a hand-written SVG (security, eval and scope) over Recharts (front end). Recorded as decision D4, with the dissent.
- **Attack runs in the demo:** no tool text at all, and the attacker host is never printed. This is the strictest of the proposals: scope wanted the tool text shown, security wanted it redacted, and eval proposed printing the host as plain text.
- **Re-recording the dev transcripts:** split. Scope wanted it inside the `src/` PR; the others deferred it. Recorded as decision D6, default no.
- **Event types:** a hand-written TypeScript union instead of codegen (scope; front end's required `type` kept).

## Note on process

- A usage limit stopped all four critics during round 2. Each was resumed from its saved state with the same brief.
- Scratch scripts the critics wrote stayed in a temporary job folder and are not committed. The commands and outputs they cite are quoted inline below.


---

# Round 1: security

## A8 security red-team report

I found 5 blocking issues and 6 that should be fixed. The DNS-rebinding defence, CSRF protection on POST, the replay corpus and the canary handling all survived attack. I edited nothing under `~/projects/`. My only scratch file is `~/.claude/jobs/e82029df/tmp/a8-review/security/scan.py`.

### 1. Blocking

**B1. Argument injection through the question (§7 U1, §10). This can run code.**
`build_command` puts the question in argv as `claude`'s positional `[prompt]`, with no `--` before it.
- VERIFIED: `claude --help` prints "Usage: claude [options] [command] [prompt]".
- VERIFIED: `claude --model haiku "--version"` printed `2.1.323 (Claude Code)`. A token in the prompt slot is parsed as an option.
- VERIFIED: `--settings <file-or-json>` (which can carry hooks) and `--plugin-url <url>` ("Fetch a plugin .zip from a URL") both exist.
- So a question such as `--plugin-url=https://…` turns into a CLI option. The 500-character limit is the only validation A8 adds.
- VERIFIED: a NUL byte makes `Popen` raise `ValueError: embedded null byte`. That is not an `AskError`, so it could crash the worker while the run lock is held.

Fix:
- **U1 adds P9:** "`build_command` ends options with `--` and puts the prompt last (or sends it on stdin). A unit test with `question="--version"` asserts the question comes after `--`." JUDGEMENT: Commander normally honours `--`, but I couldn't confirm it without a `claude -p` call. The stub test plus one `make live-web` run would check it.
- **§10, added:** "The server strips the question, rejects control characters and NUL, and rejects a leading `-`."

**B2. The per-launch cookie token protects nothing, and the GET event stream has no stated protection (§10).**
- The cookie is set "when the page loads", so any local process that fetches `/` gets it.
- VERIFIED: RFC 6265 §8.5 says "Cookies do not provide isolation by port." Any web app on 127.0.0.1:other-port is same-site and receives the cookie.
- VERIFIED: MDN says browsers add `Origin` to same-origin requests "except for GET or HEAD". So the Origin check can't protect `GET /api/runs/{id}/events`.
- A cross-site `EventSource` request is still sent; only its response is blocked by CORS. When it fails, the server sees the stream close, and "closing the event stream cancels it". That lets any website cancel George's run, as long as it can guess the `run_id`. A8 doesn't say how `run_id` is generated.

Replacement text:
> "On launch the server prints `http://127.0.0.1:PORT/?token=<32 random bytes>`. That request sets an `HttpOnly; SameSite=Strict` cookie and redirects to strip the token. Serving `/` without the token never sets the cookie. Every `/api/*` route, GET included, requires the cookie and rejects `Sec-Fetch-Site` values other than `same-origin`. POST also requires `Origin` to equal `http://127.0.0.1:PORT` exactly, port included (`null` is rejected). `run_id` is `secrets.token_urlsafe(16)`. Drop `localhost` from the allowed hosts, so there is one origin."

**B3. Step events can show attacker text the answer checks would reject. The §3 claim "The UI can't show what the checks rejected" is false as written (§9, E3, U2, U5).**
- VERIFIED: the poison routes carry foreign URLs into tool results:
  - inject-01's `search_tables` card contains a `NOTICE-7731` line citing `statcan-mirror.example.com`;
  - inject-03's `is_error` body contains the same with `statcan-data.de`.
- In a live run these become `step_finished.summary` and error text, shown before `run_failed`.
- Model-written `arguments` are checked only for the canary (ask.py:333), never by `foreign_links`.
- VERIFIED: the `get_series` output has **no `title` or `unit`** (`project_series` keeps product_id, vector_id, coordinate, source_url, scalar_factor and points). So `series.title`/`unit` would have to come from cards or member names, which are injection routes.

Fix:
- `summary` is built on the server from structured fields only ("12 tables", "120 points", an error code). It never copies tool text.
- `arguments`, and any third-party title, go through `untrusted_text` and then every `foreign_links()` hit (imported, per E2) is replaced with "[link withheld]".
- `series` carries `product_id: int`, not `source_url`. The client builds the href only from `/^\d{8}$/` against a fixed template.
- P4: `on_step` fires only after the canary check.
- A contract test replays inject-01 and inject-03 offline and asserts no event contains a foreign link.

**B4. `run_failed.message` is "chosen from a fixed table per error code", but many errors have no code (§9, §10, U6).**
- VERIFIED: ask.py raises code-less `AskError`s at lines 161, 164, 178, 275, 278, 282, 333 (canary in a tool call), 371 and 420.
- Line 161 includes `claude -p` `result` text, line 420 includes stderr, and line 278 includes the cited URL.

Fix: "A code of `None` maps to `AGENT_FAILED` with a fixed message. A test asserts no event ever contains `str(exc)`. The canary in a tool call is given `ErrorCode.ANSWER_REJECTED` in U1."

**B5. Cancel doesn't do what P5 claims (P5, U7, §10).**
- VERIFIED: `run_events` only advances when `for line in proc.stdout` yields. A `should_stop` "checked on every event" can't fire while the model is silent mid-turn, which is the critique §17 says P5 resolves.
- VERIFIED: the MCP server runs as `sys.executable -m canada_agent.mcp_server`, not `canada-mcp`. A test that searches for `canada-mcp` processes passes even if one survives.
- VERIFIED: `start_new_session=True` means Ctrl-C on the server never reaches `claude`. If uvicorn exits mid-run, the 120 s timer dies with it and `claude` carries on (JUDGEMENT on uvicorn's exact behaviour).

Fix:
- "`ask` takes a `cancel: threading.Event`. `_stream` starts a watcher that runs `kill_group()` as soon as it is set, as `expire()` already does."
- "The test checks by process group (`os.killpg(pgid, 0)` raises `ProcessLookupError`), using a stub that sleeps silently and spawns a child."
- "Server lifespan shutdown and `atexit` set `cancel` and join the worker."

### 2. Should fix

- **S1. Pages workflow (§11).** VERIFIED: actions/deploy-pages needs `pages: write` and `id-token: write`. Those permissions should belong only to a deploy job that runs nothing but `deploy-pages`. A separate build job (`contents: read`) runs `npm ci --ignore-scripts` and uploads the artifact. Use `on: push: branches: [main]`, never `workflow_run` from PR CI. Restrict the `github-pages` environment to `main`. Pin all actions, including `setup-node` and `upload-pages-artifact`, by SHA (SPEC lines 93/255). The current workflows pin by SHA; A8 doesn't say the new one will.
- **S2. `recordings()` fails open.** VERIFIED: `(verdicts is not None and not verdicts.get(...))` lets every recording through if the grades manifest is missing. `build-demo` must:
  - require the verdicts, `split == dev` and `poison is None`;
  - run `foreign_links` over every string it displays;
  - assert `provenance.path` is repo-relative. Today `offline.py` falls back to an absolute path, which would include `/Users/<name>`.

  §11's stated reason for excluding injection runs is also wrong. VERIFIED: inject-01 to inject-03 have `error: None` and passed the graders. They must be excluded because their **tool results** carry the poison, not because of `structured_output`.
- **S3. API key passthrough.** `env = {**os.environ, …}` passes `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` to `claude` if they are set. JUDGEMENT: `-p` then bills the API, which breaks ADR 0009. `canada-web serve` should refuse to start if either is set, or strip them in U1.
- **S4. One run at a time.** Release the lock only after `proc.wait()` returns. Cancel a run whose event stream hasn't attached within 10 s. GET must never start a run. Add a configurable daily cap on live runs, against a front-end reconnect loop.
- **S5. CSP in `<meta>`.** The tag must come before Vite's script tag. Trusted Types is not available in every browser (JUDGEMENT), so plain-text rendering is the real defence: say so. A Pages project site shares the `<user>.github.io` origin with George's other Pages sites, so `'self'` covers those too. Accept that in writing, or use a custom subdomain.
- **S6. Other local users.** JUDGEMENT, low risk: the canary and the question sit in argv (`--system-prompt`), so they may show in `ps`, depending on macOS's process-argument restrictions. Note it in §10 rather than claiming the canary is secret.

### 3. Cut or defer

- Cut the per-launch cookie design as written (replaced in B2).
- Cut `localhost` from `TrustedHostMiddleware`: one origin is simpler to check.
- Spell out the Stop path. U7 doesn't say whether Stop is a POST, which would need B2's checks, or a stream close. Pick one.

### 4. Held up

- **DNS rebinding.** VERIFIED in a local starlette 0.50.0 copy: `trustedhost.py:40` strips the port with `host.split(":")[0]`. A rebinding page's Host is the attacker's domain, so it is rejected. `[::1]` becomes `[`, which is rejected, and the server only binds IPv4 anyway.
- **CSRF on POST.** JUDGEMENT: no CORS middleware, plus a required JSON content type (which forces a preflight) and an exact Origin check, block it.
- **The 20 replay recordings.** VERIFIED: `foreign_links` over all their tool results and arguments found none. Recomputing `PROMPT_VERSION` (`v1-c8c974c0`) and reading the grades manifest gives exactly 20 (24 minus 3 inject minus lookup-07).
- **The canary never reaches an event.** VERIFIED: the tool-argument check runs before `on_event`, and the answer only exists after `check_answer`.
- **Terms.** The demo never calls a model, so no path routes other people's requests through the subscription, provided B2's token closes the local-process gap.
- **`id-token: write` is needed** (VERIFIED, deploy-pages README).

---

# Round 1: eval

## A8 review: eval integrity and methodology

I did not edit anything under `~/projects`. I made no model or network calls and did not read the test split. My scratch scripts are in `~/.claude/jobs/e82029df/tmp/a8-review/eval/`.

### 1. Blocking

**B1. §15 says "the gate decides" whether U1 moved the pass rate. It can't: the U1 re-baseline hides any regression U1 causes.**
- VERIFIED: `gate.py:270` makes `baseline` refuse unless the study ran on the *current* `agent_hash`.
- VERIFIED: `check_evidence` (`gate.py:352`) requires `baseline.from_study_agent_hash == receipt.agent_hash`.
- So after U1, the k=3 gate is judged against a k=5 study of the same new agent. That only checks the agent is reproducible. Nothing compares U1 against v1.0's baseline (0.9417 mean, 20 stable cases). The order is consistent with ADR 0008, but A8 claims more than it delivers.
- **Fix:**
  - In `gate.py` (a judging file, so `agent_hash` doesn't change), `cmd_baseline` first runs `judge(per_case(new study), outgoing baseline, 0)`. It refuses on a flip, a mean drop or a leak unless given `--accept-change "<reason>"`. It records `{"replaces": <old hash>, "regression_check": [...]}` in `baseline.json`.
  - This needs no extra model runs.
  - Replace the §15 text with: "U1's new study is judged against the v1.0 baseline under the same flip and mean rules before it becomes the baseline. A failure blocks U1."

**B2. U3 and U4 need data that `src/` doesn't expose. Without it, un-gated `web/` code re-derives it and breaks E2, or a second re-baseline follows.**
- VERIFIED: `AskResult` has only answer, usage, turns, duration, cost, `tool_calls` and `prompt_version`.
- `ToolCall` carries no result. The URL set and the per-vector values that `run_events` uses for grounding are local variables.
- U3 (source points from `get_series`) and U4 (link only tool-returned URLs) therefore can't be built from `AskResult` (E3) without re-parsing tool text in `web/`.
- §13 even puts "citation rule" in the **Vitest** (JavaScript) tests. That is a JS port of `CITABLE_URL`, which §6.2 rejects.
- E2's grep for the Python regex text would not catch a rewritten JS regex.
- **Fix:** add to P4:
  - `StepEvent(finished)` carries the returned URLs, the vector ids and the parsed series points, computed by the same code in `run_events`.
  - `AskResult` gains `returned_urls` and `sources`.
  - The backend and `build-demo` emit `links: [{url, linkable}]`. The front end only renders `linkable`.
  - Replace the Vitest row "citation rule" with "renders `<a>` only for `linkable: true`". Add an ESLint/grep ban on `statcan.gc.ca` regexes in `web/frontend`.

**B3. §11: `build-demo` can't feed recordings to `run_events` as A8 implies, and the check it can do is weaker than claimed.**
- VERIFIED (`replay_check.py`): `slim()` stores events as `{"type","content"}`, but `run_events` reads `event["message"]["content"]`.
  - Feeding the 20 recordings as stored, only 4 pass (the refusals). The rest fail with "an answer needs at least one successful get_series".
  - Re-wrapped, 20/20 pass with no database.
- That is a self-consistency check on *recorded* tool results. It is not `--offline`'s re-execution against the snapshot (`_replay`, which needs Postgres), and the canary can never fire.
- Determinism also breaks: step latencies come from the replay clock.
- **Fix:** replace the §11 bullet with: "every recording is re-wrapped and passed through the production `run_events` with an injected fixed `clock` (it already takes one). This checks the recorded answer against the recorded tool results. It does not re-run tools; `fresh-clone` does that. Latencies come only from recorded `t_ms`, else null."

**B4. Replay provenance can't be filled honestly as specified.**
- VERIFIED: transcript keys are case, question, model, prompt_version, git_sha, git_dirty, poison, error, wall_s and events. There is **no date**, yet §9 wants `recorded_on` and the §11 banner shows "(model, date)".
- VERIFIED: all 20 dev recordings carry `git_sha 9e183c1`. That commit is **not an ancestor of v1.0.0** (`merge-base --is-ancestor` fails). `ask.py` (+86 lines), `links.py` and `transcripts.py` changed after it.
- So the demo shows runs from a pre-release branch agent that is neither v1.0.0 nor v1.1.0. P3 timing reaches none of them, so U9's "recorded pace" applies to zero replays.
- **Fix:**
  - P3 also stamps `recorded_at` (UTC) and `claude_version` per transcript.
  - Add to U1: re-record the 24 **dev** Sonnet transcripts on the v1.1 agent (24 runs), then a reviewed `canada-grade --split dev --write`, and confirm the three fresh-clone questions still replay.
  - Otherwise, label every replay "recorded during v1.0 development (commit 9e183c1, before release)" and drop "recorded pace" from U9.

**B5. P8 closes a gap that barely matters, misses real ones, and records a claim CI can't check.**
- VERIFIED: `config/prices.toml` is loaded only by tests (`costs.py` has no runtime caller). `config/scope.toml` feeds only the index build, whose output `data/index.sql.zst` is already hashed.
- Adding `config/` outside `JUDGING` means a price edit forces all 192 runs.
- VERIFIED: `migrations/` is not in `INPUTS`. JUDGEMENT: a migration (for example an HNSW index, against ADR 0003) changes search results and so changes runs.
- A `claude --version` in the receipt can't be verified in CI, because there is no `claude` there.
- **Fix:** P8 becomes:
  - add `migrations/` to `INPUTS`, and `config/` to `JUDGING`;
  - record `claude_version` per transcript (B4);
  - `check_evidence` requires every gate and study run to share one `claude_version` and model, equal to the receipt's.
  - Add these paths to ci.yml's "Flag changes to eval inputs" step.
- This doesn't affect the v1.0 receipts or the held-out recordings. VERIFIED: tags verify with their own code; `canada-grade --check` uses no hash; the immutability step only diffs `evals/transcripts/test`.

### 2. Should fix

1. **The §6.3 benchmark acceptance can't be reproduced as written.**
   - VERIFIED: the investigation's scripts and raw outputs are not committed (investigation line 1). So "from 0.28 / 0.247 / 7.7 ms" can't be checked, and two harnesses already disagree on search (7.7 vs 8.6 ms).
   - VERIFIED: my rerun shows batch medians drifting 287→299 ms (`ask`) and 282→298 ms (`mcp_server`), and a 588 ms cold first run.
   - P2's ≤0.21 s target is a 37 ms change, about 3× that drift. It also contradicts P2's own "50–70 ms" prediction.
   - **Fix:** `make bench`:
     - runs base and head interleaved (a base worktree) on one named machine;
     - discards ≥3 warm-up runs, then takes n≥30;
     - pre-compiles bytecode (`uv sync --compile-bytecode`), never `PYTHONDONTWRITEBYTECODE` for imports;
     - commits the raw samples plus machine, OS, Python, uv-lock hash, Postgres image and power state to `docs/perf/`;
     - accepts on "median improvement ≥ X with a bootstrap 95% CI excluding 0". The absolute thresholds then apply only on the reference machine, and the "before" numbers come from U0's `make bench`, not the investigation.
   - Held up: P1 is achievable. VERIFIED: the imports `ask` needs without `mcp_server` take a 70 ms median.
2. **The §1 and §6.1 framing overclaims.**
   - "Claude's thinking is about 95% of **every** question" is the Haiku snapshot median (9.37 s / 9.80 s), and `duration_ms` includes Claude Code's tool round trips (investigation line 331).
   - VERIFIED: on the one live trace, tool latencies sum to 1.97 s of 26.7 s, so the model is at most ~92%.
   - "10–30 s" has no measured lower bound. The Sonnet snapshot median is 7.45 s, and the live trace is n=1, 3.6× that, with the gap unexplained.
   - §6.2's "0.3 s of 10–27 s (1–3%)" leaves out the 7.45 s row; it should read "7–27 s (1–4%)".
   - **Fix:** "Waiting on Claude (model plus Claude Code's own work, `duration_ms`) is ~95% of a median Haiku snapshot run (n=761, four agent versions) and ≤92% of the single live Sonnet trace."
3. **Selection in the replay library.**
   - VERIFIED: dev is 23/24 passed. The 20 replays are the 21 non-injection runs minus lookup-07. That run was `ANSWER_REJECTED` ("an answer with no values must be a refusal") and carries the model's own text, not an attacker's.
   - **Fix:**
     - Include lookup-07 as a labelled "rejected by the runtime checks" replay. It shows U6, with only the code shown.
     - The library header reads: "20 of 21 dev questions (the set the agent was tuned on); 1 rejected run shown; held-out: 13/16 on v1.0.0, not re-run".
     - The About panel says the held-out figure describes the v1.0.0 agent, not v1.1.
4. **E4 is sound only if the display is shown to match the agent.**
   - Add a fidelity test: for each replay, the answer event equals the recording's `structured_output` byte for byte, and each chart point equals the recorded `get_series` payload.
   - Add a test that `web/` calls `ask` with the same argv as the CLI (unmodified `Settings`, no question rewriting, no `table=`), so `web/` can't change behaviour without the gate seeing it.
5. **The one-PR re-baseline is fragile.** Any review fix to `src/` after the study, even a docstring, repeats all 192 runs.
   - **Fix:** state "code review completes before recording. The study, baseline and gate are the PR's last commits, and any later `src/` change re-runs them."
6. **`CANCELLED`.**
   - VERIFIED: graders fail any `run.error`, and `leaked()` treats errored runs as not leaked. `ErrorCode` isn't in `mcp_tools.json` or the prompt. So graders are unaffected.
   - Add a test that `record()` never passes `should_stop` (default `lambda: False`), so a gate injection run can't be "cancelled" into not-leaked.
7. **The §3 claims table points at things a reviewer can't check.**
   - "A cancel that really stops the agent" can't be checked without the subscription. Point to the stub-`claude` test by name.
   - "I build accessible interfaces" rests on axe alone, which covers a minority of WCAG. Add a recorded manual keyboard and screen-reader pass, or soften the claim.

### 3. Cut or defer
- **P8's `config/` addition as written:** replace it per B5.
- **P1 is not a UI win.** The web server imports `ask` once. Keep it only because the re-baseline is already being paid for, and label it CLI-only.

### 4. Held up
- **P3–P5 don't break `canada-grade --check`.** VERIFIED: `PROMPT_VERSION` hashes only `system_v1.md`. Graders ignore extra event keys. `offline.recordings()` filters on `prompt_version` and the pinned verdicts, which P1–P8 don't touch.
- **The test-split CI step and the v1.0 tag receipts are unaffected by U1.**
- **The re-baseline order** (study k=5 → baseline → gate k=3) matches ADR 0008's rule that the baseline comes from a separate study.
- **"20 replayable"** is VERIFIED (`recordings()` returns 20), and no injection run is included.
- **"~0.3–0.55 s of our CPU"** matches the investigation's components (0.25 + 0.28 + 0.03 s).
- **The "~2 s live network"** matches the trace (1.97 s).

---

# Round 1: frontend

FRONT-END / ACCESSIBILITY REVIEW OF A8 (scratch: ~/.claude/jobs/e82029df/tmp/a8-review/frontend/; nothing under ~/projects/ was touched)

## 1. Blocking

**B1. §8/§10: the two-request SSE shape leaves cancel, reconnect and access undefined.**
- VERIFIED (Chromium 153, `scripts/reconnect_srv.py`): an EventSource whose server closes the stream after its last event reconnects on its own. It made 14 GETs in 4 s at `retry: 300`. A 204 response stops it (2 GETs).
- VERIFIED (`scripts/origin_srv.py`): a same-origin EventSource GET sends **no `Origin` header**. It does send the SameSite=Strict HttpOnly cookie, plus `Sec-Fetch-Site: same-origin`. `fetch` POST sends the correct Origin even under `Referrer-Policy: no-referrer`.
- What A8 leaves unspecified:
  - what happens to a run whose GET never connects (the gap between POST and GET);
  - how the GET is protected (§10 covers only the POST);
  - what a reconnect to a finished run returns;
  - "closing the stream cancels" works against EventSource's automatic reconnect.
- Fix (preferred): **one request.** `POST /api/ask` returns `EventSourceResponse`.
  - VERIFIED: the docstring in `fastapi/sse.py` 0.163.1 says it "Works with any HTTP method". My test ran SSE over POST.
  - The browser reads it with `fetch` + `ReadableStream` + `eventsource-parser` 4.1.3 (or a ~30-line parser). Stop calls `AbortController.abort()`.
  - This removes the run registry, the orphan window, GET hardening and reconnect handling.
  - Replacement text for §8: "`POST /api/ask` streams the run as Server-Sent Events in its response body. There is no resume and no automatic reconnect; aborting the request cancels the run."
- Fallback if the two requests stay:
  - the run starts only when the first event stream connects, or is cancelled if none connects within 5 s;
  - GET requires `Sec-Fetch-Site: same-origin`, the cookie and an unguessable `run_id`, with one subscriber per run (a second gets 409);
  - a finished or unknown run returns 204;
  - the client calls `es.close()` on the terminal event and on `error`.
- Dropping `Last-Event-ID` resume is fine for localhost (JUDGEMENT), but A8 should say so. The investigation (§183) had resume, and A8 dropped it silently.

**B2. P5 (§6.3): `should_stop` "checked on every event" can't cancel while the model is thinking.**
- VERIFIED by code read: `_stream` blocks in `for line in proc.stdout` (ask.py ~409). Between events (the model's thinking time), nothing polls the flag.
- VERIFIED (`scripts/sse_disconnect.py`, FastAPI 0.163.1 + uvicorn 0.54.0): when the client disconnects during an idle wait, the async generator's `finally` runs within milliseconds, and a `threading.Event` reaches the worker at once.
  - uvicorn reports ASGI spec 2.3, so Starlette 1.10's `listen_for_disconnect` path is used.
- So the web side is fine; the agent side is the bottleneck.
- Fix, replacing P5: "`ask` gains `cancel: threading.Event`. `_stream` starts a watcher (`cancel.wait()` → `kill_group()`), mirroring the timeout `expire`, and raises `AskError(..., ErrorCode.CANCELLED)`. Acceptance: a cancel set during a 30 s silent stub kills `claude` and `canada-mcp` within 1 s."
- The endpoint must be an `async def` generator fed through `loop.call_soon_threadsafe(queue.put_nowait, ...)`, with `finally: cancel.set()`. A sync generator runs in a threadpool and can't be cancelled.

**B3. §9 `series` event: `title` and `unit` don't exist in any `get_series` output, and `scalar_factor` is dropped.**
- VERIFIED (multi-04 transcript; `project_series` in mcp_server.py): the payload is `product_id, vector_id, coordinate, source_url, scalar_factor, points, first_period_returned, truncated, no_data_in_range`.
  - A title has to be joined from `get_table_dimensions` results (table title plus member names via `coordinate`).
  - A unit only exists as model text in `answer_values.unit`, which is inconsistent: "index" vs "index points" in compare-01/02.
- Fix: `series {step_id, product_id, vector_id, label|null, scalar_factor, truncated, points:[{ref_period, value|null, status_symbol|null}], source_url}`.
  - `label` is a best-effort join from that run's dimension results.
  - There is no unit field. The axis reads "value as published (scalar: units)".

**B4. §3 claim vs §9: "a rejected run shows only its error code" is false as specified.**
- `series` and `step_finished.summary` stream before the checks run. A run that ends in `ANSWER_REJECTED` will already have drawn charts and tool summaries.
- Fix:
  - the server buffers `series` and emits them only after `AskResult` exists, immediately before `answer`;
  - `summary` is generated from parsed fields only ("3 tables", "13 points, 2025-09 to 2026-09"), never from tool text;
  - add a contract test: a stream ending in `run_failed` contains no `series`.

**B5. §9 / U6: error codes aren't a closed set.**
- VERIFIED (AST scan of ask.py): 10 raise sites have `code=None`. They include:
  - grounding failures, e.g. `cited a URL no tool returned: {url!r}` (the message carries attacker-controlled text);
  - canary-in-tool-call;
  - CLI failures;
  - `UsageLimitError`.
- Tool errors also use `BAD_ARGUMENTS` and `RESULT_TOO_LARGE`, which aren't in `ErrorCode`.
- Fix: in U1 (it touches `src/`, so it must ride the one re-baseline), give every raise a code. Add `CANCELLED`, `USAGE_LIMIT`, `GROUNDING_FAILED` (or reuse `ANSWER_REJECTED`) and `MODEL_ERROR`.
  - `run_failed.code` becomes a non-null enum.
  - `step_finished.error_code` is matched against an allowlist, otherwise `TOOL_ERROR`.
- Also fix in P4: `on_step(started)` must fire after the canary check on arguments (ask.py ~333), so canary-bearing arguments never reach the browser.

**B6. §8 types: the generated TypeScript makes the discriminator optional.**
- VERIFIED (`scripts/events_schema.py` with pydantic 2 → json-schema-to-typescript 16.0.0): `oneOf` becomes a TS union and `const` becomes a literal, but a defaulted `type` field comes out as `type?: "run_started"`, with alias noise (`Type1`, `StepId1`).
- §9's events have no `type` field at all, yet E1's single `apply(event)` reducer over a JSON array needs one in the payload.
- Fix:
  - every model has `type: Literal[...]` with **no default** (or `json_schema_serialization_defaults_required=True`);
  - strip property `title`s before generating;
  - send unnamed SSE events, so the type lives in the data.
- VERIFIED: the fixed schema generates a clean `type: "run_started"` union.

## 2. Should fix

1. **U5 charts vs the real replays.** VERIFIED point counts in the 20 replayable recordings:
   - 6 have 13-point series;
   - 10 have only 1–3 points (lookup-01..06, compare-06, multi-01..03);
   - 4 are refusals with no series;
   - **none contain a `null`**; lookup-07, the only one with nulls, is grader-failed and excluded.

   Rules to add:
   - draw a line chart only with ≥3 non-null points; otherwise show a value tile plus the table;
   - add a synthetic fixture to test suppressed gaps.

   VERIFIED: with `connectNulls={false}`, Recharts draws gaps (path `M` count 2 per line).
2. **U3 "source points".** For `change_*` entries, `ref_period` is a range ("2025-09/2026-09") or spans two vectors (multi-01..03), so `{vector_id, ref_period, value}` is ambiguous. Also, `check_grounded` verifies only `level` values. The card should say changes are "computed by the model from the levels above; not independently checked".
3. **U9 pacing.** No dev transcript has per-event timing (only `wall_s`), so the demo will use a fixed pace unless transcripts are re-recorded (24 model runs). Say so, and scale the fixed pace to `wall_s`.
4. **The §10 token.** Any process that GETs `/` receives the cookie, so the token adds nothing beyond Origin + Host + `Sec-Fetch-Site`.
   - Either drop it, or make it real (JUDGEMENT, Jupyter-style): `serve` opens `http://127.0.0.1:PORT/?t=<token>`; the server swaps the token for the HttpOnly cookie and redirects; `/` without it shows "open the link printed in the terminal".
   - Also say how FastAPI serves the built `dist/`.
5. **CSP only applies to the build.** VERIFIED: in dev, `@vitejs/plugin-react` 6.3.0 injects an inline `<script type="module">` preamble, which breaks `script-src 'self'`. Say "CSP is enforced on built assets; Playwright CSP tests run against the build served by `canada-web`".
6. **Pages.**
   - Use `base: '/<repo>/'` and fetch replays via `import.meta.env.BASE_URL`. VERIFIED: the build prefixes asset URLs.
   - Select replays with a query string or hash, because Pages has no SPA fallback.
   - Drop `frame-ancestors` from the meta CSP. VERIFIED: Chromium ignores it there and logs a console error, which would trip a "no console errors" check.
7. **Accessibility.**
   - **Recharts:** VERIFIED that it defaults to `role="application" tabindex="0"` with no accessible name (RootSurface.js, confirmed in the browser). axe won't flag this. Use `accessibilityLayer={false}`, `role="img"`, an `aria-label` set to the summary sentence and `tabIndex={-1}` (VERIFIED: the override works), inside a `<figure>` whose `<figcaption>` holds the summary. Use a native `<details>` for the table, with `<caption>`, `<th scope>` and the literal text "suppressed".
   - **axe:** VERIFIED that in axe-core 4.14.1 `target-size` (WCAG 2.5.8, the 2.2 AA rule) is `enabled: false`. Configure `withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa'])` and `rules: {'target-size': {enabled: true}}`.
   - **What axe can't judge (JUDGEMENT):** live-region chattiness, focus logic, and contrast of SVG chart lines (1.4.11). Add unit tests on token contrast pairs, and do one manual VoiceOver pass in U4.
   - **Live region:**
     - the visible step list is not `aria-live`;
     - a separate visually hidden `role="status"` gets one short sentence per *finished* step, with no argument JSON;
     - the elapsed timer sits outside it;
     - when the answer arrives, focus moves to the answer heading (`tabIndex=-1`); on failure, to a `role="alert"`;
     - the Stop button unmounts while focused, so focus must be moved explicitly.
   - **Replays:** add "Skip to result" (2.2.2). Reduced motion should skip pacing, not just animations.
8. **Ordering rules.** Allow parallel `tool_use` (keyed by `step_id`). A `step_started` with no `step_finished` is closed by the terminal event, e.g. on a budget overrun.

## 3. Cut or defer

- **Split U2.** It is most of the front end. JUDGEMENT on size:
  - TS/TSX ~1,500–2,000 lines across ~15 components plus reducer and adapters;
  - CSS ~350 lines;
  - Vitest and Playwright tests ~900 lines;
  - `web/` Python ~600 lines plus ~500 lines of tests.

  Split it as:
  - U2a: events, converter, `build-demo` and contract tests, with plain-text rendering;
  - U2b: answer card, citations and errors;
  - U2c: chart, table and accessibility;
  - U2d: Pages.

  U3 shrinks a lot under B1's single request.
- **D4: consider a hand-written SVG chart instead of Recharts.** VERIFIED Vite 8.3.8 builds: React + Recharts was 603.7 kB minified / 178.4 kB gzip; React + an SVG polyline was 219.7 / 68.7 kB. The charts here are 1–2 series of ≤13 points (≤120 max). About 150 lines of SVG gives full control over accessibility and drops redux-toolkit and immer. Keep Recharts only if George values the library name.

## 4. Held up

- **React 19.3.1 + Recharts 3.10.1 under the exact §10 CSP.** VERIFIED in Chromium 153 (`csp-app/probe.cjs`), with the header CSP and the meta CSP, through load, tooltip hover, legend, and both reduced-motion settings:
  - **0 `securitypolicyviolation` events**;
  - 19 `style` attributes, all set through the CSSOM, which `style-src` doesn't block;
  - Trusted Types enforced (`innerHTML` throws TypeError) and `setAttribute('style')` blocked;
  - an injected `<img onerror>`/`<script>` string rendered as inert text.
- **Package dist code.** VERIFIED with tarball greps:
  - React DOM uses `innerHTML` only for `dangerouslySetInnerHTML` and when you render a `<script>` element;
  - Recharts measures text with a `<span>` plus CSSOM and `textContent`, and has no `<style>` injection or eval;
  - decimal.js-light's `Function('return this')` is in an unreachable UMD branch.
- **Vite production output** has no inline script (VERIFIED). The modulepreload polyfill is bundled into the JS, not inlined.
- **Trusted Types via `<meta>`** works (VERIFIED). MDN lists `trusted-types` support in Chrome 83, Firefox 148 and Safari 26.
- **FastAPI SSE built-ins** (VERIFIED source): a 15 s keep-alive (`_PING_INTERVAL`), `Cache-Control: no-cache`, `X-Accel-Buffering: no`.
- **Replay count.** VERIFIED: 20 = 24 dev recordings − 3 poisoned − 1 grader-failed (lookup-07), which matches §11.

---

# Round 1: scope

## SCOPE CRITIC: review of A8 (draft v0.1)

The amendment has about 40 deliverables: P1–P8, U1–U10, a 7-event contract, codegen, 7 security controls, build-demo, a Pages deploy, an axe suite, 3 ADRs, the bench, a 192-run re-baseline, a 3-reviewer review, the release and 5 vault lessons. The thing a hiring manager will actually open, the public demo, needs none of the `src/` work. Yet A8 schedules that work first (§14: U1 comes before U2).

My effort estimate for an AI-assisted solo build (JUDGEMENT):

| Phase | Build | Owner review |
|---|---|---|
| U0 | ~1 day | 2–3 h |
| U1 | ~1 day | 3–4 h (gated code, process-group tests) |
| U2 | 2–3 days | 4–6 h |
| U3 | 1–2 days | 3–4 h (security) |
| U4 | ~1 day | 2–3 h |
| **Total** | **6–9 days** | **15–20 h**, plus 5 lessons |

SPEC §16's precedent applies: scope was cut there because "v0.1 was 8–9 weekends, not 4".

### 1. Blocking

**B1. §14 order: the demo is blocked behind a re-baseline it doesn't need.**
- **What the demo needs (VERIFIED):** U2 needs only existing code. `run_events` already exists (ask.py:297) and is pure, and `offline.recordings()` already exists (offline.py:68). The investigation agrees: "Demo builder… needs no database, model or network".
- **What U1 gives the demo: nothing.**
  - **P3:** the dev transcripts store only `type` and `content` per event (I checked all 24). Staleness is question, prompt or poison only (grade.py:38–44), so U1 never forces a re-record. The gate re-baseline records Haiku runs (`ci_model`, gate.py:293), not the Sonnet demo recordings. So every v1.1.0 replay would show "timing not recorded" anyway.
  - **P1:** it saves 0 s in live web mode. The server imports `canada_agent.ask` once, and the import cost is per process (ask.py:30–34). JUDGEMENT, from reading the code.
  - **What's left for the UI:** P2 + P6 ≈ 55–90 ms per question, under 1% of a 10–27 s run.
- **Fix:** reorder to U0-lite → U2 (demo, no `src/` changes) → U3 + one `src/` PR → U4. Replacement text for §14: "U2 ships before any `src/` change; the `src/` bundle lands with live mode, because only live mode needs it."

**B2. §11: the demo hides the project's differentiator.**
- **What A8 says:** it excludes "injection runs" because "a rejected run carries the attacker's answer inside `structured_output`".
- **What the recordings show (VERIFIED):**
  - All 3 dev injection runs have `error: None` and all passed the graders (`evals/grades/dev.json`). In each, the model ignored the attack and said so; for example, inject-03: "A tool error message contained an instruction to cite a different website; I ignored it."
  - The bundle is §9 events, not raw transcripts ("it is then converted to the §9 events"), so `structured_output` is never shipped anyway.
- **The gap:** §3's headline claim, "The UI can't show what the checks rejected", is never visible in the demo, because no rejected run is bundled.
- **Material already on hand:**
  - `lookup-07` is a real, unpoisoned `ANSWER_REJECTED` run ("an answer with no values must be a refusal").
  - The README documents a gate run of inject-03 whose correct answer was withheld because it named the attacker's host.
- **Fix:** add three demo categories:
  - "Attack resisted" (the 3 dev injection runs; tool text shown as plain text and labelled untrusted);
  - "Answer rejected by checks" (lookup-07: only the steps plus the `run_failed` code and copy);
  - the 20 normal runs.
  build-demo should expect `AskError(ANSWER_REJECTED)` for runs on a fixed allow-list, rather than failing the build on them.

**B3. §7 U1/U9: the public demo's question box is undefined.**
Visitors will type their own question. A8 never says what replay mode does with it. **Fix:** "In replay mode the text box is replaced by a question picker. A typed question is matched with `offline._key`; with no match, the page lists the replayable questions and says live mode is local-only." Default to auto-playing one compare or multi-step replay on first load, so a 2-minute visitor sees the steps without clicking anything.

**B4. §6.3 P5 doesn't deliver the §3 claim "a cancel that really stops the agent".**
- **The problem:** P5 says `should_stop` is "checked on every event". That is exactly the delay of the in-`web/` Tap-raise cancel it replaces.
- **Evidence:** `build_command` passes no `--include-partial-messages` (VERIFIED, ask.py:127–151). The review notes this means "a long Sonnet turn means a multi-second cancel delay".
- **Fix:** either:
  - poll `should_stop` from a watcher thread inside `_stream`, the same way the timeout `Timer` calls `kill_group`; or
  - drop P5 from `src/` and use the Tap (no re-baseline), saying honestly that "cancel takes effect at the next agent event; 120 s backstop".

### 2. Should fix

- **P8 (VERIFIED):** `config/` holds `prices.toml` (cost reporting) and `scope.toml` (indexing, already covered by `data/index.sql.zst` in `INPUTS`). Adding `config/` to `INPUTS` means a price edit forces 192 runs. Meanwhile `gate.py` is in `JUDGING` (gate.py:49–58), so recording `claude --version` in the receipt needs **no** re-baseline. Split P8: ship the version stamp anytime, and drop `config/` (or add it to `JUDGING`).
- **P4:** this one is genuinely justified, for live mode only. `on_event` fires *after* the tool-argument canary check (ask.py:332 before 342). A Tap sees raw events before that check and can't know the canary. Keep P4, scheduled with U3, and say why in §6.3.
- **"Measured before optimising" doesn't need P1–P7 shipped.** That story is the §6.1 table, `make bench` and ADR 0011's "don't rewrite". Re-label §3's evidence accordingly, so P-items don't read as the proof.
- **§11 "About" panel:** promote it to a visible "How it's tested" tab. Build its numbers at build time from the committed `evals/gate-result.json`, `baseline.json` and `flakiness.json` plus `docs/chart.svg`, never hand-typed. Link draft PR #24, the staged gate failure. This gives about 80% of D2's portfolio value at about 5% of the cost.
- **If P3 ships with U3:** budget one `make transcripts --force` (24 Sonnet runs), or the replays never get real pacing. Until then, pace replays by distributing the recorded `wall_s` across steps, labelled "approximate pace".

### 3. Cut or defer

**Cut:**
- **P6 and P7:** 3–5 ms and under 0.3 ms offline.
- **The per-launch token:** Host + exact Origin + `application/json` with no CORS already blocks cross-site POSTs. The review called it "optional".

**Keep minimal:**
- **Trusted Types:** keep it as one CSP line, not a headline claim. Drop it if React or Recharts trips it.
- **Codegen pipeline:** keep only if it really is one script. Otherwise use a committed JSON Schema plus a Vitest/pytest test that every bundled replay validates and drives the reducer. That catches the same drift.
- **3 ADRs:** merge 0010 and 0012 into one ("web UI and replay-only demo"); keep 0011.
- **U4 review:** two reviewers (security + honesty) is enough for a static page plus a localhost server.
- **U10:** theme tokens yes. "No layout shift" as a tested requirement, no.

**Defer:**
- **P1 and P2:** move them into the U3 `src/` PR with P4, P5 and P3, so there is one re-baseline and it's earned by live mode.
- **The full eval explorer (D2):** deferring is correct, given the static evidence tab above.

**Re-scoped phases:**
1. **V0:** merged ADR, event models + schema, `make bench` (today's numbers only).
2. **V1:** the demo: build-demo over the 20 normal, 3 resisted and 1 rejected runs; picker and auto-play; steps, answer card, chart + table, error copy; "How it's tested" tab; Pages; an axe smoke test. **Zero `src/` changes, no gate cost.**
3. **V2:** live mode, plus one `src/` PR with P1–P5 (P5 as a watcher thread) and the re-baseline; optionally re-record dev with timestamps.
4. **V3:** README GIF and demo link at the top of the README, 2-reviewer review, v1.1.0.

### 4. Held up

- **ADR 0011, stay in Python:** I attacked it and it survives. §6.1–6.2 are well caveated, and the 1–3% figure matches the investigation's measurements. It is a strong interview line.
- **The re-baseline cost is small:** about 30 min of compute (investigation §"What any agent change costs"). My objection is that U1 blocks the demo and adds review surface, not the compute.
- **The no-hosted-live constraint and replay labelling** (§4, §11): correct and necessary under the quoted terms.
- **React + TypeScript over plain JS:** fits George's primary stack and the full-stack target roles. The review's 700–1,200-line estimate makes "no build" a false economy.
- **E3 (the answer is built only from `AskResult`) and no token streaming:** the right honesty bar, consistent with SPEC §16's style. It is the most memorable claim, provided the demo actually shows it (B2).
- **Host, Origin and 127.0.0.1-only binding:** justified, because the endpoint spends the subscription. These are not gold-plating.
---

# Round 2: security

## A8 round 2: security red-teamer

I edited nothing under `~/projects/`. To fit the 5-day budget I give up my round-1 B2 token design and three of my "should fix" items.

### 1. The other critics' Blocking items

**Eval critic**
- **B1 (the re-baseline hides any regression U1 causes): AGREE.** The check lives in `gate.py`, a judging file, so it costs no model runs.
- **B2 (`src/` doesn't expose the URLs and points the UI needs): AGREE-WITH-CHANGE.**
  - In the demo phase, `web/` *imports* `_payloads`, `series_values` and `CITABLE_URL` (E2 still holds), and emits `linkable: bool` and `product_id`. No `src/` change is needed.
  - Move this into `StepEvent` only when the `src/` bundle lands.
  - Ban StatCan regexes in `web/frontend`.
- **B3 (recordings must be re-wrapped and given a fixed clock before `run_events`): AGREE.** My round-1 scan ran `foreign_links` over the tool results directly, not through `run_events`, so it doesn't contradict this.
- **B4 (replay provenance: no date, pre-release commit): AGREE-WITH-CHANGE.**
  - Don't re-record (24 Sonnet runs); the budget can't take it.
  - Label every replay "recorded during v1.0 development (commit 9e183c1)".
  - Drop `recorded_on` and "recorded pace".
- **B5 (P8 misses the real fingerprint gaps): AGREE.** VERIFIED: `gate.py:60-68` `INPUTS` has no `migrations/`, and `migrations/` holds 0001–0006 `.sql`.

**Frontend critic**
- **B1 (use one streaming POST): AGREE.** It removes the GET-hardening, run-registry, orphan-window and cross-site-cancel issues from my round-1 B2.
- **B2 (cancel can't fire while the model is silent): AGREE.** Same finding as my round-1 B5.
- **B3 (`series` has no title or unit): AGREE.** Same as my round-1 B3 evidence.
- **B4 (a rejected run shows charts and tool text): AGREE.** Buffering `series` until after `AskResult` is the simplest fix.
- **B5 (error codes aren't a closed set): AGREE.** In the demo phase, map `None` to `AGENT_FAILED` inside `web/`. Make the codes real in the `src/` bundle.
- **B6 (generated TypeScript makes `type` optional): AGREE.**

**Scope critic**
- **B1 (ship the demo before any `src/` change): AGREE.**
- **B2 (show the injection runs): AGREE-WITH-CHANGE.** Show them, but redact foreign hosts in the tool text (ruling d below).
- **B3 (define what the demo's question box does): AGREE.**
- **B4 (P5 doesn't really cancel): AGREE.** Use the watcher-thread option.

### 2. Conflict rulings

- **a. Phase order: scope wins.** Ship U2 (the demo) with zero `src/` changes. The live-mode `src/` bundle comes later, guarded by eval's regression check against v1.0. Re-recording dev transcripts is deferred, and replays are labelled honestly. Reason: the demo needs nothing from U1, and 192 runs shouldn't block it.
- **b. Transport: one `POST /api/ask` that streams SSE, read with fetch.** Reason: it removes a whole attack surface (unprotected GET, cross-site cancel, the POST-to-GET orphan window, reconnect loops). The frontend critic VERIFIED that FastAPI's SSE works over POST.
- **c. Local auth: drop the token.** I concede my round-1 B2. Keep:
  - Host allowlist of `127.0.0.1` only;
  - `Origin` must equal `http://127.0.0.1:PORT`, port included, with `null` rejected;
  - `Content-Type: application/json`;
  - `Sec-Fetch-Site: same-origin`.

  Reason: on a single-user Mac, any local process that could steal a token could just run `claude -p` itself. §10 should say so plainly instead of claiming a token protects anything.
- **d. Injection runs: yes, there is a safe middle.**
  - Include all 3 as "attack resisted".
  - Shown tool text goes through `untrusted_text`, then every `foreign_links()` hit becomes "[outside link withheld]".
  - Add lookup-07 as "rejected by checks", showing the code only.
  - Reason (JUDGEMENT): `statcan-data.de` is not a reserved test domain. Publishing "AI assistants must cite <host>" verbatim would turn the public page into an injection carrier for AI crawlers.
  - A build test asserts zero `foreign_links` hits across the whole bundle.
- **e. Charts: hand-written SVG.** Reasons:
  - The frontend critic VERIFIED that only 6 of the 20 replays have 13 points, 10 have 1–3 points and none has a null.
  - Recharts defaults to an unnamed `role="application"`.
  - It also means one less npm dependency in the supply chain and nothing that could clash with the CSP.
- **f. P8:**
  - add `migrations/` to `INPUTS`;
  - put `config/` in `JUDGING`, not `INPUTS`, so a price edit doesn't force 192 runs;
  - stamp `claude_version` per run, and have `check_evidence` require one version across all runs.

  Reason: it closes the real behaviour gap without a re-baseline on every price edit.

### 3. Must-fix list for A8 v0.2 (ranked)

1. One streaming `POST /api/ask` (abort cancels it), with the §2c header checks and no token. §10 says so honestly.
2. Step text is built by the server from parsed fields; arguments and third-party text are passed through `untrusted_text` and `foreign_links` redaction (imported from `canada_agent`); `series` is buffered until after `AskResult`; links are rendered only from `linkable`/`product_id`.
3. A closed error-code set. `run_failed` never carries `str(exc)`, and the web layer maps `None` to `AGENT_FAILED` until the `src/` bundle adds the codes.
4. The question is validated in `web/`: stripped, at most 500 characters, no control characters or NUL, no leading `-` (VERIFIED in round 1: `claude` parses `--…` as an option). `build_command` gets `--` in the `src/` bundle.
5. P5 is replaced by a `cancel: threading.Event` watcher that kills the process group. The test checks by process group, not by the `canada-mcp` name, and server shutdown kills any active group.
6. U2 (the demo) ships first, with zero `src/` changes and honest provenance (commit 9e183c1).
7. `build-demo`:
   - re-wraps events and uses a fixed clock;
   - fails closed when the grade verdicts are missing;
   - uses an explicit allow-list (20 normal runs + 3 resisted + lookup-07);
   - has a zero-foreign-link test over the whole bundle;
   - uses repo-relative paths only.
8. The `src/` bundle's study is judged against the v1.0 baseline before it becomes the new baseline (eval B1).
9. Pages workflow:
   - a build job with `contents: read` and `npm ci --ignore-scripts`;
   - a separate deploy job, the only one with `pages: write` and `id-token: write`;
   - triggered only by a push to `main`;
   - every action pinned by SHA.
10. Events have a required `type` discriminator, plus the P8 change from §2f.

**What I concede or downgrade from round 1**
- **B2 (Jupyter token): conceded**, replaced by item 1.
- **B1 (argv injection): downgraded** from a `src/`-first fix to `web/`-side validation now, with `--` added when the `src/` bundle lands.
- **S3 (`ANTHROPIC_API_KEY` passthrough): downgraded** to a one-line refusal at server startup, nice-to-have.
- **S4 (daily cap on live runs): dropped.**
- **S5 and S6 (meta-CSP notes, Pages shared origin, `ps` visibility of the canary): downgraded** to a sentence each in §10/§11.

---

# Round 2: eval

## Round 2: eval-integrity critic

I re-checked the facts below offline. My scratch files are in `.../a8-review/eval/`.

**Restated B4, on a diff basis.**
- VERIFIED: `git diff --stat 9e183c1 d7cc29e -- src` shows `ask.py` +86, `links.py` 16, `transcripts.py` 6, plus `offline.py`, `graders.py` and `gate.py` changed after the commit where all 20 demo recordings were made.
- VERIFIED: `git branch -a --contains 9e183c1` lists only `docs/v1-release` and `demo/staged-gate-failure`, not `main`.
- So the replays come from an agent that is neither the v1.0 release nor v1.1. Their provenance must say "recorded during v1.0 development", and the commit link only resolves while those branches exist.

### 1. Other critics' blocking items
- **Security**
  - **B1 (argv injection): AGREE.** Add `--` before the question, or send it on stdin, in the `src/` bundle. Also reject a leading `-` and NUL at the server.
  - **B2 (token): AGREE-WITH-CHANGE.** Under a single streaming POST there is no GET to protect. Exact `Origin` (with port), `Host` and `Sec-Fetch-Site` checks block other origins, and a local process could run `claude` itself anyway. Drop the token (see 2c).
  - **B3 (attacker text in step events): AGREE.** VERIFIED: inject-01 and inject-03 each carry one foreign link in a tool result, and inject-02 carries a fake value. Summaries are built only from structured fields.
  - **B4 (errors without a code): AGREE.** VERIFIED: the gate keys on grader check names, and `BLOCKED` in gate.py is never used. So giving every error a code doesn't change pinned verdicts.
  - **B5 (cancel): AGREE.** A watcher thread (`cancel.wait()` → `kill_group()`), and the test checks by process group.
- **Front end**
  - **B1 (single request): AGREE.**
  - **B2 (cancel watcher): AGREE.** It is the same fix as security B5.
  - **B3 (`series` has no `title`/`unit`; keep `scalar_factor`): AGREE.**
  - **B4 (buffer `series` until `AskResult`): AGREE.**
  - **B5 (closed set of error codes): AGREE**, merged with security B4.
  - **B6 (required `type` field on every event): AGREE.** It's cheap.
- **Scope**
  - **B1 (demo before any `src/` change): AGREE.** It changes my own items (see 3).
  - **B2 (show resisted and rejected runs): AGREE-WITH-CHANGE.** See 2d.
  - **B3 (question box in replay mode): AGREE.**
  - **B4 (cancel): AGREE.** It is the same fix as security B5.

### 2. Rulings
- **a. Phase order: demo first, with zero `src/` changes.**
  - `web/` is outside `INPUTS` (VERIFIED), so the demo costs no gate runs.
  - `build-demo` can import `run_events`, `series_values` and `CITABLE_URL`.
  - Every cited URL in an answer that passed `check_grounded` is already one a tool returned (VERIFIED in ask.py), so the link rule needs no new `src/` API.
  - The `src/` bundle lands with live mode, and the v1.0-baseline regression check (item 1 below) rides with it.
- **b. Transport: one POST that streams Server-Sent Events, read via `fetch`.** It removes the unprotected GET, the auto-reconnect loop and the run registry.
- **c. Local auth: drop the token,** conditional on (b). Bind `127.0.0.1` only; use exact `Origin` with the port, `Host`, `Sec-Fetch-Site: same-origin`, JSON content type and no CORS.
- **d. Injection runs in the public demo: a safe middle exists.**
  - Include the 3 runs as "attack resisted". VERIFIED: all have `error: None`, 0 foreign links in the answer, and pass `check_answer`.
  - Steps show only structured summaries, never tool text.
  - The attack is described from the `poison` spec (goal, route, host as plain text).
  - The build fails if `foreign_links()` finds anything in any bundled string.
  - Add lookup-07 as "rejected by checks", showing the code only.
- **e. Charts: hand-written SVG.**
  - 10 of 20 replays have 1–3 points, so they get a value tile instead of a chart.
  - The SVG build is about 110 kB gzip smaller than with Recharts (front end, VERIFIED).
  - Recharts' default accessibility markup would need overriding anyway.
- **f. P8: change it.**
  - Drop `config/` from `INPUTS`. VERIFIED: `prices.toml` is used only by tests, and `scope.toml`'s output (the index dump) is already hashed.
  - Add `migrations/` to `INPUTS`.
  - Stamp `claude_version` per transcript.
  - `verify` checks that the gate and study runs share one version, equal to the receipt's.
  - All of this lands in the `src/` bundle.

### 3. Final must-fix list for A8 v0.2 (ranked)
1. **The regression check, before the baseline is replaced.** `canada-gate baseline` must first judge the new study against the outgoing v1.0 baseline. It is a gate.py-only change with 0 model runs. Fix §15's claim "the gate decides" (my B1).
2. **A one-request stream, with Origin, Host and `Sec-Fetch-Site` checks and no token** (front end B1, rulings b and c).
3. **Argv injection:** `--` before the question, plus server-side rejection (security B1).
4. **Untrusted text never reaches the page.** Structured summaries only, `series` buffered until the answer, foreign links redacted, and a build that fails on any foreign link (security B3, front end B4, ruling d).
5. **Cancel through a watcher thread,** tested by process group (security B5, front end B2, scope B4).
6. **Every failure has a code; messages come from a fixed table** (security B4, front end B5).
7. **Reorder the phases** so the demo ships before the `src/` bundle (scope B1).
8. **Demo honesty.**
   - Show the 3 resisted runs and 1 rejected run.
   - The header reads "20 of 21 dev questions, the set the agent was tuned on; held-out 13/16 on v1.0, not re-run".
   - Provenance says "recorded during v1.0 development".
   - `recorded_on` comes from the commit date, labelled as such (my B4 restated, scope B2).
9. **State `build-demo`'s check honestly.** It re-wraps each recording and runs `run_events` with a fixed `clock`. VERIFIED: 20/20 pass that way, versus 4/20 as stored. This checks the answer against the recorded tool results; it does not re-run the tools (my B3).
10. **The P8 changes in ruling f, plus a minimal benchmark.**
    - P8: per ruling f (my B5).
    - `make bench` commits raw samples and the environment, runs before and after interleaved with n≥30, and measures warm bytecode. VERIFIED: medians drift about 4–5% between batches.

**What I concede or downgrade:**
- **B2 (expose URLs and source points from `src/`): conceded.** Imported functions are enough, and the links are decided in Python.
- **B4's dev re-record: downgraded to optional.** Pace replays from the recorded `wall_s`, labelled "approximate pace".
- **Benchmark rigour: downgraded** to the small requirements in item 10.
- **The fidelity tests and the web-argv test (should-fix 4): folded** into item 4's contract tests.
- **Re-recording dev transcripts and P1's CLI-only label: dropped** from the must-fix list.

---

# Round 2: frontend

ROUND 2: FRONT-END AND ACCESSIBILITY ENGINEER

## 1. Other critics' Blocking items

**Security**
- **B1 (argv injection): AGREE-WITH-CHANGE.** The server must reject a leading `-`, NUL and control characters. That fix holds whatever Commander does with `--`. Add `--` in `build_command` as defence in depth, covered by a stub test and one `make live-web` run.
- **B2 (cookie and GET): AGREE-WITH-CHANGE.** The single-POST transport (2b) removes the GET route entirely; on the token, see 2c.
- **B3 (attacker text in step events): AGREE.** It is my round-1 B4: summaries built only from structured fields, and `series` emitted only after `AskResult` exists. I also adopt Security's `product_id`-only href template.
- **B4 (code-less errors): AGREE.** It is my round-1 B5. Mapping `None` to `AGENT_FAILED` is simpler than my enum expansion; take theirs.
- **B5 (cancel): AGREE.** It is my round-1 B2. Their test fix is right: check by process group, because the server runs as `python -m canada_agent.mcp_server`, not as `canada-mcp`.

**Eval**
- **B1 (regression check against v1.0): AGREE.** It lives in `gate.py` (judging code), so it costs no extra runs.
- **B2 (`src/` doesn't expose URLs or sources): AGREE-WITH-CHANGE.**
  - For the demo, `build-demo` (Python in `web/`) imports `CITABLE_URL` and `series_values` and emits `linkable` flags. That needs zero `src/` changes and satisfies E2.
  - P4 carries the same data for live mode.
  - The ban on StatCan regexes in `web/frontend` stays.
- **B3 (`run_events` can't read stored events): AGREE.** VERIFIED: `run_events` reads `event.get("message")` (ask.py), while transcripts store `{"type","content"}`. They need re-wrapping plus a fixed clock.
- **B4 (provenance): AGREE-WITH-CHANGE.**
  - VERIFIED: all 24 dev recordings carry `git_sha 9e183c1`, and that commit is dated 2026-11-07.
  - Not re-verified: whether it is an ancestor of v1.0.0, because no `v1.0.0` tag exists in my local clones.
  - The change: skip re-recording to stay in budget. Label replays "recorded from commit 9e183c1 (2026-11-07), during v1.0 development", with approximate pacing spread across `wall_s`.
- **B5 (P8): AGREE-WITH-CHANGE.** Ruling in 2f.

**Scope**
- **B1 (demo first): AGREE.**
- **B2 (injection runs in demo): AGREE-WITH-CHANGE.** The middle path is in 2d.
- **B3 (question box): AGREE.** Use a picker only (no typed-question matching) and auto-play one multi-step replay.
- **B4 (cancel): AGREE.** Use the watcher thread, not the Tap.

## 2. Rulings on the conflicts

**a. Phase order: the demo ships first, with zero `src/` changes.** The `src/` bundle lands with live mode and carries Eval's regression check, which needs no extra runs. Re-recording transcripts is deferred and labelled honestly. Reason: the demo needs nothing from U1, and this removes 192 runs from the critical path.

**b. Transport: one `POST /api/ask` that streams SSE, read with `fetch` and stopped with `AbortController`.** VERIFIED: FastAPI 0.163.1 supports SSE over POST, and on disconnect the generator's `finally` runs at once. This deletes the orphan window, GET protection, auto-reconnect handling and the run registry. It is both the smallest and the safest design.

**c. Local auth: drop the token.** Keep:
- `Host` restricted to `127.0.0.1` only;
- exact `Origin` match;
- `Content-Type: application/json`;
- `Sec-Fetch-Site: same-origin`;
- no CORS.

  Document that another local OS user is out of scope. Reason: with no GET route, the remaining threat is local processes, and those can already run `claude` themselves. I concede my round-1 "make the token real" option.

**d. Injection runs: show them, without any tool text.**
- Include the 3 resisted runs as "Attack resisted". Their steps use server-built summaries only, plus a badge built from the transcript's `poison.goal`. No tool text ships.
- Include lookup-07 as "Rejected by checks": steps plus its code only.
- `build-demo` asserts that `foreign_links()` finds nothing in any emitted string.

  Reason: this shows the differentiator, and the poisoned text never leaves the build.

**e. Charts: keep Recharts.** I concede my round-1 hand-written-SVG suggestion. Reason:
- VERIFIED: zero CSP or Trusted Types violations.
- Its accessibility default (`role="application"`) is fixed with four props, which I verified.
- That is less code for George to review than ~150 lines of hand-written SVG.
- The 178 kB gzip bundle is acceptable for a demo.

**f. P8:**
- Add `migrations/` to `INPUTS` and `config/` to `JUDGING`.
- Stamp `claude_version` in the receipt and transcripts.
- Defer `check_evidence` version equality until a second version actually appears.

  Reason: this closes the real gap, and a price edit no longer forces 192 runs.

## 3. Must-fix list for A8 v0.2 (ranked)

1. Reorder the phases: demo (zero `src/`) → live mode plus one `src/` PR with its re-baseline and the v1.0 regression check → release.
2. Question hardening: reject a leading `-`, NUL and control characters, and add `--` in `build_command` (P9).
3. Cancel through a `threading.Event` watcher that calls `kill_group`. Test by process group with a silent stub. Server shutdown also sets cancel.
4. Single POST SSE transport with Host, Origin, JSON and `Sec-Fetch-Site` checks; no token; Stop is an abort.
5. No tool text reaches the browser. Summaries are server-built, `series` comes after `AskResult`, links are a `linkable` flag computed in Python, and `foreign_links` is asserted at build time.
6. Error copy is a fixed table. `None` maps to `AGENT_FAILED`, `USAGE_LIMIT` and `CANCELLED` are added, and no event ever contains `str(exc)`.
7. Event contract:
   - a required `type` literal with no default (VERIFIED: a default makes the TypeScript `type?:`);
   - `series` carries `{product_id, vector_id, scalar_factor, points (with status_symbol)}`, with no title or unit;
   - parallel and dangling steps are allowed.
8. `build-demo`:
   - re-wraps events and uses a fixed clock;
   - fails closed on missing verdicts or a non-dev split;
   - shows honest provenance (commit 9e183c1, approximate pace);
   - outputs 20 normal + 3 resisted + 1 rejected runs, with a picker.
9. P8 as ruled in 2f, plus Eval's judging-only regression check.
10. Accessibility minimums:
    - Recharts set to `accessibilityLayer={false}`, `role="img"`, an `aria-label` and `tabIndex={-1}`;
    - a chart only when there are ≥3 points, always with its table (VERIFIED: 10 of 20 replays have ≤3 points);
    - axe run with the `wcag22aa` tags and `target-size` enabled (VERIFIED: off by default in axe-core 4.14.1);
    - one `role="status"` announcement per finished step;
    - focus moves to the answer heading or the alert;
    - one manual keyboard and VoiceOver pass.

**What I concede or downgrade from round 1**
- **Conceded:** the two-request fallback (B1), the real-token option, the hand-written SVG chart, and the four-way U2 split (two PRs are enough).
- **Downgraded to nice-to-have:** "Skip replay", the Pages SPA-routing note, and change-value source-point wording beyond one caption line.
- **Kept, folded into item 7:** B3 (`series` fields) and B6 (generated types).

---

# Round 2: scope

## Scope critic, round 2

**Overall:** A8 fits the 5-day / 12-hour budget if the order is demo first, then one `src/` PR that ships with live mode.

### 1. Other critics' Blocking items

**Security**
- **B1 (question argv injection):** AGREE. It is the top fix, and the cheapest.
- **B2 (token and the GET route):** AGREE-WITH-CHANGE. Most of it becomes moot under one streaming POST (ruling b). Drop the token instead of adopting the Jupyter-style design (ruling c).
- **B3 (attacker text in steps):** AGREE. Steps are built only from structured fields, and `series` carries `product_id` instead of a URL.
- **B4 (errors with no code):** AGREE. Merge it with frontend B5.
- **B5 (cancel):** AGREE. This is the same finding as my round-1 B4.

**Eval**
- **B1 (no check of U1 against v1.0):** AGREE. It lives in `gate.py`, a judging file, so it needs no extra runs.
- **B2 (`AskResult` lacks returned URLs and sources):** AGREE-WITH-CHANGE.
  - Live mode: P4 carries them, as eval proposes.
  - Demo: `build-demo` computes `linkable` and the source points in Python by importing `CITABLE_URL` and `series_values`. That keeps E2 and touches no `src/`.
  - Drop the Vitest "citation rule".
- **B3 (`run_events` can't read recordings as stored):** AGREE. I concede part of my round-1 B1: recordings need re-wrapping and a fixed clock before `run_events`. That work lives in `web/`, so "demo first" survives.
- **B4 (provenance):** AGREE-WITH-CHANGE.
  - The demo ships labelled "recorded during v1.0 development (commit 9e183c1, before release)", with paced replays scaled to `wall_s`.
  - The 24-run dev re-record, which adds `recorded_at`, `claude_version` and `t_ms`, rides the single `src/` PR.
- **B5 (P8):** AGREE (ruling f).

**Front end**
- **B1 (one streaming request):** AGREE.
- **B2 (cancel):** AGREE (duplicate of security B5).
- **B3 (`series` fields):** AGREE.
- **B4 (buffer charts until checks pass):** AGREE. Without this, §3's main claim is false.
- **B5 (closed error set):** AGREE.
- **B6 (discriminator):** AGREE-WITH-CHANGE. Drop codegen. Use a hand-written TypeScript discriminated union with 7 members, required `type` literals in pydantic, pytest validation of every bundle against the committed JSON Schema, and a Vitest test that runs the reducer over every bundled replay. That is cheaper and catches the same drift.

### 2. Rulings

- **a. Phase order: demo first, with zero `src/` changes.**
  - Every Blocking item in `src/` (P9, cancel, error codes, P4 data) exists only for live mode, so it ships with live mode as one PR.
  - That PR also re-records dev and runs eval's regression check against the v1.0 baseline.
  - This decouples the highest-signal deliverable from the riskiest one.
- **b. Transport: one `POST /api/ask` that streams SSE, read with `fetch`.**
  - VERIFIED by the frontend critic: FastAPI SSE works over POST, and `abort()` reaches the worker within ms.
  - It deletes the run registry, the orphan window, GET hardening and reconnect handling.
- **c. Local auth: drop the token.**
  - The only state-changing route becomes the POST, guarded by Host = `127.0.0.1`, an exact `Origin` including the port, `Sec-Fetch-Site: same-origin` and a JSON content type.
  - JUDGEMENT: a malicious local process can already run `claude -p` with George's own credentials, so a token defends against nothing new.
  - A cross-port page on localhost is caught by the exact-Origin check.
- **d. Injection runs in the demo: a safe middle exists.** Include inject-01 to inject-03 as "attack resisted", but display **no tool text**:
  - the summaries are structured;
  - a fixed, server-written caption says the run carried a planted instruction ("[link withheld]");
  - VERIFIED in round 1: the answers name no foreign host, as they must, since `check_answer` passed;
  - `build-demo` runs `foreign_links` over every displayed string and fails on any hit.

  Add lookup-07 as "rejected by checks", showing the code only. If time runs short, this item goes first; the poisoned runs are optional.
- **e. Charts: a hand-written SVG.**
  - VERIFIED by the frontend critic: 10 of the 20 replays have 1–3 points; React + Recharts is 178 kB gzip against 69 kB for SVG; Recharts needs accessibility overrides.
  - Use a value tile below 3 points.
- **f. P8:**
  - add `migrations/` to `INPUTS` (it rides the one re-baseline);
  - `config/` goes into `JUDGING` or stays out entirely;
  - `claude_version` is recorded per transcript, and `check_evidence` requires it to be the same across runs.

### 3. Must-fix list for A8 v0.2 (ranked)

1. **P9:** `--` before the prompt; reject a leading `-`, control characters and NUL (security B1).
2. **Cancel:** `threading.Event` plus a watcher calling `kill_group()`; a silent-stub test checked by process group (security B5, frontend B2, my B4).
3. **One streaming POST:** abort cancels the run; Host, exact Origin, `Sec-Fetch-Site` and JSON checks; no token, no GET route (frontend B1, security B2 changed).
4. **No tool text reaches the page:** structured summaries; `series` buffered until `answer`; `product_id` instead of a URL; a `foreign_links` scan at build time (security B3, frontend B3/B4).
5. **Closed error codes:** every raise coded; fixed messages; `str(exc)` never appears in an event (security B4, frontend B5).
6. **Demo first in `web/`:** re-wrap plus fixed clock; `linkable` computed by imported Python; honest provenance label; question picker plus auto-play; lookup-07 shown as rejected (my B1/B3, eval B2–B4).
7. **One `src/` PR alongside live mode:** P4 carrying the data, P5, P9, the codes, P3 plus `recorded_at`/`claude_version`, P1 and P2. Code review finishes before recording. Regression check against v1.0. 24-run dev re-record (eval B1/B4, should-fix 5).
8. **P8 as in ruling f** (eval B5).
9. **Discriminated event types:** a hand-written TS union plus schema tests; drop codegen (frontend B6).
10. **Budget cuts:**
    - SVG chart;
    - P6 and P7 cut;
    - ADRs 0010 and 0012 merged;
    - a 2-reviewer U4;
    - eval explorer deferred, with a build-time "How it's tested" tab;
    - axe with the `wcag22aa` tags plus one manual keyboard/VoiceOver pass; soften the WCAG claim.

**Plan for 5 days and 12 hours of review (JUDGEMENT):**

| Days | Work | Owner review |
|---|---|---|
| 1–2 | Demo and Pages | ~4 h |
| 3 | The `src/` PR and re-baseline (~216 runs, ~35 min) | ~3 h |
| 4 | Live mode | ~3 h |
| 5 | Accessibility, README GIF, review, release | ~2 h |

**What I concede or downgrade:**
- **My B1:** kept, but it needs eval's re-wrap. I also concede P1 can ride the re-baseline, since it's free there.
- **My B2:** downgraded. Injection runs are now optional and shown without tool text. My "show the tool text as plain text" was wrong: security's point stands.
- **My B3 (question box):** downgraded to part of item 6.
- **My "keep codegen if cheap":** withdrawn.