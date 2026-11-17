# Amendment A8: Web UI and performance

Status: **draft v0.1 for George's review, 2026-11-17.** It amends `SPEC.md` v1.0 (with A1 and A7) and builds on ADR 0009. Nothing here is approved until George says so. The decisions waiting on him are in §16.

Evidence:
- `docs/reviews/2026-11-17-stack-investigation.md`: an Opus orchestrator with three sub-investigators, all measured offline.
- `docs/reviews/2026-11-17-stack-review.md`: a Sonnet adversarial reviewer.

Where the two disagree, §17 says which one A8 follows and why. The rule for choosing was **what fits this application**, not what job postings ask for.

## 1. In plain words

Today the agent lives in a terminal. A8 adds two things.

1. **A web page that shows the agent working.** You type a question. Each step appears as it happens: which tables it searched, which series it fetched and how long each call took. Then the answer arrives with its numbers, a chart of the data and links to the StatCan tables.
   - A live question takes 10–30 seconds (a recorded Sonnet run took 26.7 s), so seeing the steps matters.
   - **Live mode runs only on George's own computer**, on his Claude subscription.
2. **A public demo anyone can open.** It replays the agent's recorded runs through the same page, clearly labelled as replays. It never calls Claude, so it costs nothing and stays inside Anthropic's terms (§4).

It also makes the Python faster where measurement says it's worth it. It does **not** rewrite anything in another language: Claude's thinking is about 95% of every question, and all our own Python together is a few percent (§6).

## 2. What changes in SPEC v1.0

| SPEC v1.0 | A8 |
|---|---|
| §3 "No chat UI or hosted site" | A **local web UI** (live) and a **static public replay demo**. There is still no hosted live mode |
| §4 Users: George, MCP clients, CI | Adds **visitors to the public demo** (read-only, replays only) |
| §6 Stack: Python only | Adds a TypeScript front end in `web/`. All agent code stays Python |
| §5 "v1.1" feature list | Renamed **"later"**, because A8 ships as release **v1.1.0** (decision D5) |
| §12 Observability | Recorded runs keep **per-event timestamps**, so replays can show step timing |

Everything else in SPEC v1.0 still holds: the tools, the graders, the gate rules, the held-out test rule and the security rules.

## 3. Goals and claims

| Claim | Evidence a reviewer can check |
|---|---|
| I measure before I optimise | The latency budget (§6.1), a committed offline benchmark (`make bench`) with before and after numbers, and the decision **not** to rewrite, with its reasons |
| I can build a streaming AI interface | Live steps over Server-Sent Events, one event contract shared by live and replay, and a cancel that really stops the agent |
| The UI can't show what the checks rejected | The answer card is built only from a result that passed `check_answer` and `check_grounded`; tests prove a rejected run shows only its error code |
| I take security in a local tool seriously | Localhost-only binding, Host and Origin checks, a strict CSP with Trusted Types, and untrusted text never rendered as HTML (§10) |
| I build accessible interfaces | WCAG 2.2 AA target, a data table for every chart, and automated accessibility checks in CI (§12) |

## 4. Constraints

- **No API billing** (ADR 0009). Live mode runs `claude -p` on George's subscription. There is no API key path.
- **Anthropic's terms:** "Anthropic does not permit third-party developers to … route requests through Free, Pro, Max, or Ultra plan credentials on behalf of their users" (code.claude.com/docs/en/legal-and-compliance, checked 2026-11-17). So:
  - live mode serves **one person, on his own machine**;
  - the public demo **never calls a model**.
  - Letting a friend use the live mode would also break this rule. The README says so.
- **The eval gate** (ADR 0008):
  - Any change under `src/canada_agent`, `pyproject.toml` or `uv.lock` changes `agent_hash`. That needs a new flakiness study (k=5), a new baseline and a new gate run (k=3), which is 192 `claude -p` runs.
  - A8 batches **all** of its `src/` changes into one PR, so that cost is paid once (§6.3).
- **The held-out test split** never runs again, and **no test-split recording appears in the demo**.
- **No new paid services.** Voyage stays on the free tier, and hosting is free (decision D1).

## 5. Non-goals (A8)

- **No hosted live mode.** No logins, no accounts and no multi-user anything.
- **No rewrite in Rust, Go or TypeScript**, and no mixing in hand-written Rust or Go for speed. §6.2 has the numbers. An optional Rust learning experiment is decision D3 and stays outside the agent.
- **No token-by-token answer streaming.** The answer appears only after the runtime checks pass (§8, rule E3).
- **No multi-turn chat.** Each question is its own isolated run, as today.
- **No eval explorer yet** (browsing runs, gate receipts, flakiness). The architecture leaves room for one (decision D2), but A8 doesn't build it.
- **No server-side rendering framework.** The backend is Python, so Next.js, Remix and similar would duplicate it.
- No tool-description or prompt changes. Cutting model round trips is the biggest latency lever, but it can cost accuracy and needs its own pre-registered experiment (§6.4).

## 6. Performance

### 6.1 Where the time goes (measured 2026-11-17)

| Part of one question | Time | Source |
|---|---|---|
| Whole question, Haiku eval runs (median of 761; 24 dev questions repeated) | 9.8 s (p95 15.6 s) | `evals/runs` |
| Whole question, Sonnet dev transcripts (n=24) | 7.45 s | `evals/transcripts/dev` |
| **One live Sonnet question** | **26.7 s** | `docs/demo/ask-trace.txt` |
| Claude's own time (inside the above) | ~95% | `duration_ms` |
| Process start and teardown (`claude -p` plus our tool server) | ~0.5 s | wall minus `duration_ms` |
| Our tool server: start to ready (on the critical path; Claude Code waits for it) | 0.25 s, mostly `import mcp` | handshake benchmark |
| CLI start (`import canada_agent.ask`), ~0.2 s of it importing `mcp_server` for one constant | 0.28 s | `-X importtime` |
| All tool calls in one question, offline | ~33 ms | in-process benchmark |
| Live network inside tools (Voyage search, StatCan fetch) | ~2 s | one live trace |
| Runtime checks (canary, links, grounding) | < 1 ms | benchmark |

**What follows:** all our own Python CPU is about 0.3–0.55 s of a 7–27 s question. Over 90% of it is importing modules.

**Caveat:** the live figures (26.7 s, ~2 s network) come from one trace. U1 adds per-event timestamps (§6.3, P3), so future runs measure this properly.

### 6.2 Decision: stay in Python (ADR 0011)

| Option | Best-case saving per question | Cost |
|---|---|---|
| Tool server in Go or Rust | ~0.23 s (start-up only) | Rewrite ~2,100 lines (the server plus search, StatCan client and snapshot); re-pin the tool snapshot; re-baseline; a second copy of security rules |
| Search in Rust | ≤ 5 ms offline; 0 live (network-bound) | Same, for no visible gain |
| Snapshot parsing in Rust | ~50 ms, once per table | A build toolchain per platform |
| Checks or stream parsing in anything | < 1 ms | – |
| **All of the above** | **~0.3 s of 10–27 s (1–3%)** | Three toolchains, three test setups, cross-language boundaries |

- **Two security rules stay in one language.** The link filter (`links.py`) and the canary/grounding checks are shared by the runtime and the graders. The adversarial review showed the filter *can* be ported to JavaScript (0 mismatches over 30,000 fuzzed strings once `\w` was rewritten as Unicode classes). But two implementations of a security rule can drift apart, and that is reason enough.
- **Rust is already here where it pays:** `pydantic-core`, `jiter` and `rpds-py` are Rust, and `psycopg-binary` is C.
- **If a CPU hotspot ever appears in a profile**, the order is:
  1. a Rust-backed library;
  2. one small benchmarked PyO3 extension;
  3. never a rewrite.

### 6.3 The U1 performance bundle (one PR, one re-baseline)

Every change under `src/` in A8 lands together, so the gate is re-baselined once.

| # | Change | Expected gain | Acceptance (measured by `make bench`, offline) |
|---|---|---|---|
| P1 | Move `SERVER_NAME` to a tiny module, so `ask.py` and `offline.py` no longer import `mcp_server` just for that constant | ~0.2 s per CLI question | `import canada_agent.ask` median ≤ 0.12 s (from 0.28 s) |
| P2 | Lazy-load what the tool server needs only on some calls (`psycopg`, `yaml`, `zipfile`, `csv`) | 50–70 ms per question | Handshake median ≤ 0.21 s (from 0.247 s) |
| P3 | **Per-event timestamps:** `_tee` stamps each captured event with `t_ms` (ms since the run started), and `transcripts.slim()` keeps it | Enables live-latency measurement and replay timing | New recordings carry `t_ms`; old ones replay as "timing not recorded" |
| P4 | **A structured step hook:** `run_events`/`ask` gain `on_step(StepEvent)`, with call id, tool name, arguments, phase (started/finished), latency and is-error. The string `on_event` stays for `--trace` | Lets the UI show steps without re-parsing raw events | Unit tests: the same steps for a stub stream as `--trace` prints |
| P5 | **Cancel:** `ask` gains `should_stop: Callable[[], bool]`, checked on every event; a stop raises `AskError` with the new code `CANCELLED`, and `_stream`'s `finally` kills the process group | A closed tab or a Stop click ends the run and its tools | A test proves no `claude` or `canada-mcp` process survives a cancel |
| P6 | One database connection per `search_tables` call (today `search()` and `cards()` each connect) | 3–5 ms offline, up to ~20 ms live | In-process `search_tables` median ≤ 6 ms |
| P7 | Memoise parsed `metadata` per table in the snapshot and live backends | < 0.3 ms offline; one StatCan round trip saved live | Unit test: the second call doesn't re-parse or re-fetch |
| P8 | Close the gate's fingerprint gaps: add `config/` to `INPUTS` and record the `claude --version` in the receipt | Honesty, not speed | `canada-gate verify` fails when `config/` changes |

**Rejected:** a long-lived `claude` session or tool server (it breaks per-question isolation and the per-run canary, and HTTP transport reverses ADR 0005); `--bare` mode (it needs API billing).

**Deferred to a measured follow-up:** pre-starting the next `claude -p` so its ~0.5 s start overlaps with typing. It is untested, and it changes how the question and canary are passed.

### 6.4 The biggest lever, kept separate

Each tool call the model *doesn't* need saves about 0.6–1.0 s on Haiku; Sonnet hasn't been measured. Examples:
- `search_tables` returns matching member ids, so `get_table_dimensions` isn't needed;
- `get_series` accepts member names.

These change pinned tool descriptions and may cost accuracy. If George wants them, they become a later experiment with a written prediction first, like PR #24, and the gate decides. They are **not** part of A8.

## 7. UI requirements

| # | Requirement |
|---|---|
| U1 | Ask a question in a text box; submit with Enter or a button. The server rejects questions over 500 characters (a new limit: the CLI has none today, and a question goes into `claude -p`'s argv) |
| U2 | **Steps stream live**, one line per tool call: tool, its arguments in readable form, then ok or error with latency. Waiting time shows as elapsed seconds, so 26 s never looks frozen |
| U3 | **Answer card**, shown only after the run passed the runtime checks: the prose answer; each `answer_values` entry with its label, period and unit; and the source points it came from (period and value from the `get_series` results in that run) |
| U4 | **Citations:** only URLs that match `CITABLE_URL` *and* that a tool returned in that run are links. Anything else is plain text |
| U5 | **Chart** for each fetched series: line over time, with `null` shown as a gap labelled "suppressed", never zero. At most 120 points (the tool's cap). Always paired with a data table (§12) |
| U6 | **Errors:** every `ErrorCode` and `UsageLimitError` has a plain-English message and what to do next. `ANSWER_REJECTED` shows **only** the code and an explanation, never the rejected answer |
| U7 | **Stop button** during a live run (P5) |
| U8 | **Run footer:** turns, tool calls, duration, model, prompt version, and "API-equivalent $x, billed to subscription" (live), or the replay provenance (§11) |
| U9 | **Replay library:** pick any of the 20 replayable dev questions; it replays the steps at their recorded pace (or a fixed pace when timing wasn't recorded) and says so |
| U10 | Light and dark themes from design tokens; works at phone width; no layout shift when the answer arrives |

## 8. Architecture

```
Browser (web/frontend: Vite + React + TypeScript)
   │  POST /api/ask ─► run_id         GET /api/runs/{id}/events  (Server-Sent Events)
   ▼
canada-web (web/: FastAPI on 127.0.0.1)          Public demo: same frontend, built in
   │  worker thread, one run at a time            replay-only mode + replays/*.json
   ▼                                              (static files; no API, no model)
canada_agent.ask(on_step=…, should_stop=…, capture=…)
   │  claude -p (stream-json) ─► canada-mcp (stdio) ─► Postgres / StatCan
   ▼
AskResult (only after check_answer + check_grounded) ─► the "answer" event
```

**Event rules:**
- **E1. One event contract** for live and replay (§9). The browser has one `apply(event)` reducer. A live run feeds it from Server-Sent Events, and a replay feeds it from a JSON array.
- **E2. The backend imports, never copies.** `web/` imports `run_events`, `CITABLE_URL`, the error codes and the recording loader from `canada_agent`. A test fails if `web/` re-implements any of them, by grepping for the regex sources.
- **E3. The answer event is built only from an `AskResult`,** which exists only after the checks pass. Step events come from `on_step` and are labelled as progress: tool results may carry injected text, so they are shown as plain text and never interpreted.
- **E4. `web/` is its own uv project**, with its own `pyproject.toml` and `uv.lock`. It depends on `canada-data-agent` through a path source (`[tool.uv.sources]`, editable), **not** as a workspace member, which would share the root lock. Its code is outside the gate fingerprint by design: it can change how a result looks, not what the agent does. §13 says how its display is still tested against the agent.

**Stack (versions checked 2026-11-17; the plan pins exact ones):**
- **Backend:** FastAPI 0.163.x with its built-in Server-Sent Events (`fastapi.sse.EventSourceResponse`, since 0.135.0) and uvicorn 0.54.x.
- **Front end:** Node 26 LTS, TypeScript 7.0, Vite 8.3, React 19.3 and Recharts 3.10 (SVG, decision D4).
- **Tests:** Vitest 5.1, Playwright 1.65 and `@axe-core/playwright` 4.14.
- **Types:** generated, never hand-written. The pydantic event models export a committed JSON Schema, `json-schema-to-typescript` 16 generates `events.ts`, and CI fails if the generated file is stale.

**Why Server-Sent Events, not WebSockets:** data flows one way, plain HTTP is enough, it reconnects on its own, and there's no cross-site WebSocket hijacking to defend against.

**Why React + TypeScript over a no-build page:**
- The investigation's first pick was plain JavaScript with no build step. It won only while "static demo" carried a heavy weight and type safety, accessibility and room to grow carried none. Under three other reasonable weightings it fell to 6th or lower (review §4).
- Vite's build output is static files anyway, so the demo stays serverless.
- The types come from the Python models, so the browser can't drift from the backend.

## 9. Event contract (v1)

Pydantic models in `web/src/canada_web/events.py`; JSON Schema committed at `web/schema/events.v1.json`.

```
run_started   {run_id, mode: "live"|"replay", provenance, question, model, prompt_version}
step_started  {step_id, tool, arguments, t_ms|null}
step_finished {step_id, ok, latency_ms|null, error_code|null, summary}   # summary: plain text, length-capped
series        {step_id, vector_id, title, unit, points:[{ref_period, value|null}], source_url}
answer        {answer, answer_values, source_urls, refused, sources:[{vector_id, ref_period, value}]}
run_failed    {code, message}            # message is ours, never model text; never the rejected answer
run_finished  {num_turns, duration_ms, api_equivalent_usd|null, billed: "subscription"|"none"}
```

**How the events are built:**
- `provenance` = `{source: "live"}`, or `{source: "recording", path, model, recorded_on, git_sha, timing_recorded: bool}`.
- `series` comes from parsing the `get_series` result with a strict pydantic model. If parsing fails, there's no chart, and the answer card still shows its source points.
- **Ordering:** `run_started` comes first; the last event is exactly one of `run_finished` or `run_failed`; no event follows it. A contract test checks every replay file and a stub live run against this.

## 10. Security (local live mode)

The live server spends George's subscription and receives text that may carry injections. Treat it like a production endpoint:
- **Bind 127.0.0.1 only.** `canada-web serve` refuses any other host, even when asked.
- **Host header check** (`TrustedHostMiddleware`: `127.0.0.1`, `localhost`), against DNS rebinding. See the vault lesson *DNS Rebinding and Localhost Security*.
- **`POST /api/ask`** requires an exact `Origin` match, `Content-Type: application/json`, and a per-launch token. The token is set as a `SameSite=Strict`, `HttpOnly` cookie when the page loads. **No CORS middleware.**
- **One run at a time:** a second `ask` gets 409. A run has the existing budget (`max_tool_calls` 8, `question_timeout_s` 120), and **closing the event stream cancels it** (P5).
- **CSP on every response:** `default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; require-trusted-types-for 'script'; trusted-types 'none'`. Also `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`.
- **Untrusted text is text:**
  - no `dangerouslySetInnerHTML` (an ESLint rule bans it);
  - no Markdown rendering of model or tool text;
  - links are created only by the citation rule (U4), with `rel="noopener noreferrer"`.
- **The browser never sees** the canary, the system prompt, the database URL or raw stderr. `run_failed.message` is chosen from a fixed table per error code.
- **Logs:** the existing JSON log in `logs/ask.jsonl`. The server logs no request bodies beyond the question.

## 11. Public demo (replay-only)

- **What it is:** the same front end, built with `VITE_MODE=replay`. The live code path is compiled out, the API base is empty, and `connect-src 'self'` only fetches the bundled `replays/*.json`.
- **What it shows:**
  - The 20 replayable dev recordings (`offline.recordings()`: grader-passed, unpoisoned, current prompt).
  - **No test-split recordings and no injection runs.** A rejected run carries the attacker's answer inside `structured_output`, so it must never be bundled.
- **Built and checked by `canada-web build-demo`:**
  - every recording goes through the production `run_events` (no database, model or network needed), and a recording that fails the checks fails the build;
  - it is then converted to the §9 events.
  - The build is deterministic: same inputs, same bytes, which a test checks.
- **Labelled everywhere:** a banner reads "Replay of a recorded run (model, date). Not a live model call." Every replay's footer shows its provenance.
- **Hosting (decision D1):**
  - GitHub Pages, deployed by a workflow with `contents: read`, `pages: write` and `id-token: write`, and no other secrets.
  - It runs only on `main` after CI passes.
  - No analytics, no third-party scripts and no external fonts. The CSP comes from a `<meta>` tag, because Pages can't set headers. `frame-ancestors` doesn't work in `<meta>`, which is accepted for a static page with no actions.
- **An "About" panel** gives the v1.0 held-out result with its interval, links to the repo and the README, and says how to run live mode locally.

## 12. Accessibility

- **Target:** WCAG 2.2 AA.
- **Automated:** `@axe-core/playwright` in CI must report zero serious or critical violations on the ask, steps, answer, error and replay states.
- **Steps:** an `aria-live="polite"` region announces each step. Elapsed time updates don't announce.
- **Charts:**
  - every chart has a visible data-table toggle and a one-sentence text summary ("Rent index, Ontario, 2025-09 to 2026-09: 161.2 to 164.4");
  - suppressed values are marked by a label, not by colour alone.
- **Keyboard only:** ask, stop, open a source link and switch replays. A Playwright test does this with no mouse.
- **Motion:** `prefers-reduced-motion` turns off replay pacing animations.
- **Contrast:** colour tokens meet 4.5:1 for text in both themes.

## 13. Testing and CI

| Layer | Tool | What it proves |
|---|---|---|
| `src/` changes (U1) | pytest, as today | P1–P8 acceptance; existing 418 tests still pass |
| Benchmark | `make bench` (offline) | §6.3 numbers, with before and after committed to `docs/perf/` |
| Event contract | pytest + JSON Schema | Every replay file and a stub live run validate; event order rules; generated `events.ts` is fresh |
| Backend | pytest + FastAPI `TestClient` | Host, Origin, token and content-type checks reject; 409 on a second run; cancel kills the process group (stub `claude` binary); headers and CSP present; `ANSWER_REJECTED` sends no answer text |
| Front end units | Vitest | The `apply(event)` reducer; citation rule (only tool-returned StatCan URLs link); `null` → gap; error-code copy exists for every `ErrorCode` |
| End to end | Playwright | Replays of all 20 recordings render; the keyboard-only flow; axe checks; the CSP blocks an injected `<script>` in a crafted tool result; **zero `securitypolicyviolation` events** across every state (this is how D4's chart library proves it fits the CSP) |
| Live smoke | `make live-web` (local, never CI) | One real question through the page |

**CI:**
- A new `web` job runs on every PR with no secrets: uv sync of `web/`, pytest, `npm ci`, type check, Vitest, the demo build, and Playwright on the built demo.
- **The gate is unchanged.** `web/` is outside the fingerprint (E4), but its tests run every PR, and E2's import-not-copy test keeps it honest.

## 14. Delivery

The plan (`docs/PLAN-A8.md`, after approval) breaks these into small PRs.

| Phase | Scope | Proof |
|---|---|---|
| U0 | ADRs 0010 (UI stack and `web/` outside the fingerprint), 0011 (stay in Python), 0012 (replay-only public demo); event models, schema and generated types; `make bench` with today's numbers | Schema contract tests pass; baseline benchmark committed |
| U1 | The §6.3 bundle in one PR, then the re-baseline: flakiness study k=5, `make baseline`, gate k=3 | Benchmark meets §6.3; gate receipt passes; `verify` green |
| U2 | Replay viewer and `build-demo`; front end with steps, answer card, chart and table, error states; Pages deploy if D1 | All 20 replays render; axe clean; demo URL live |
| U3 | Live mode: `canada-web serve`, SSE, hardening, Stop | Backend security tests; `make live-web` answered one real question |
| U4 | Accessibility pass, README section with screenshots or a GIF, the 3-reviewer adversarial review (security, honesty, code), release v1.1.0 | Review findings fixed and logged in `docs/reviews/`; tag pushed |

**Ownership (A7) still applies:** Claude builds; George gets a vault lesson per new concept (Server-Sent Events, CSP and Trusted Types, generated types, localhost hardening, accessibility testing) and check-yourself questions at the tag.

## 15. Risks

| Risk | Mitigation |
|---|---|
| The U1 re-baseline hits the subscription's usage limit | Runs resume with the same command (they already do); budget it as one sitting |
| U1 changes move the dev pass rate | The gate decides; P1–P8 don't touch prompts or tool descriptions, so a move would be noise or a real bug, and the receipt shows which |
| The UI shows something the gate never verified | E2 (import, don't copy), E3 (answer only from `AskResult`), contract tests over all replays |
| Injected text in tool results reaches the page | Plain text only; Trusted Types; a Playwright test with a crafted payload |
| A replay is mistaken for a live run | Banner, footer provenance, and `billed: "none"` on every replay |
| Two languages to maintain | TypeScript only in `web/frontend`; generated types; one event contract; the agent and every rule stay Python |
| Someone runs live mode for others | README warning quoting the terms; the server refuses non-local binding |
| The chart library constrains CSP or accessibility | D4; the data table is the accessible source of truth, and the chart is the extra |

## 16. Decisions for George

Each has a default, which applies if he approves A8 without changing it.

| # | Question | Default | Why |
|---|---|---|---|
| D1 | Host the public replay demo? | **Yes, on GitHub Pages** | Free and static, with no model calls. A recruiter can see the agent work without installing anything |
| D2 | Single page now, or build the eval explorer too? | **Single page now;** the explorer later | The explorer is a lot of new surface. React and the event contract keep it cheap to add later |
| D3 | A Rust learning experiment (a PyO3 snapshot parser, benchmarked against Python)? | **No** (optional, outside the agent if yes) | It's a learning goal, not an optimisation; it would save ~50 ms once per table |
| D4 | Chart library | **Recharts** (SVG, React-native) | SVG is easier to test and inspect than canvas; the data table carries accessibility either way |
| D5 | Release name | **v1.1.0**, with SPEC §5's "v1.1" list renamed "later" | A8 is a backwards-compatible feature release |

## 17. How A8 resolves the investigation and its review

| Point | Investigation said | Review said | A8 follows |
|---|---|---|---|
| Latency | Model ~95%, our Python 3–6% | Right in direction. The sample is Haiku-only on recorded data; live Sonnet is 26.7 s; the per-call saving is 0.6 s, not 1.7 s | The review: §6.1 shows both samples and the live trace; P3 adds timing for real measurement; §6.4 uses 0.6–1.0 s |
| Rewrite | No; the link regex is unportable | No; the regex *is* portable, but it would be two copies of a security rule | The review's reasoning (§6.2) |
| UI front end | Plain JS, no build, ~400 lines | Wins only under one weighting; ~700–1,200 lines realistic; no types or accessibility criteria | The review: React + TypeScript (§8) |
| UI backend | FastAPI SSE, one event schema, localhost hardening | Solid | Both (§8–§10) |
| Static demo | A heavily weighted requirement | A preference, and the hosted demo wasn't decided | D1 makes it George's call |
| Missed option | – | Build the replay viewer first; TUI and Python dashboards not considered | Replay first (U2 before U3). A TUI is rejected because the demo needs a browser; Python dashboards fail the static-demo and CSP needs |
| Un-gated UI | `web/` outside the fingerprint | A UI bug could contradict the gate | E2, E3 and the contract tests (§13) |
| Cancel | Raise from the capture list | Works, but is hacky and fires only on the next event | P5: an explicit `should_stop` hook in `src/` |
| Pre-starting `claude -p` | Best architecture fit, untested | Unproven; changes the canary and stdin handling | Deferred to a measured follow-up (§6.3) |
