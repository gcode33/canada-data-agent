# Amendment A8: Web UI and performance

Status: **v0.2, approved by George 2026-11-18, with every decision in §16 at its default.** It amends `SPEC.md` v1.0 (with A1 and A7) and builds on ADR 0009. The build plan is `docs/PLAN-A8.md`.

v0.2 replaces v0.1 after a two-round adversarial review by four critics: a security red-teamer, an eval-integrity critic, a front-end and accessibility engineer, and a scope critic. The critics' disputed facts were re-checked by the chairman. What changed and why is in §17; the full critiques are in `docs/reviews/2026-11-17-a8-spec-review.md`. The investigation behind the stack choice is in `docs/reviews/2026-11-17-stack-investigation.md` and `-stack-review.md`.

The rule for every choice: **what fits this application**, not what job postings ask for.

## 1. In plain words

Today the agent lives in a terminal. A8 adds two things, in this order.

1. **A public demo anyone can open.** It replays the agent's recorded runs in a web page:
   - the steps it took (tables searched, series fetched);
   - the answer, with its numbers, a chart and links to StatCan;
   - a run where it **resisted a planted attack**;
   - a run its own checks **rejected**.

   It never calls Claude, so it costs nothing and stays inside Anthropic's terms (§4). It ships first, because it needs no change to the agent's code.
2. **Live mode on George's own computer.** The same page, asking Claude for real and streaming each step as it happens. A live question can take half a minute (one recorded Sonnet run took 26.7 s), so seeing the steps matters, and a Stop button really stops the agent.

A8 also makes the Python faster where measurement says it's worth it. It does **not** rewrite anything in another language: waiting on Claude is about 92–95% of a question, and all our own Python together is a few percent (§6).

## 2. What changes in SPEC v1.0

| SPEC v1.0 | A8 |
|---|---|
| §3 "No chat UI or hosted site" | A **static public replay demo** and a **local live web UI**. There is still no hosted live mode |
| §4 Users: George, MCP clients, CI | Adds **demo visitors** (replays only) |
| §6 Stack: Python only | Adds a TypeScript front end in `web/`. All agent code and every check stay Python |
| §5 "v1.1" feature list | Renamed **"later"**, because A8 ships as release **v1.1.0** (D5) |
| §10 Gate | `canada-gate baseline` first checks a new study against the outgoing baseline (§6.4). `migrations/` joins the fingerprint |
| §12 Observability | New recordings carry per-event timestamps, `recorded_at` and the Claude Code version |

Everything else in SPEC v1.0 still holds.

## 3. Goals and claims

| Claim | Evidence a reviewer can check |
|---|---|
| I measure before I optimise | §6.1's latency budget; `make bench` raw samples in `docs/perf/`; ADR 0011 (the decision *not* to rewrite) |
| The UI never shows what the checks rejected | The demo's "rejected by checks" replay shows only an error code; a contract test fails if a failed run's stream contains a chart, answer text or tool text (§9) |
| I test AI features adversarially | The demo's "attack resisted" replays, described without repeating the attack; the build fails if any outside link reaches the page |
| A streaming interface with a cancel that really stops the agent | The `test_cancel_kills_process_group` stub test (§13); one-request streaming (§8) |
| Accessibility is designed in, not bolted on | axe with WCAG 2.2 AA rules in CI, plus a recorded manual keyboard and VoiceOver pass in `docs/a11y.md`. Automated tools catch only part of WCAG, so the claim is "tested", not "compliant" |

## 4. Constraints

- **No API billing** (ADR 0009). Live mode runs `claude -p` on George's subscription. `canada-web serve` refuses to start if `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` is set, because `claude` would then bill the API.
- **Anthropic's terms** (code.claude.com/docs/en/legal-and-compliance, checked 2026-11-17): "Anthropic does not permit third-party developers to … route requests through Free, Pro, Max, or Ultra plan credentials on behalf of their users."
  - Live mode serves one person, on his own machine.
  - The public demo never calls a model.
  - Letting a friend use live mode would break this too. The README says so.
- **The eval gate** (ADR 0008). Any change to `src/canada_agent`, `pyproject.toml` or `uv.lock` (and, after A8, `migrations/`) means:
  - a new flakiness study (k=5, 120 runs);
  - a baseline;
  - a gate run (k=3, 72 runs).

  A8 puts **every** `src/` change in **one** PR (§6.3), so this is paid once.
- **The held-out test split** never runs again, and no test-split recording appears anywhere in the UI.
- **Budget:** about 5 AI-assisted build days and ≤ 12 hours of George's review. No new paid services: Voyage stays free tier, and GitHub Pages is free.

## 5. Non-goals (A8)

- **No hosted live mode.** No accounts or logins, and nothing multi-user.
- **No rewrite in Rust, Go or TypeScript**, and no hand-written Rust or Go for speed. §6.2 shows why. An optional Rust learning experiment is D3, and stays outside the agent.
- **No token-by-token answer streaming.** The answer, and any chart, appear only after the runtime checks pass.
- **No multi-turn chat.** Each question is its own isolated run.
- **No eval explorer** (browsing runs, receipts, flakiness). A static "How it's tested" tab covers the essentials (§11).
- **No server-side rendering framework.** The backend is already Python.
- **No prompt or tool-description changes.** Cutting model round trips is the biggest latency lever, but it can cost accuracy, so it needs its own pre-registered experiment (§6.5).
- **No local auth token.** Other processes and users on George's machine are out of scope: a process that could steal a token could run `claude` itself (§10).

## 6. Performance

### 6.1 Where the time goes (measured 2026-11-17, offline)

| Part of one question | Time | Source |
|---|---|---|
| Whole question, Haiku eval runs (median of 761, across 24 dev questions and four agent versions) | 9.8 s (p95 15.6 s) | `evals/runs` |
| Whole question, Sonnet dev transcripts (n=24) | 7.45 s | `evals/transcripts/dev` |
| **One live Sonnet question** (n=1) | **26.7 s** | `docs/demo/ask-trace.txt` |
| Waiting on Claude: the model plus Claude Code's own work (`duration_ms`) | ~95% of a median Haiku run; ≤ 92% of the live trace | `duration_ms` |
| Process start and teardown (`claude -p` plus our tool server) | ~0.5 s | wall minus `duration_ms` |
| Our tool server, start to ready (Claude Code waits for it before the first turn) | 0.25 s, mostly `import mcp` | handshake benchmark |
| CLI start (`import canada_agent.ask`), ~0.2 s of it importing `mcp_server` for one constant | 0.28 s | `-X importtime` |
| All tool calls in one question, offline | ~33 ms | in-process benchmark |
| Live network inside tools (Voyage, StatCan) | ~2 s | the one live trace |
| Runtime checks | < 1 ms | benchmark |

All our own Python CPU is about 0.3–0.55 s of a 7–27 s question (1–4%), over 90% of it importing modules.

**Caveats:**
- The live numbers are a single trace, 3.6× the Sonnet snapshot median, and the gap is unexplained.
- The recordings drop per-event times, so model thinking can't yet be separated from tool round trips.
- P3 fixes this for new recordings.

### 6.2 Decision: stay in Python (ADR 0011)

| Option | Best-case saving per question | Cost |
|---|---|---|
| Tool server in Go or Rust | ~0.23 s (start-up only) | Rewrite ~2,100 lines; re-pin the tool snapshot; re-baseline; a second copy of the security rules |
| Search in Rust | ≤ 5 ms offline; 0 live (network-bound) | The same, for no visible gain |
| Snapshot parsing in Rust | ~50 ms, once per table | A native build per platform |
| Checks or stream parsing in anything | < 1 ms | – |
| **All of the above** | **~0.3 s of 7–27 s** | Three toolchains, three test setups, cross-language boundaries |

- **Security rules stay in one language.** The link filter (`links.py`) and the canary and grounding checks are shared by the runtime and the graders. The review showed the filter *can* be ported to JavaScript: 0 mismatches over 30,000 fuzzed strings, once `\w` was rewritten as Unicode classes. But two copies of a security rule can drift, and that is reason enough.
- **Rust is already here where it pays:** `pydantic-core`, `jiter` and `rpds-py`. `psycopg-binary` is C.
- **If a CPU hotspot ever shows in a profile**, the order is:
  1. a Rust-backed library;
  2. one small benchmarked PyO3 extension;
  3. never a rewrite.

### 6.3 The `src/` bundle: one PR, shipped with live mode (phase U2)

The demo needs **no** `src/` change: `build-demo` imports what it needs from `canada_agent`. Every `src/` change is for live mode, so they all land together with it.

| # | Change | Why | Acceptance |
|---|---|---|---|
| P1 | Move `SERVER_NAME` to a tiny module, so `ask.py` and `offline.py` stop importing `mcp_server` for one constant | −0.2 s per **CLI** question (the web server imports once, so live mode gains nothing) | `make bench`: a faster import of `canada_agent.ask` |
| P2 | Lazy-load what the tool server uses only on some calls (`psycopg`, `yaml`, `zipfile`, `csv`) | 50–70 ms per question | `make bench`: a faster handshake |
| P3 | `_tee` stamps each captured event with `t_ms`. `slim()` keeps it. Each transcript records `recorded_at` (UTC) and `claude_version` | Live-latency measurement; honest provenance | New recordings carry all three; `canada-grade --check` still passes on old ones |
| P4 | `on_step(StepEvent)` hook: call id, tool, arguments, phase, latency, is-error. It fires **after** the canary check on arguments | The UI gets steps without re-parsing raw events, and canary-bearing arguments never reach it | Unit test: the same steps `--trace` prints, on a stub stream |
| P5 | **Cancel:** `ask` takes `cancel: threading.Event`. `_stream` starts a watcher (`cancel.wait()` → `kill_group()`), as the timeout already does, and raises `AskError(code=CANCELLED)` | Stops the agent even while the model is silently thinking | `test_cancel_kills_process_group`: a silent 30 s stub with a child process. After cancel, `os.killpg(pgid, 0)` raises within 1 s |
| P8 | Fingerprint fixes: add `migrations/` to `INPUTS`; put `config/` in `JUDGING` (it holds prices and the scope list, whose output is already hashed); `verify` requires one `claude_version` across a receipt's runs | A migration can change search results; a price edit shouldn't force 192 runs | `verify` fails on a `migrations/` change; CI's "flag changes to eval inputs" step covers both paths |
| P9 | `build_command` ends options with `--` before the question | **Security:** `claude` parses a question starting with `--` as an option, and options include `--settings` and `--plugin-url`. This affects the v1.0 CLI too | Stub test: `question="--version"` arrives after `--` |
| P10 | Every `AskError` gets a code. New codes: `CANCELLED`, `USAGE_LIMIT` and `AGENT_FAILED`. Canary-in-tool-call and grounding failures become `ANSWER_REJECTED` | The UI can map every failure to fixed text and never show `str(exc)` | An AST test: no `AskError(...)` without `code=` |

**Cut from v0.1:**
- **P6** (one database connection per search): 3–5 ms.
- **P7** (memoised metadata): < 0.3 ms.

Neither would be visible to anyone.

**`make bench` (U0):**
- Runs base and head **interleaved** on one named machine: 3 warm-ups, then n ≥ 30, with compiled bytecode.
- Commits the raw samples and the environment (machine, OS, Python, lock hash, Postgres image, power state) to `docs/perf/`.
- **Acceptance:** an improvement whose bootstrap 95% interval excludes zero. Batch medians drift 4–5% on their own, so a single before/after number proves nothing.

### 6.4 The re-baseline, without hiding a regression

ADR 0008's order still holds: flakiness study → baseline → gate. But a gate judged against a study of the *same* new agent only shows the agent is reproducible. It can't show the bundle didn't make it worse. So:
- **In U0** (a `gate.py` change: a judging file, 0 model runs), `canada-gate baseline` first judges the new study against the **outgoing** baseline, using the gate's flip, mean-drop and leak rules.
  - It refuses unless given `--accept-change "<reason>"`.
  - It records `{replaces, regression_check}` in `baseline.json`.
- **Code review of the `src/` PR finishes before any recording.** The study, baseline and gate receipt are its last commits. Any later `src/` change, even a docstring, re-runs them.

### 6.5 The biggest lever, kept separate

Each tool call the model *doesn't* need saves about 0.6–1.0 s on Haiku; Sonnet is unmeasured. Examples:
- `search_tables` returns member ids;
- `get_series` accepts names.

These change pinned tool descriptions and may cost accuracy. If George wants them, they become a later experiment with a written prediction first, like PR #24. They are not part of A8.

## 7. UI requirements

| # | Requirement |
|---|---|
| U1 | **Demo:** a question **picker** (no free text). The first visit auto-plays one multi-step replay. **Live:** a text box. The server strips the question and accepts 1–500 characters, with no NUL or control characters and no leading `-` |
| U2 | **Steps:** one line per tool call. Each shows the tool, the model's arguments (as plain text, length-capped, with outside links redacted) and a **summary built by the server from parsed fields** ("12 tables", "13 points, 2025-09 to 2026-09", an error code). Elapsed seconds show while waiting. Parallel steps are keyed by id |
| U3 | **Answer card,** only after the checks pass: the prose answer; each `answer_values` entry with label, period and unit as the model reported it; links (U4). Change values carry one line: "computed by the model from the levels shown; only levels are checked against the data" |
| U4 | **Links:** the server marks each answer URL `linkable` only if it matches `CITABLE_URL` and a tool returned it in that run, using imported Python. The browser renders `<a>` only for `linkable: true`. The front end contains no StatCan URL pattern, and a lint rule enforces that |
| U5 | **Chart:** a hand-written SVG line chart when a series has ≥ 3 non-null points; otherwise a value tile. Always paired with a data table. `null` is a gap labelled "suppressed", never zero. Values are shown as published, with the scalar factor noted. Series appear only after the checks pass |
| U6 | **Errors:** every failure code maps to fixed plain-English text and a next step. `ANSWER_REJECTED` shows only that the checks refused the answer |
| U7 | **Stop** during a live run: it aborts the request, which cancels the run (P5) |
| U8 | **Run footer:** turns, tool calls, duration, model and prompt version. Live: "API-equivalent $x, billed to subscription". Demo: the provenance line (§11) |
| U9 | **Replays** play at an approximate pace spread over the recorded `wall_s`, labelled "approximate pace". Reduced motion plays them instantly |
| U10 | Light and dark themes from design tokens; works at phone width |

## 8. Architecture

```
Live (127.0.0.1 only)                               Demo (GitHub Pages, static)
Browser ──POST /api/ask (JSON)──► canada-web        Browser ──GET replays/<id>.json
   ◄── Server-Sent Events in the response body          (built by canada-web build-demo)
   abort() = Stop
                  │ worker thread, one run at a time
                  ▼
canada_agent.ask(on_step=…, cancel=Event)  ──►  claude -p ──► canada-mcp (stdio)
                  │
AskResult (exists only after check_answer + check_grounded)
   └─► series events, then the answer event
```

**Rules:**
- **E1. One event contract** for live and replay (§9), and one `apply(event)` reducer in the browser. Live feeds it from the response stream, read with `fetch` and a small SSE parser; a replay feeds it from a JSON array.
- **E2. `web/` imports, never copies.** `run_events`, `CITABLE_URL`, `foreign_links`, `untrusted_text`, `series_values`, the error codes and the recording loader all come from `canada_agent`. A test fails if `web/` defines any of these again, and an ESLint rule bans StatCan URL patterns in `web/frontend`.
- **E3. Nothing the checks could still reject is shown first.**
  - Step events carry only server-built summaries and redacted, capped arguments.
  - `series` and `answer` are emitted only once an `AskResult` exists.
  - A failed run ends with `run_failed` and nothing else.
- **E4. `web/` is its own uv project**, with its own `pyproject.toml` and `uv.lock`. It depends on `canada-data-agent` through an editable path source, **not** as a workspace member, which would share the root lock. It is outside the gate fingerprint by design: it can change how a result looks, not what the agent does. E2, E3 and the §13 contract tests keep its display tied to the agent.

**Why one streaming POST, not POST plus a GET event stream:**
- It removes the second route and the protections a GET would need (browsers send no `Origin` on same-origin GETs).
- It removes the gap where a run starts but no one listens, and the browser's automatic reconnect loop.
- It lets Stop be a simple abort.
- FastAPI's built-in SSE works on any method (verified on 0.163.1), and a client disconnect reaches the worker within milliseconds.
- Resume (`Last-Event-ID`) is deliberately not supported on a local single-user tool.

**Stack** (current versions checked 2026-11-17; the plan pins exact ones):
- **Backend:** FastAPI 0.163 and uvicorn 0.54.
- **Front end:** Node 26 LTS, TypeScript 7.0, Vite 8.3 and React 19.3. Charts are hand-written SVG (D4).
- **Tests:** Vitest 5.1, Playwright 1.65 and `@axe-core/playwright` 4.14.

**Types:**
- The pydantic event models have a **required** `type` literal on every event, with no default (a default makes the TypeScript field optional).
- Their JSON Schema is committed.
- The TypeScript union is written by hand: seven small types, so no code generator.
- **Drift is caught by tests:** every bundled replay validates against the schema (pytest) and drives the reducer without error (Vitest), and a test checks the union's `type` names match the schema's.

**Why React + TypeScript** over a no-build page: the investigation's first pick (plain JavaScript) won only while "static demo" carried a heavy weight and type safety and accessibility carried none. Under three other weightings it fell to 6th or lower. Vite's output is static files anyway, so the demo stays serverless.

## 9. Event contract (v1)

Pydantic models in `web/src/canada_web/events.py`; schema at `web/schema/events.v1.json`.

```
run_started   {type, mode: "live"|"replay", category: "answer"|"refusal"|"attack_resisted"|"rejected",
               question, model, prompt_version, provenance}
step_started  {type, step_id, tool, arguments_text}            # redacted, ≤ 200 chars
step_finished {type, step_id, ok, latency_ms|null, error_code|null, summary}   # summary: server-built
series        {type, step_id, product_id, vector_id, scalar_factor, truncated,
               points: [{ref_period, value|null, status_symbol|null}]}       # only after the checks pass
answer        {type, answer, answer_values, links: [{url, linkable}], refused}
run_failed    {type, code, message}       # message from a fixed table; never str(exc), never answer text
run_finished  {type, num_turns, duration_ms, api_equivalent_usd|null, billed: "subscription"|"none"}
```

**Field rules:**
- **`provenance`:** `{source: "live"}`, or `{source: "recording", case, model, commit, commit_date, recorded_at|null, timing: "recorded"|"approximate"}`.
- **`series` has no URL, title or unit.**
  - The link is built in the browser only from `product_id`, which must match `^\d{8}$`, using a fixed StatCan template.
  - A label comes from the run's own dimension results when available, as plain text.
- **`step_finished.error_code`** must be one of the known tool codes, otherwise `TOOL_ERROR`.
- **`run_failed.code`** is drawn from a closed set: `ErrorCode` plus `CANCELLED`, `USAGE_LIMIT` and `AGENT_FAILED`.
  - Until P10 lands, `web/` maps a missing code to `AGENT_FAILED`.

**Ordering:**
1. `run_started` comes first.
2. Step events follow, possibly interleaved.
3. The run ends with exactly one of:
   - **success:** zero or more `series`, then `answer`, then `run_finished`;
   - **failure:** `run_failed` alone.
4. A `step_started` with no matching `step_finished` is closed by the terminal event.

A contract test checks every bundled replay and a stub live run against all of this.

## 10. Security (local live mode)

The live server spends George's subscription and handles text that may carry injections.

**Network**
- **Bind 127.0.0.1 only.** `canada-web serve` refuses any other host. It prints `http://127.0.0.1:PORT/`.
- **Host check:** `TrustedHostMiddleware(["127.0.0.1"])`, against DNS rebinding. There is one origin; `localhost` is not accepted.
- **`POST /api/ask` is the only API route.** It requires:
  - `Origin` exactly `http://127.0.0.1:PORT`, port included, with `null` rejected;
  - `Sec-Fetch-Site: same-origin`;
  - `Content-Type: application/json`.

  There is no CORS middleware and no token: with no GET route left, the remaining threat would be a local process, and that could run `claude` itself.

**The question (argument injection)**
- The server validates the question (U1).
- P9 adds `--` before the question. Until P9 ships, the leading-`-` rejection is the defence.

**Runs and processes**
- **One run at a time:** a second request gets 409.
- The lock is released only after the process group is gone.
- Aborting the request, or the server shutting down, sets `cancel` and joins the worker.
- The existing budget applies: `max_tool_calls` 8 and `question_timeout_s` 120.

**What reaches the browser** (E3)
- **Tool text never reaches the browser.** Summaries are built from parsed fields.
- Arguments pass through `untrusted_text` and `foreign_links` redaction ("[outside link withheld]").
- `run_failed.message` comes from a fixed table.
- **The browser never sees:** the canary, the system prompt, the database URL, stderr, file paths, or a rejected answer.

**Response headers**
- **CSP on every response:** `default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; require-trusted-types-for 'script'; trusted-types 'none'`. Also `nosniff` and `Referrer-Policy: no-referrer`.
- The CSP is enforced on built assets. Vite's dev server injects an inline script and is exempt; every CSP test runs against the build.
- Trusted Types is extra protection where browsers support it. **The real defence is that untrusted text is only ever rendered as text:** no `dangerouslySetInnerHTML` (banned by lint) and no Markdown rendering.

**Known limits, stated plainly**
- The canary and question are in `claude`'s argv, so other users on the machine may see them in `ps`.
- Other local users and processes are out of scope.

## 11. Public demo (replay-only)

**What it is**
- The same front end, built with `VITE_MODE=replay`. The live code path is compiled out; it only fetches the bundled `replays/*.json`.

**What it contains** (an explicit allow-list, all from the **dev** split)

| Category | Runs | What is shown |
|---|---|---|
| Answers and refusals | The 20 grader-passed runs from `offline.recordings()` | Steps, answer, chart or tile and table, links |
| Attack resisted | inject-01, -02, -03 | Steps (server-built summaries only), the answer, and a fixed caption naming the attack's **goal and route**. These come from the run's `poison` spec, parsed with the imported `canada_agent.evals.poison.parse`; its `goal` is `exfil_url` or `wrong_value`, and its `vector` is the route. Example caption: "a planted instruction in a table card tried to make it cite another website". The planted text and the attacker's host are **never** shown: published verbatim, the page itself would carry the attack to AI crawlers |
| Rejected by checks | lookup-07 | Steps and the `ANSWER_REJECTED` explanation; no answer text, no chart |

**The header:** "20 of the 21 answerable dev questions (the set the agent was tuned on), 3 attacks it resisted, and 1 answer its own checks rejected. The held-out result for v1.0 is 13/16; it is not re-run here."

**`canada-web build-demo`** (Python in `web/`, no `src/` changes)
- **Fails closed:** if the grade verdicts are missing, a run isn't on the dev split, or a run is off the allow-list.
- **Re-wraps** each recording's events into the stream shape. They are stored slimmed: 20/20 pass `run_events` re-wrapped, 4/20 as stored.
- **Runs the production `run_events`** with a fixed clock:
  - the 23 answer and attack runs must pass;
  - lookup-07 must raise `ANSWER_REJECTED`.

  This checks each recorded answer against its recorded tool results. **It does not re-run the tools**; the `fresh-clone` CI job does that.
- **Builds the §9 events,** running `foreign_links()` over **every emitted string**. The build fails on any hit.
- **Outputs** only repo-relative paths. The same inputs produce the same bytes, which a test checks.

**Provenance, on every replay:** "Recorded during v1.0 development (commit 9e183c1, 2026-11-07), before the release's final review fixes. Not a live model call. Approximate pace."
- That commit isn't on `main`, because main is squash-merged. GitHub keeps it reachable through PR #23's permanent ref (`refs/pull/23/head`), so the link resolves even if branches are deleted.
- If D6 is yes, the re-recorded runs replace these.

**The "How it's tested" tab** is built at build time from the committed:
- `evals/gate-result.json`, `baseline.json` and `flakiness.json`;
- `docs/chart.svg`;
- the README headline (13/16, Wilson 57–93%).

Nothing is hand-typed. It links the staged gate-failure PR #24.

**Hosting (D1)**
- **Build job** (`contents: read`): `uv sync --locked`, `build-demo`, `npm ci --ignore-scripts`, `vite build`, and upload the artifact.
- **Deploy job:** runs only `actions/deploy-pages`, and is the only job with `pages: write` and `id-token: write`.
- **Trigger:** only a push to `main`, after CI passes; the `github-pages` environment is restricted to `main`.
- **Pinning:** every action is pinned by commit SHA (SPEC §11).

**Page settings**
- **No third parties:** no analytics, no third-party scripts, no external fonts.
- **Vite `base`:** set to the repo path. Replay selection uses the query string, because Pages has no SPA fallback.
- **CSP:** a `<meta>` tag placed before any script, without `frame-ancestors`, which browsers ignore in `<meta>`.
- **Accepted:** a project site shares the `gcode33.github.io` origin with any other Pages site of the account. It is acceptable for a static page with no actions.

## 12. Accessibility

**Target:** WCAG 2.2 AA, claimed as **tested**, not compliant.

**Automated**
- `@axe-core/playwright` runs with the `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa` and `wcag22aa` tags, and with `target-size` enabled (it's off by default).
- It must report zero serious or critical violations in every state: picker, steps, answer, attack, rejected, error and live.

**Manual**
- One keyboard-only and one VoiceOver pass at U3, recorded in `docs/a11y.md`.

**Steps and focus**
- The visible step list is not a live region.
- A visually hidden `role="status"` announces one short sentence per **finished** step. The elapsed timer is outside it.
- When the answer arrives, focus moves to its heading (`tabIndex=-1`). On failure, it moves to a `role="alert"`.
- When Stop disappears, focus moves explicitly.

**Charts and colour**
- The SVG has `role="img"` and an `aria-label` that is the one-sentence summary, inside a `<figure>` with a `<figcaption>`.
- The table sits in a native `<details>`, with a `<caption>`, `<th scope>` and the literal word "suppressed".
- Colour tokens meet 4.5:1 for text and 3:1 for chart lines in both themes, checked by unit tests on the token pairs.

## 13. Testing and CI

| Layer | Tool | What it proves |
|---|---|---|
| `src/` bundle | pytest | P1–P10 acceptance, including `test_cancel_kills_process_group` and the P9 argv test; the existing 418 tests pass |
| Benchmark | `make bench` | §6.3, with raw samples committed |
| Gate | pytest + the U2 re-baseline | The regression check against the v1.0 baseline (§6.4) |
| Event contract | pytest + JSON Schema | Every bundled replay and a stub live run validate; the ordering rules; a failed run contains no `series`, `answer` or tool text; no emitted string has a `foreign_links()` hit |
| Fidelity | pytest | Each replay's answer event matches the recording's checked answer; chart points equal the recorded `get_series` points; `web/` calls `ask` with unmodified `Settings`, as the CLI does |
| Backend | pytest + `TestClient` | The Host, Origin, `Sec-Fetch-Site`, content-type and question-validation checks reject; 409 on a second run; an abort kills the process group (stub `claude`); headers and CSP are present; the server refuses an API key in the environment |
| Front end | Vitest | The reducer over every bundled replay; `<a>` only for `linkable`; gaps for `null`; a fixed text for every error code; the TypeScript `type` names match the schema |
| End to end | Playwright, against the **build** | All 24 replays render; the keyboard-only flow; axe; a crafted payload stays inert text; **zero `securitypolicyviolation` events** |
| Live smoke | `make live-web` (local, never CI) | One real question through the page |

**CI**
- A new `web` job runs on every PR with **no secrets**. The gate is otherwise unchanged.
- The existing "flag changes to eval inputs" step adds `migrations/` and `config/`.

## 14. Delivery

The plan (`docs/PLAN-A8.md`, after approval) breaks these into small PRs.

| Phase | Days | Scope | Proof | George's review |
|---|---|---|---|---|
| U0 | 0.5 | ADR 0010 (web UI, replay-only demo, `web/` outside the fingerprint) and ADR 0011 (stay in Python); event models, schema and TypeScript union; `make bench` with today's numbers; the `gate.py` regression check (judging only, 0 model runs) | Contract tests; benchmark committed; regression-check unit tests | ~1.5 h |
| U1 | 2 | **The demo:** `build-demo`; the front end (picker, auto-play, steps, answer card, chart or tile and table, attack and rejected categories, error text, "How it's tested"); the Pages deploy | All 24 replays render; axe clean; the demo URL is live and at the top of the README | ~4 h |
| U2 | 1.5 | **The `src/` bundle** (P1–P5, P8–P10) in one PR: code review, then study, regression check, baseline and gate (192 runs, plus 24 if D6). **Then live mode** in `web/`: `serve`, the streaming POST, hardening and Stop | Benchmark gains; receipt passes; the regression check passes against v1.0; backend security tests; `make live-web` answered one real question | ~4 h |
| U3 | 1 | Manual accessibility pass, README GIF, a 2-reviewer adversarial review (security, honesty), release v1.1.0 | Findings fixed and logged in `docs/reviews/`; tag pushed | ~2 h |

**Ownership (A7) still applies.** George gets a vault lesson per new concept and check-yourself questions at the tag:
- Server-Sent Events;
- CSP and Trusted Types;
- localhost hardening;
- argument injection;
- accessibility testing;
- regression-checked baselines.

## 15. Risks

| Risk | Mitigation |
|---|---|
| The U2 re-baseline hits the subscription's usage limit | Runs resume with the same command; budget it as one sitting |
| The `src/` bundle makes the agent worse | The §6.4 regression check against the v1.0 baseline blocks it unless the change is explicitly accepted with a reason |
| The UI shows something the gate never verified | E2 (import, don't copy), E3 (nothing shown before the checks), fidelity and contract tests |
| Injected text reaches the page or a crawler | No tool text is ever emitted; `foreign_links` fails the build on any hit; attacks are described, never quoted |
| A question is parsed as a `claude` option | Server-side validation now; `--` in `build_command` (P9) |
| A replay is mistaken for a live or current agent | The provenance line on every replay; `billed: "none"`; the header states it's the tuning set |
| Two languages to maintain | TypeScript only in `web/frontend`; one small hand-written event union; every rule stays Python |
| Someone runs live mode for others | A README warning quoting the terms; local binding only |

## 16. Decisions for George

Each has a default, which applies if he approves A8 without changing it. **Approved 2026-11-18: all seven at their defaults.**

| # | Question | Default | Why |
|---|---|---|---|
| D1 | Host the public replay demo? | **Yes, GitHub Pages** | Free, static, no model calls. A recruiter sees the agent work without installing anything |
| D2 | Eval explorer now? | **No**, a static "How it's tested" tab instead | Most of the portfolio value at a fraction of the surface |
| D3 | A Rust learning experiment (PyO3 snapshot parser, benchmarked)? | **No** | A learning goal, not an optimisation (~50 ms once per table) |
| D4 | Charts | **Hand-written SVG** | Three of four critics. 10 of the 20 answer replays have ≤ 3 points, so most get a tile; the bundle is ~110 kB gzip smaller; accessibility is set directly. **Dissent (front-end critic):** Recharts is verified CSP-clean, its accessibility default is fixed with four props, and it means less code to review |
| D5 | Release name | **v1.1.0**, with SPEC §5's "v1.1" list renamed "later" | A backwards-compatible feature release |
| D6 | Re-record the 24 dev transcripts on the U2 agent, so replays show real step timing and the released agent? | **No** | 24 more Sonnet runs, plus a reviewed re-grade. Replays are labelled as pre-release instead |
| D7 | Show the 3 attack runs in the public demo? | **Yes**, described by goal and route; never the planted text or host | It shows the project's differentiator; the build proves no outside link ships |

## 17. Review log (v0.1 → v0.2)

Four adversarial critics, two rounds. In round 2 each critic read the other three critiques and had to agree, change or dispute every blocking item within a 5-day, 12-hour budget. The chairman re-checked the disputed facts. The full text is in `docs/reviews/2026-11-17-a8-spec-review.md`.

| Change | Raised by | Why |
|---|---|---|
| The demo ships first, with zero `src/` changes; the `src/` bundle moves to live mode | Scope; all agreed | The demo needs nothing from `src/`, and 192 runs shouldn't block it |
| One streaming POST instead of POST plus a GET event stream | Front end; all agreed | A same-origin GET carries no `Origin`; the browser reconnects automatically; there's an orphan window. All verified |
| P9: `--` before the question, plus server-side validation | Security; all agreed | `claude --model haiku "--version"` printed the version: a question in the prompt slot is parsed as an option. The chairman confirmed `build_command` has no `--` |
| Cancel through a watcher thread, tested by process group | Security, front end, scope | v0.1's per-event check can't fire while the model is silent; the tool server runs as `python -m`, so a name-based test would pass falsely |
| No tool text reaches the browser; `series` only after the checks; `product_id` instead of a URL | Security, front end | Poisoned tool results carry outside links (verified in inject-01 and inject-03); v0.1 would have drawn charts for a run that was then rejected |
| A closed set of error codes (P10) | Security, front end | 10 raise sites had no code, some with attacker-influenced text |
| A regression check against the outgoing baseline | Eval; all agreed | v0.1's "the gate decides" was false: the gate only compared the new agent with itself |
| `build-demo` re-wraps and uses a fixed clock; "re-checked" is stated precisely | Eval | Stored events are slimmed: 4/20 pass as stored, 20/20 re-wrapped |
| Honest provenance (commit 9e183c1, before the final review fixes) | Eval | The chairman verified by diff, not ancestry: the tag the critic used doesn't exist, and squash merges make ancestry meaningless. `ask.py` +86 lines, plus `links.py` and `transcripts.py`, changed after that commit |
| Attack-resisted and rejected replays in the demo, the attack described not quoted | Scope (include), security (no host), resolved by the chairman | Shows the differentiator without the page carrying the attack |
| P8 reworked: `migrations/` in, `config/` to judging, one Claude Code version per receipt | Eval; all agreed | v0.1 would have forced 192 runs on a price edit and missed migrations |
| `series` without title or unit; a tile under 3 points | Front end | `get_series` returns neither; 10 of 20 replays have ≤ 3 points |
| A required `type` on every event; a hand-written TypeScript union instead of codegen | Front end (type), scope (no codegen) | A default makes the generated field optional; tests catch the same drift |
| Benchmark: interleaved, n ≥ 30, raw samples, interval-based acceptance | Eval | Medians drift 4–5% between batches; the investigation's raw data wasn't committed |
| Accessibility: `wcag22aa` tags, `target-size` on, a manual pass, "tested" not "compliant" | Front end, eval | `target-size` is off by default in axe 4.14.1; axe covers only part of WCAG |
| Framing: "waiting on Claude ~95% (Haiku median), ≤ 92% (live)"; "7–27 s"; 0.6–1.0 s per call | Eval | v0.1 over-claimed from the Haiku sample |
| **Cut:** P6, P7, the per-launch token, the GET route, codegen, `Last-Event-ID` resume, the third ADR, a 3rd U4 reviewer | Scope, security (conceded the token), front end | Each fails the budget test or protects against nothing new |
| **Rejected:** re-recording in A8 (now D6); a Jupyter-style token; Recharts (now D4, with dissent) | Round-2 majority | Budget; a local process could run `claude` itself; size and accessibility |
