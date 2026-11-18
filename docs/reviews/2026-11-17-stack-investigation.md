> Evidence for amendment A8 (`docs/amendments/A8-web-ui-and-performance.md`). Written 2026-11-17 by a Claude Opus 5.5 orchestrator with three parallel sub-investigators. All measurements were offline: no model, Voyage or live StatCan calls. The scripts and raw outputs it cites (`measure/`, `lang/`, `ui/`, `xcheck/`) were kept in a temporary job folder and are not committed; the key numbers are restated in A8 §6. Challenged by `2026-11-17-stack-review.md`, which supersedes it where they disagree.

# Canada Data Agent: latency, language and UI investigation

Date: 2026-11-17.
- **Repo:** `~/projects/ai-eval-lab` at `d7cc29e` (v1.0.0). `git status --short` was clean before and after.
- **Machine:** Apple M5, macOS 26.2, Python 3.13 venv, Node v25.2.1, Claude Code 2.1.323.

**Evidence labels.**
- **M** = MEASURED: the command and the number are given.
- **V** = VERIFIED: the source URL was fetched on 2026-11-17.
- **J** = JUDGEMENT: my reasoning, not tested.

**Who did what.** Three sub-investigators worked in parallel: measurement, language and ecosystem, and UI. Their scripts and raw outputs are in `measure/`, `lang/` and `ui/raw/`. I re-ran the key measurements and re-checked the key external facts; those outputs are in `xcheck/`.

## A. Latency budget for one question

**How it was measured.**
- Model-side numbers come from 761 recorded Haiku dev runs in `evals/runs` (gate and flakiness-study runs). Each holds `wall_s` and Claude's own `duration_ms` and `num_turns`.
- Events have no per-event timestamps, because `transcripts.slim()` drops them (`transcripts.py:47-59`).
- Our-side numbers were measured locally on the snapshot backend:
  - `VOYAGE_API_KEY=` and `DATA_BACKEND=snapshot` were set; I confirmed environment variables take precedence over `.env`.
  - Database sessions were read-only.

**Typical question:** Haiku, dev split, 6 turns, 4 tool calls, ~1.3k output tokens, run from the CLI.

| # | Component | Median | p95 | How measured | Kind |
|---|---|---|---|---|---|
| 0 | Wall time around `claude -p` | 9.80 s | 15.6 s | M: `xcheck/runs_stats.py`, `measure/01_runs_analysis.py`, n=761 | – |
| 0a | Claude's own `duration_ms` | 9.37 s | 15.0 s | M | waiting on model |
| 0b | Wall minus duration (Claude Code init, tool-server connect, teardown) | 0.50 s | 0.62 s | M: wall ≥ duration in 761/761 runs; flat against turns (R² 0.000) | process start |
| 0c | Cost of each extra tool call or turn | ~1.7 s | – | M: regression. Haiku: wall ≈ 0.76 + 0.70×turns + 3.9 s per 1k output tokens (R² 0.76). Sonnet: 1.0 + 7.9 s per 1k (R² 0.91) | waiting on model |
| 1 | CLI: Python start plus `import canada_agent.ask` (paid before `claude` starts, so not in `wall_s`) | 0.28 s | 0.30 s | M: `measure/02_time_cmd.py`; xcheck agrees (0.28 s) | ours, CPU (imports) |
| 1a | …of which the avoidable `mcp_server` import (needed only for `SERVER_NAME`) | ~0.20 s | – | M: the other imports alone take 71 ms (`measure/08_import_counterfactuals.txt`) | ours, CPU |
| 1b | `uv run` overhead | 5–7 ms | – | M | – |
| 2 | `claude --version` / `--help` (a rough proxy for binary start only) | 9.5 / 48 ms | – | M | – |
| 3 | Tool server: process start to `initialize` reply (inside 0b) | 247 ms | 275 ms | M: `measure/04_mcp_startup.txt` (n=15) = 247; `lang/handshake.txt` = 243; xcheck = 246 (n=10) | ours, CPU (imports) |
| 3a | …of which `import mcp` / `psycopg` | 163 / 42 ms | – | M: `-X importtime`; `mcp` builds 556 pydantic models | ours, CPU |
| 3b | Tool-server start with an empty bytecode cache (fresh clone or CI) | 0.89–1.06 s | – | M | ours, CPU |
| 3c | Is tool-server start on the critical path? | yes | – | V: code.claude.com/docs/en/headless says that with `--mcp-config` and `-p`, "Claude Code waits for still-pending servers before running the first turn" | – |
| 4 | All tool calls in one question (snapshot data, fresh server) | 33 ms | 82 ms | M: `measure/04_mcp_calls.txt`, 54 recorded calls × 5 | ours |
| 4a | `search_tables`, run in-process | 7.7 ms (xcheck 8.6) | 12.7 ms | M: `measure/05_inprocess.txt`, `xcheck/inprocess_rerun_full.txt`. Breakdown: 2 database connects 5.5–6.6 ms; full-text 0.55–0.66 ms; exact vector scan of 584×1024 0.9–1.0 ms (EXPLAIN: sequential scan); RRF 0.01 ms; result cap 0.03 ms | ours |
| 4b | `get_table_dimensions` | 0.08 ms | 0.33 ms | M: it re-parses `metadata.json` on every call | CPU |
| 4c | `get_series`, first use of a table (gunzip and parse the whole table) | 10–14 ms (CPI) / 59–64 ms (LFS) | – | M | ours, CPU |
| 4d | `get_series`, warm | 0.03–0.3 ms | – | M | CPU |
| 5 | Our checks: `run_events`, canary, `foreign_links`, `check_answer`, `check_grounded` | 0.22 ms | 0.34 ms | M: `measure/06_checks.txt` | CPU |
| 5a | Parsing the JSON event stream | 0.03 ms | – | M | CPU |
| 6 | Live only: a search with Voyage embedding and rerank | ~0.48 s per search | – | Committed live trace `docs/demo/ask-trace.txt` lines 4 and 6 (0.475 s, 0.479 s); ADR 0003 (~100 ms embed); ADR 0004 (200–400 ms rerank). Not re-run: no paid calls | waiting on network |
| 6a | Live only: `get_series` with an empty StatCan cache | ~1.0 s | – | `docs/demo/ask-trace.txt` line 10 | waiting on network |
| 7 | Full offline replay (`canada-ask --offline`) | 0.61–0.74 s | 0.79 s | M: `measure/07_replay_timing.txt`, 7 runs × 6 questions. Imports ~0.24 s; server start + calls + close 0.31–0.45 s; `run_events` 0.3 ms | ours |
| 8 | Tool-server memory: idle / after an LFS question / long-lived | 81 / 171 / 153–189 MiB | – | M: `ps` | – |
| 9 | Offline test suite | 418 passed in 9.2 s | – | M: `uv run --frozen pytest -p no:cacheprovider -q` | – |

**Where the time goes.**
- **The model:** ~9.3 s, about 92–95% of the question.
- **Process start and teardown:** 0.5 s, plus 0.28 s when run from the CLI.
- **Our CPU:** ~0.25 s of tool-server imports, plus ~0.28 s of CLI imports on the CLI path, plus ~0.03 s of tool calls, plus under 1 ms of checks. Over 90% of our CPU per question is module import.
  - In the profile of a replay (`measure/07_replay_cprofile.txt`), none of our own functions are in the top 45 by cumulative time.
- **Live mode adds** 0.5–2 s of network waiting inside our tools (Voyage and StatCan).
- **Our share overall:** ~3% of an eval run and ~5.6% of a CLI question.
- **The 95 s first cold run** can't be broken down from the committed evidence. A plausible cause (J): before it was fixed, a Voyage rate-limit error (429) stalled one search for 60.8 s (`docs/FINDINGS-LOG.md` line 80).

## B. Language and architecture

### Ecosystem facts (V)

**MCP SDK tiers** (modelcontextprotocol.io/docs/sdk and /community/sdk-tiers):
- Tier 1: TypeScript, Python, C#, Go, Rust, Ruby.
- Tier 2: Java.
- Tier 3: Swift, PHP, Kotlin.

| | Python | TypeScript/Node | Go | Rust |
|---|---|---|---|---|
| MCP SDK | `mcp` 2.3.0 (locked) | `@modelcontextprotocol/server` 2.4.0 | go-sdk v1.8.0 | `rmcp` 3.10.0 |
| Postgres driver | psycopg 3.3.6 (locked) | `pg` 8.23.1 | pgx v5.13.0 | sqlx 0.9.0 |
| pgvector client | not used; the code casts `%s::vector` | npm `pgvector` 0.3.1 | pgvector-go v0.4.1 | `pgvector` 0.4.2 |
| Voyage SDK | official, but the code uses plain httpx | npm `voyageai` 0.6.0, not listed in Voyage's install docs | none (plain HTTP) | none (plain HTTP) |
| Claude Agent SDK | `claude-agent-sdk` 0.2.183 | `@anthropic-ai/claude-agent-sdk` 0.3.326 | none | none |

Registry outputs are in `lang/registry.txt`.

**Terms and docs:**
- **Subscription use** (code.claude.com/docs/en/legal-and-compliance, which I re-fetched):
  - "Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, Max, or Ultra plan credentials on behalf of their users."
  - "Advertised usage limits for Pro, Max, and Ultra plans assume ordinary, individual usage of Claude Code and the Agent SDK."
- **Agent SDK overview:** "Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK".
- **`--bare` mode** (code.claude.com/docs/en/headless, re-checked by me): "bare mode doesn't use your subscription login … Claude Code never reads OAuth credentials or the system keychain". It is faster, but it would mean API billing, so it is ruled out.

### What any agent change costs (V: `gate.py` lines 49-68, read by me)

**What the gate fingerprints.**
- `INPUTS` = `src/canada_agent`, `evals/golden`, `evals/baseline.json`, `snapshots`, `data/index.sql.zst`, `pyproject.toml`, `uv.lock`. Only files tracked by git count.
- `agent_hash` is the same set minus the grading files.

**What a change triggers.**
- Changing agent code, `pyproject.toml` or `uv.lock` requires a new 5-repeat flakiness study (120 runs), a new baseline, and a 3-repeat gate (72 runs).
- That is 192 `claude -p` runs: about $0.50 API-equivalent and ~30 minutes.

**Loophole.**
- Agent code placed in a new directory outside `src/canada_agent` changes the fingerprint once, when `ask.mcp_config()` is pointed at it.
- After that, edits to that directory never change it again.
- These are already outside the fingerprint today: `config/`, `migrations/`, the `Makefile`, and the `claude` CLI version.
- ADR 0009 says "evals/" is fingerprinted, but only `evals/golden` and `evals/baseline.json` are.

### Verdict per component

| Component | Lines (M) | Tests touching it (M) | Correctness risk of a rewrite | Plausible gain for the user | Verdict |
|---|---|---|---|---|---|
| Orchestration and stream parsing (`ask.py`, plus 247 lines in `links`/`logs`/`untrusted`/`config`/`errors`/`costs`) | 575 + 247 | 50 in `test_ask`, plus link tests in graders, gate and poison | High: `links.py`'s Unicode `\w`, lookarounds and NFKC. In JavaScript, `/^\w$/u.test('é')` is false (M); Go's RE2 and Rust's regex have no lookarounds. The module is shared with the grader | ~0 (the 0.20 s import fix is a Python fix) | **Stay in Python** |
| Tool server (`mcp_server.py`; ~2,100 lines with what it pulls in) | 208 | 23 + 34 poison + 14 offline + 22 pipeline, plus re-pinning `mcp_tools.json` | Medium-high: the strict-arguments fix (J: zod and serde drop unknown keys); spacing in `json.dumps` decides where the 16,000-character cap trims and so the text the model sees; pydantic `Field` constraints | ≤0.23 s of ~9.8 s (Go/Rust start ~5–20 ms, J; Node ~80–150 ms, J; `node -e 0` is 34 ms, M) | **Stay in Python**; keep it warm instead |
| Search (`search/`, `index/`, `embed/`, `db/`) | 977 | 55 | Low-medium | 0: ~8 ms offline, network-bound live | **Stay in Python** |
| StatCan client and series (`wds/`, `series/`) | 791 | 70 | Medium: errors inside HTTP 200 bodies, Retry-After, the exact cache key | 0: network-bound, 10 requests/s limit | **Stay in Python** |
| Eval tooling (`evals/`) | 1,805 | 177 | High: `verify` re-grades every committed run, so any drift fails CI | 0: offline only | **Stay in Python** |
| Offline replay (`offline.py`) | 236 | 14 | Low | 0 | **Stay in Python** |

A rewrite would matter only if one of these held (J): the median question dropped to ~1–2 s (impossible with ~5–6 model turns); our CPU showed up in a profile; or the server had to serve many clients at once. None does.

### Is starting fresh processes per question the bottleneck?

Only partly. Starting processes costs ~0.5 s plus 0.28 s of CLI start; the model costs ~9.3 s.

| Alternative | What it would save | Verdict |
|---|---|---|
| One long-lived `claude` session answering many questions | – | **Reject.** It breaks per-question isolation: context carries over, the system prompt and its canary can't rotate, and cost totals accumulate |
| `--resume` or Agent SDK sessions | nothing | Each is still a new process, and they carry context between questions |
| A long-lived tool server over HTTP | ~0.25 s | **Reject.** It reverses ADR 0005: a port, authentication, and Origin checks the spec makes mandatory ("Servers MUST validate the Origin header…", V: modelcontextprotocol.io/specification/2025-11-25/basic/transports). It also breaks the per-run `POISON` and `DATA_BACKEND` settings the injection evals rely on |
| **Pre-started single-use `claude -p --input-format stream-json`** | up to ~0.5 s | **Best fit (J, untested).** Start the next process, with a fresh canary, while the user types; write the question to stdin and close it. Today `_stream` passes `stdin=DEVNULL` precisely to avoid that wait |

### In-Python optimisations, ranked

| # | Change | Gain per question | Evidence | Gate impact |
|---|---|---|---|---|
| 1 | **Tool design that saves a model round trip** (e.g. `search_tables` returns matching member ids, or `get_series` accepts member names). Haiku makes 1.13 search, 1.23 dimension and 1.33 series calls per question (M). Fewer output tokens also help: 3.9 s per 1k for Haiku, 7.9 s for Sonnet | ~1–1.7 s | M on the cost per call; J on whether the model skips the call | Pinned tool descriptions change, so the full gate runs. **May lower accuracy**; the gate decides |
| 2 | Pre-start the next `claude -p` in the UI's live mode | up to ~0.5 s as perceived | J | Change to `ask.py`, so a re-baseline |
| 3 | Move `SERVER_NAME` so `ask.py` no longer imports `mcp_server` | 0.20 s per CLI question | M: 273 → 71 ms | Bundle into one pull request |
| 4 | Lazy-load `psycopg`, `yaml`, `zipfile` and `csv` in the tool server | 50–70 ms per server start | M / J | Bundle |
| 5 | Preload the snapshot gzip in a background thread | 10–65 ms on the first `get_series` per table | M | Bundle |
| 6 | One database connection per search (today `search()` and `cards()` each connect) | 3–5 ms offline, ≤20 ms live | M / J | Bundle |
| 7 | Memoize `metadata` | <0.3 ms offline; one StatCan round trip live | M / J | Bundle |
| 8 | Live only: cache coordinate → vector_id; try `rerank-2.5-lite` | 0.2–0.5 s live | J | The rerank change needs the retrieval eval and the gate |
| – | Faster checks or parsing | <0.5 ms | M | Not worth doing |

## C. UI

### Requirements derived from the code (V unless marked)
1. **Stream each tool step live, with its latency.** The hook already exists: `on_event` (`ask.py:342, 358`); see `docs/demo/ask-trace.txt`.
2. **Show the answer only after the checks pass.**
   - The checks run on the `result` event (`ask.py:359-370`). So the UI must not stream answer tokens (J), even though `--include-partial-messages` exists (V).
   - A rejected answer shows only its error code. Example: `evals/runs/gate-…97b6fa09ac9f/r3/inject-03.json` is coded ANSWER_REJECTED, yet its `structured_output` still contains the attacker's answer (M, xcheck). Build the demo only from `offline.recordings()`.
3. **Answer card.**
   - Fields: `answer`, `answer_values`, `source_urls`, `refused` (`ask.py:48-73`).
   - Recompute the arithmetic in the UI, as `graders._recompute` does.
   - Only links that match `CITABLE_URL` and that a tool actually returned may be clickable.
4. **Chart** the `get_series` points. A `null` value means suppressed, never zero; at most 120 points.
5. **Label replays** "Not a model run" (`ask.py:571`). Recorded runs have no per-step timings (M: a replay shows 0.0 s), so show "timing not recorded".
6. **Show every `ErrorCode`**, plus `UsageLimitError`.
7. **Live mode is local and single-user; the public demo is replay-only**, per the terms above.
8. **Treat table cards, member names and error bodies as text, never HTML.** These are the injection routes the README documents.
9. **Protect the localhost endpoint**, because each question spends the owner's subscription:
   - bind 127.0.0.1;
   - check the Host header (against DNS rebinding);
   - check Origin and require a JSON content type;
   - no CORS;
   - one run at a time;
   - a strict Content Security Policy (CSP).
10. **Closing the tab must kill the processes.** `_stream`'s `killpg` in its `finally` block already does this.
11. **Tests in pytest**, with Playwright for Python, plus a pinned event-schema snapshot.
12. **Don't change the gate fingerprint.**
    - Keep UI code out of `src/canada_agent` and out of the root `pyproject.toml`/`uv.lock`.
    - Use a separate `web/` uv project with its own lock and `[tool.uv.sources] canada-data-agent = {path="..", editable=true}`. Don't make it a uv workspace member, because a workspace shares the root lock (J).
    - Starlette 1.10.0, sse-starlette 3.6.0 and uvicorn 0.54.0 are already locked through `mcp` (M).

### Backend and API shape

**FastAPI's built-in streaming is real** (V: fastapi.tiangolo.com/tutorial/server-sent-events/ says "Added in FastAPI 0.135.0"; PyPI dates 0.135.0 to 2026-03-01; the current version is 0.163.1).
- Import: `from fastapi.sse import EventSourceResponse, ServerSentEvent`.
- It sends a keep-alive ping every 15 s and sets `Cache-Control: no-cache` and `X-Accel-Buffering: no`.
- Plain (non-async) generators run in a thread pool.
- WebSockets are rejected: nothing needs two-way traffic, and they invite cross-site hijacking (J).

**Endpoints (J):**
- `POST /api/ask` returns a `run_id`. Host, Origin and content type are checked.
- `GET /api/runs/{id}/events` streams the events. It is an async generator reading a queue, with a per-run buffer so a dropped connection can resume via `Last-Event-ID`.
- `POST /api/runs/{id}/cancel` stops a run.
- `GET /api/replays` and `/api/replays/{case}` serve recorded runs.

**Event schema** (pydantic models with a pinned JSON Schema, J):
```
run_started   {mode: live|replay, provenance{source, model, prompt_version, git_sha, recorded_wall_s}, budget}
step_started  {step_id, tool, arguments, t_ms|null}
step_finished {step_id, ok, latency_ms|null, error_code?, result}
answer        {answer, answer_values, source_urls, refused, arithmetic[recomputed], checks:"passed"}  # only after run_events returns
run_failed    {code, safe_message}   # never the rejected answer
run_finished  {num_turns, duration_ms, api_equivalent_usd, billed}
```

**How live and replay share one page.**
- **Live:** a worker thread runs `ask(..., capture=Tap(queue))`, and an adapter normalises the events. Applying `transcripts.slim()` to live events gives the recorded shape.
- **Replay:** the same normaliser.
- **Demo builder:** it runs each replayable dev recording through the production `run_events` (M: this needs no database, model or network) and writes `replays/<case>.json`.
- **One renderer:** `apply(event)` consumes either the live stream or a fetched JSON array. `mode` and `provenance` drive the replay banner.

**Cancel without touching `src/` (J).**
- `Tap.append` raises once the run is cancelled. The exception travels through `_tee`, `run_events` and `closing()` into `killpg`.
- It takes effect at the next event; the 120 s timer is the backstop.

**Localhost hardening (J).**
- Run uvicorn on 127.0.0.1, with `TrustedHostMiddleware(["127.0.0.1","localhost"])`.
- Require an exact Origin match plus a JSON content type.
- No `CORSMiddleware`. An optional per-launch token in a `SameSite=Strict` cookie.
- CSP: `default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; require-trusted-types-for 'script'; trusted-types 'none'`.
- uPlot 1.6.32 never uses `innerHTML` or `eval`, so it works under that CSP. htmx 2.0.11 has 11 `innerHTML`, one `eval(` and one `new Function` (M: `ui/raw/csp-grep.txt`).

### Options

**Versions** (M on 2026-11-17; * = I re-queried it myself):
- **Python UI frameworks:** streamlit 1.67.0*, gradio 6.32.0*, nicegui 4.0.0*, reflex 0.11.0, python-fasthtml 0.14.24, datastar-py 1.0.3.
- **Chainlit 2.12.0\*:** its GitHub repo is archived (`archived:true`*).
- **Web stack:** fastapi 0.163.1*, sse-starlette 3.7.0.
- **JS frameworks:** react 19.3.1, vite 8.3.8, svelte 5.57.3, @sveltejs/kit 3.2.0, vue 3.5.45, next 16.4.6, astro 7.4.12, solid-js 2.0.0 (released today).
- **htmx:** htmx.org 2.0.11 (version 4.0.1 is tagged `next`).
- **Others:** @gradio/lite 5.45.0*, last modified 2025-09-10; uplot 1.6.32* (2025-03-14, one maintainer).

**Facts that decide the scores (M from the package source unless marked):**
- **Streamlit:**
  - listens on every network interface by default: `DEFAULT_SERVER_ADDRESS: Final = "0.0.0.0"` (`starlette_server_config.py:60`, re-checked by me);
  - re-runs the whole script on each interaction (V), and `st.markdown` renders links;
  - a static demo needs stlite: 112 MB unpacked plus 8.6 MB of Pyodide WebAssembly.
- **NiceGUI** also defaults to `0.0.0.0` (`llms.md:906`), as does **FastHTML** (`serve(host='0.0.0.0')`, `core.py:913`).
- **Gradio** binds 127.0.0.1, but its in-browser version, gradio-lite, is frozen (M) and called "mostly dead" (V: HF forum).
- **Chainlit's** `@cl.step` maps naturally onto tool calls, but the repo is archived and the original team stepped back on 2025-05-01 (V). It pulls in 125 dependencies.
- **Datastar** needs CSP `unsafe-eval` (V: data-star.dev/reference/security).
- **Python dependency counts** (M):

  | Stack | Packages |
  |---|---|
  | fastapi + uvicorn + jinja2 | 16 |
  | streamlit | 33 |
  | gradio | 53 |
  | nicegui | 50 |
  | reflex | 41 |
  | fasthtml | 25 |
  | chainlit | 125 |
- **Chart sizes, gzipped** (M): uPlot 22 KB, Chart.js 71 KB, Observable Plot 69 KB.

**Scores (J).** Weights:

| Criterion | Weight |
|---|---|
| Safety | 20 |
| One event format for live and replay | 20 |
| Static demo with no server | 15 |
| Maintenance | 15 |
| Testability | 10 |
| Charts and layout | 10 |
| Project health | 10 |

Each option is rated 1–5 per criterion; score = Σ(weight × rating)/5. I checked the arithmetic.

| Option | Safety | Stream | Static | Maint | Tests | Charts | Health | Score |
|---|---|---|---|---|---|---|---|---|
| **FastAPI SSE + JSON events + plain JS, no build + uPlot** | 5 | 5 | 5 | 4 | 4 | 5 | 4 | **93** |
| FastAPI SSE + Vite + TypeScript + React/Preact | 4 | 5 | 5 | 2 | 3 | 5 | 5 | 83 |
| FastAPI SSE + Vite + Vue 3 | 4 | 5 | 5 | 2 | 3 | 5 | 5 | 83 |
| FastAPI SSE + SvelteKit (static) | 4 | 5 | 5 | 2 | 3 | 5 | 5 | 83 |
| FastAPI SSE + Jinja2 + htmx 2 + uPlot | 5 | 4 | 3 | 4 | 5 | 4 | 4 | 83 |
| SolidJS 2 | 4 | 5 | 5 | 2 | 3 | 5 | 3 | 79 |
| Astro + islands | 4 | 4 | 5 | 2 | 3 | 5 | 5 | 79 |
| Next.js | 4 | 4 | 4 | 1 | 3 | 5 | 5 | 73 |
| FastHTML | 3 | 4 | 2 | 4 | 4 | 3 | 3 | 66 |
| Datastar | 2 | 5 | 2 | 4 | 4 | 3 | 3 | 66 |
| Observable Framework (demo only) | 4 | 2 | 5 | 2 | 2 | 5 | 2 | 63 |
| Streamlit (+ stlite) | 2 | 3 | 2 | 4 | 3 | 3 | 5 | 60 |
| NiceGUI | 2 | 4 | 1 | 3 | 4 | 4 | 4 | 60 |
| Gradio | 3 | 4 | 1 | 3 | 3 | 3 | 4 | 60 |
| Reflex | 3 | 3 | 2 | 1 | 2 | 4 | 3 | 51 |
| Chainlit | 3 | 5 | 1 | 2 | 2 | 2 | 1 | 51 |

**Sensitivity:** without the static-demo criterion, htmx + Jinja ties the winner. The Python-native frameworks lose mainly on the static demo and on their default settings.

### Recommendation
**FastAPI with built-in streaming, one event format, and a static page with no build step** (one JavaScript module that writes only plain text, plus a vendored uPlot), in its own `web/` uv project.

**Why:**
1. **One renderer serves live and replay.** The public demo is static files with zero model calls, which keeps it within the terms, and every replay is re-checked by the production checks when the demo is built.
2. **It is the safest option against injected text:** browser-enforced Trusted Types, no `innerHTML`, and clickable links only for `CITABLE_URL` matches.
3. **It adds the least to maintain:**
   - Python: only fastapi is new.
   - JavaScript: one vendored file plus ~400 lines; no Node, no node_modules.
   - Tests stay in pytest + Playwright (playwright 1.65.2, pytest-playwright 0.10.0).
4. **The gate fingerprint doesn't change.**

**Trade-offs accepted:**
- A second language with no type checker (mitigated by the schema contract test; JSDoc + `tsc --checkJs` can come later).
- No component framework.
- CI must download a Playwright browser.
- Replays say "timing not recorded" until recordings carry timestamps.
- Cancel takes effect at the next event until the `src/` hook lands.
- uPlot has a single maintainer (it's vendored; Observable Plot can replace it).

### Runner-up
**The same backend and event format, with Vite + TypeScript + Preact/React.**
- **Pros:** types generated from the schema; components scale if the UI becomes an eval explorer (runs, gate receipts, flakiness, retrieval ablation); switching later is cheap.
- **Cost:** Node, node_modules, a second lockfile, Vitest and a build step in CI, more urgent dependency updates, and a harder Trusted Types setup.

**When to pick htmx + Jinja instead:** only if "no hand-written JavaScript" becomes a hard rule. That costs a separate pre-rendered demo and a looser CSP.

## D. Combined recommendation

**The UI choice doesn't change part B.**
- The browser only talks to the Python backend. The backend calls `ask()`, which starts `claude -p`, which starts the tool server over stdin/stdout (`ask.py:111-119`).
- Everything the project's credibility rests on is Python and covered by the gate fingerprint: the checks, `links.py`, the graders, the snapshot and the gate. A TypeScript tool server would duplicate rules that must never diverge, and would invalidate the v1.0 results.
- Only the event types cross into the browser's language, generated one way from Python.
- **Avoid a UI that drives the TypeScript Agent SDK directly:** it would bypass `check_answer` and the grounding checks.

**Plan:**
1. **Build `web/`** as a new uv project outside the fingerprint: the FastAPI app, the event adapter, the replay builder, the static page, Playwright tests and the localhost hardening.
2. **Make one bundled change to `src/`, paying for one re-baseline** (192 runs, ~$0.50, ~30 minutes):
   - move `SERVER_NAME` out of `mcp_server`;
   - add an event/cancel hook to `ask()`;
   - keep per-event timestamps in `slim()` (`transcripts.py` is not a grading file, so it changes `agent_hash`);
   - open one database connection per search;
   - lazy-load the tool server's imports;
   - optionally, let `_stream` support pre-starting.
3. **Later, and only if the gate confirms accuracy:** tool-design changes that save a model round trip. That is the only change worth more than a second.
4. **Close the fingerprint gaps** when `gate.py` is next touched: add `config/` and any agent code outside `src/`, and consider recording the `claude` CLI version.
5. **Write an ADR and amend SPEC §3:** live mode is local only; the demo is static replays; it never calls the model (quote the terms); `web/` sits outside the fingerprint on purpose.

## Open questions and risks
1. **Pre-starting `claude -p` is untested.** Does init, including the tool-server connection, finish before the first stdin message? Does an idle process use any quota? Testing needs one live run by the owner, which was out of scope.
2. **Inference and Claude Code's tool round trips can't be separated** inside `duration_ms`, because recordings have no timestamps. Step 2 of the plan fixes this for future runs.
3. **The 95 s cold run is unexplained.** A Voyage 429 stall is plausible (J).
4. **The live search latency (~0.48 s) rests on a single committed trace** of two searches.
5. **Tool-design changes may cost accuracy.** Only the gate can tell.
6. **The legal reading is judgement, not advice.** Even letting a friend use the local live mode would route their requests through the owner's credentials.
7. **Two dependencies carry risk:** uPlot has a single maintainer (last release 2025-03), and htmx is mid-migration from 2 to 4.
8. **Measurement hygiene.**
   - Some early timings may have been slowed by a concurrent `pytest --collect-only` from the language investigator; repeats agreed within ±5%.
   - Ignored bytecode files under `src/**/__pycache__` were updated; no tracked file changed.

## Methods appendix

**Orchestrator (me), outputs in `xcheck/`:**
- **Read:** README, `ask.py`, `offline.py`, ADRs 0005 and 0009, the relevant SPEC lines, `gate.py` lines 40-120 and 236-300, the Makefile.
- **Run statistics:** `python3 xcheck/runs_stats.py ~/projects/ai-eval-lab`. Result: n=761; wall 9.80/15.60 s; duration 9.37 s; overhead 0.50/0.62 s; fit wall = 2.08 + 0.61×tool calls + 4.35×thousands of output tokens.
- **Tool-server handshake:** `env -u VOYAGE_API_KEY DATA_BACKEND=snapshot DATABASE_URL=<unreachable> .venv/bin/python lang/mcp_handshake.py 10 -- .venv/bin/python -m canada_agent.mcp_server` gave a 246 ms median.
- **Import timings:** `/usr/bin/time -p` on each import, median of 5. `mcp_server` 0.27 s, `ask` 0.28 s, `links` 0.01 s.
- **Search benchmark:** `PYTHONDONTWRITEBYTECODE=1 VOYAGE_API_KEY= DATA_BACKEND=snapshot python measure/05_inprocess_bench.py`. `search_tables` 8.6 ms, a connect 3.3 ms.
- **Registry and repo checks:** PyPI JSON (fastapi 0.135.0 = 2026-03-01; streamlit, gradio, chainlit, nicegui); the GitHub API for Chainlit (archived); `npm view` for @gradio/lite and uplot.
- **Source checks:** grepped the downloaded packages for default listen addresses; inspected the rejected inject-03 run.
- **Pages fetched:** legal-and-compliance, headless, FastAPI SSE tutorial.
- **Final repo state:** `git status --short`, clean.

**Measurement investigator (`measure/`)**, all with `PYTHONDONTWRITEBYTECODE=1 VOYAGE_API_KEY= DATA_BACKEND=snapshot`:
1. Checked `.env` key names only, and the settings precedence.
2. `uv sync --frozen --dry-run` and `uv lock --check`.
3. `01_runs_analysis.py`.
4. `02_time_cmd.py`.
5. `-X importtime` (outputs `03_*`).
6. Import counterfactuals (`08_*`).
7. `04_mcp_stdio_bench.py startup 15` and `calls 5`.
8. `05_inprocess_bench.py` and `05b_explain_vector.py` (read-only, EXPLAIN ANALYZE on SELECTs).
9. `06_checks_bench.py`.
10. `canada-ask --offline --trace`, 7 runs × 6 dev questions.
11. cProfile of one replay.
12. `07b_replay_phases.py`.
13. `uv run --frozen pytest -p no:cacheprovider -q --durations=12`.

**Language investigator (`lang/`):**
- **Measurements:** `startup.txt` (python, node, `claude --version`), `importtime_top.txt`, `handshake.txt`, `transcripts_summary.txt` (Sonnet dev transcripts: median wall 7.45 s, duration 6.98 s), `unicode.txt`, `registry.txt`, `pytest --collect-only` (418 of 428), `wc -l`.
- **Sources:**
  - modelcontextprotocol.io: /docs/sdk, /community/sdk-tiers, /specification/2025-11-25/basic/transports
  - github.com/modelcontextprotocol/go-sdk/issues/892
  - docs.voyageai.com/docs/api-key-and-installation
  - code.claude.com/docs/en/: legal-and-compliance, agent-sdk/overview, headless, cli-reference, mcp

**UI investigator (`ui/raw/`, `ui/wheels/`, `ui/vendor-check/`):**
- **Raw outputs:**
  - npm: `npm-view.txt`, `npm-release-dates.txt`, `npm-sizes.txt`, `npm-wasm-python.txt`
  - PyPI: `pypi-*.json`, `pypi-summary.txt`
  - GitHub: `gh-fastapi-0.135.0.json`, `gh-misc.txt`
  - Analysis: `deps-transitive-counts.txt`, `csp-grep.txt`, `scores.txt`, `run_events-on-recorded-transcript.txt`
- **Packages:** downloaded and grepped, never installed.
- **Sources:**
  - code.claude.com/docs/en/legal-and-compliance
  - github.com/fastapi/fastapi/releases/tag/0.135.0
  - fastapi.tiangolo.com/tutorial/server-sent-events/
  - Streamlit docs: config.toml reference and fragments
  - github.com/Chainlit/chainlit
  - discuss.huggingface.co/t/gradio-lite-mostly-dead-on-all-spaces/169640
  - gradio.app/guides/gradio-6-migration-guide
  - data-star.dev/reference/security

**Constraints honoured:**
- No model, `claude -p`, Voyage or StatCan calls.
- No gate, live or record targets.
- Held-out test split untouched: only dev runs and dev transcripts were used.
- No tracked repo file changed.
- No personal information in web searches.