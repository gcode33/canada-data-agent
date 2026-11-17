> Adversarial review of `2026-11-17-stack-investigation.md`, written 2026-11-17 by a Claude Sonnet 5.5 reviewer that had to try to break each conclusion. Its scratch scripts (`review/`) are not committed. Process note from the reviewer: a glob error in its own script read the committed held-out test transcripts and printed 6 case ids and wall times; nothing was graded, re-run or used. How A8 resolves each point is in A8 §17.

## Adversarial review of the stack investigation

I tried to break all four conclusions. The latency, no-rewrite and TS-tool-server conclusions mostly survive, with caveats. The UI winner does not survive reweighting.

Process note: a mistaken glob in my own script (`review/s.py`) read the already-committed `evals/transcripts/test/*.json`. It printed only case ids and wall times for 6 rows. I used nothing else from it, and everything below uses dev data. No model, paid API, repo edit or git state change.

### 1. Verdicts

**(a) Model is ~95% of latency, Python 3–6%: UPHELD in direction, WEAKENED in magnitude and representativeness.**
- I recomputed from scratch with `review/r.py`. 768 files, 761 with `duration_ms`. Median wall 9.9 s (report 9.80), p95 15.8 s (15.6), wall minus duration median 0.495 s. This matches.
- The sample is 8 directories (4 gate, 4 study), all `claude-haiku-5-5`, over only 24 distinct dev questions. The 761 runs are repeats, not independent samples.
- Sonnet is the README headline model, but the report has only 24 single dev transcripts. I reproduced them (median 7.45 s wall, 6.98 s duration, 5 turns). That sample is too small, and its case mix differs from the Haiku one. Recomputed for Sonnet, our share is about 3.8% on the eval path and about 7.2% on the CLI path. That is the same order of magnitude, but outside the stated "3–6%".
- The report never reconciled the committed live Sonnet trace (`docs/demo/ask-trace.txt`): 26.7 s total, 6 turns, 4 tool calls. That is 3.6x the Sonnet snapshot median and 2.7x the Haiku median.
  - Tool time in that trace was 0.475 + 0.479 + 0.012 + 1.001 = 1.97 s, about 7% of the run.
  - So "typical question ~10 s" does not describe live Sonnet use. Real waits are 20–30 s.
  - That is the strongest argument for the streaming UI, and the report missed it.
- The ~2 s of live network waiting (Voyage, StatCan) is more than 3x all of our Python CPU. It rests on one trace. Under "optimise to the highest level" it deserved more than a bottom row (#8).

**(b) No rewrite, in-Python fixes: UPHELD.**
- Python CPU is about 0.3–0.55 s against a 7–30 s model wait. No language change could produce a user-visible gain.
- The gain from fewer tool calls is overstated. Section A row 0c says ~1.7 s per extra call. The orchestrator's own fit (Methods appendix) is wall = 2.08 + 0.61 × tool calls + 4.35 s per 1k output tokens. That is 0.6 s per call with tokens held fixed. The "~1–1.7 s" in optimisation #1 is therefore the upper end of what the data supports (error 5).
- The "unportable regex" argument is overstated, though the verdict still stands (error 1).

**(c) UI = FastAPI SSE + JSON events + no-build plain JS: WEAKENED, and the ranking flips under alternative weights.**
- See section 4. The 93-point margin comes from the static-demo weight, a "plain JS = 4 on maintenance" rating, and the omission of type safety, explorer scalability and accessibility.
- The ~400-line estimate is unsupported (error 6).
- The backend half (FastAPI SSE, one event schema, localhost hardening, no model calls in the public demo) is solid and framework-independent. The front-end choice is not decided by the evidence.

**(d) A TS front end doesn't justify a TS MCP server: UPHELD.**
- The browser talks to Python. The gate, graders and `links.py` stay Python.
- A rewrite would invalidate the v1.0 results.

### 2. Errors found

1. **Regex "portability problem" overstated (medium).**
   - The report said `links.py` is hard to port because `\w` fails on `é` in JS. That is true for `/\w/u`.
   - But I ported `HOST` to JS by replacing `\w` and `\W` with explicit `\p{L}\p{N}_` classes. `[^\W\d_]` becomes `[\p{L}\p{Nl}\p{No}]`.
   - I fuzzed 30,000 strings built from an adversarial alphabet (é, Cyrillic, `²`, `Ⅷ`, combining marks, `。`, `·`).
   - Result: 0 mismatches against Python (`review/gen.py`, `review/js.mjs`). A first naive port without `\p{Nl}\p{No}` gave 140 mismatches, so the port needs care, but it is tractable.
   - V8 supports lookbehind. Rust `fancy-regex` and Go `regexp2` support lookarounds. The report only said "RE2 and Rust regex have none".
   - Real remaining risks: Unicode table drift (Python 3.13 uses Unicode 15.1, Node uses 17.0), the NFKC and IGNORECASE edge cases, and having two implementations to keep in sync. The conclusion survives on "two implementations of a security rule", not on "unportable".

2. **Datastar `unsafe-eval` claim incomplete (low).**
   - The page `data-star.dev/reference/security` says the default mode needs `unsafe-eval`. It also documents a "CSP Mode": a nonce on `<html data-nonce>` with `script-src 'self' 'nonce-…'`.
   - Datastar was scored Safety 2 partly on this.

3. **Static demo (15 points) treated as a requirement (medium).**
   - The terms make a model-calling public demo problematic. They do not require static files.
   - A replay-only FastAPI/Streamlit/NiceGUI instance on `--replay-only` also calls no model.
   - Static is a hosting-cost preference. Weighting it 15 and scoring Python frameworks 1–2 on it drives half the margin.
   - SPEC line 34 also says "No chat UI or hosted site". The plan amends §3, but the report never discusses whether a hosted demo is wanted at all.

4. **`0.0.0.0` default treated as a safety disqualifier (low-medium).**
   - Streamlit, NiceGUI and FastHTML default to `0.0.0.0` (verified for Streamlit by the report). Each is one setting: `server.address`, `ui.run(host=)`, `serve(host=)`.
   - The real differences are Host/Origin checks and Trusted Types. Those are hardening the plan adds by hand to FastAPI too.
   - Safety 2 for NiceGUI and Streamlit versus 5 for the winner is not evidenced by the default alone.

5. **Per-call saving inconsistent (low-medium).**
   - Row 0c says ~1.7 s per tool call and turn. The orchestrator's own regression gives 0.61 s per tool call.
   - Optimisation #1 uses "~1–1.7 s". Treat 0.6–1.0 s for Haiku as the supported range. Sonnet's cost per call is unmeasured.

6. **"~400 lines, no build" is an unsupported estimate (medium).**
   - The scope is: streaming steps, answer card, chart with null and gap handling, replay banner, 16-plus error codes, cancel, `Last-Event-ID` resume, and Trusted-Types-safe DOM building.
   - I would expect 700–1,200 untyped lines.
   - Requirement 3 says "recompute the arithmetic in the UI", but the event schema has the server send `arithmetic[recomputed]`. The two disagree.
   - Doing it server-side is the right choice; the requirement text should say so.
   - `tsc --checkJs` mitigation reintroduces Node, which contradicts the "no Node" selling point.

7. **Accessibility is absent from the criteria (medium).**
   - uPlot draws on a canvas, so screen readers get nothing. A data-table fallback is needed.
   - Trusted Types plus `style-src 'self'` also constrain any component library.

8. **Quote check: "Python is the bottleneck" scope (low).**
   - The report labels its share "of an eval run / CLI question". It does not label it as snapshot-only.
   - The 0.5 s wall-minus-duration is not wholly ours. About 0.25 s is the tool server and the rest is Claude Code's own startup.
   - The report says up to 0.25 s of that could be saved. That is an upper bound: if Claude Code starts the tool server in parallel with its own init, the saving could be near zero.

### 3. Missed options and risks

- **Replay-viewer-first (biggest miss).**
  - The report's own requirement 7 says live mode is local and single-user.
  - SSE buffers, `Last-Event-ID` resume, cancel, Host/Origin/CSRF and a per-launch token all serve one local user.
  - The portfolio value is the replay viewer: static page plus `replays/*.json`, with no FastAPI at all.
  - Live mode could then be a thin second step, or a Textual/Rich TUI that needs no web security surface. A TUI was never considered.
- **Python-native dashboards** (Marimo, Panel, Dash, Shiny for Python, Solara) were not considered. They were weighed only against the stlite/static criterion.
- **Un-gated UI shows the verdict.**
  - `web/` outside the fingerprint is defensible. But the UI would render `checks: passed`, recomputed arithmetic and chart values.
  - A UI bug could therefore contradict what the gate verified, with no gate to catch it.
  - Mitigation: import `run_events` and the checks from `canada_agent` (no copies), and pin schema and snapshot tests in `web/` CI.
- **Pre-started `claude -p --input-format stream-json`** is sound as an idea but unproven (the report flags this). Further costs:
  - It changes argv/stdin handling in `ask.py`, so it re-baselines.
  - The canary and the question are injected differently.
  - It needs one idle process per open tab, so a process-lifecycle policy.
  - It would not help the 20–30 s tail.
- **"Tap raises to cancel"** is safe in the code.
  - `_tee` appends inside the generator under `contextlib.closing`, so `killpg` runs. `ask()` only catches `AskError`, so the cancel exception passes through to the `finally` log.
  - Weaknesses: it fires only on the next stream event. With no `--include-partial-messages`, a long Sonnet turn means a multi-second cancel delay.
  - A cancel raised on the `result` event would discard a valid answer.
  - `capture` is typed `list[...]`, so `Tap` must subclass `list`.
- **Pre-check display of tool results.** Streaming raw `tool_result` text before `check_answer` can show attacker-injected text, even as plain text. Treat the step stream as untrusted and label it so.

### 4. Recomputed UI ranking

These use my own 1–5 ratings for three added criteria: types, explorer scalability, accessibility. They are judgement, as the report's are (`review/rank.py`). Scores are normalised to 100.

Added-criterion ratings:

| Option | Types | Explorer | A11y |
|---|---|---|---|
| Plain JS | 2 | 2 | 3 |
| Vite+TS+React | 5 | 5 | 4 |
| htmx | 3 | 3 | 4 |

| Weighting | 1st | 2nd | 3rd | Plain-JS rank |
|---|---|---|---|---|
| Original (report) | Plain JS 93 | htmx/Vue/Preact/Svelte 83 | Next 73 | 1 |
| **A**: static 5, types 15, explorer 15, a11y 10, others scaled | Vite+TS+Preact/React 87.3 | Vue and SvelteKit 84.5 | Next 80.9 | 6th (76.4) |
| **B** (developer ergonomics): maintenance 25, types 20, explorer 15, tests 10, safety/stream/a11y 10 each, static 0 | htmx+Jinja 77 | Vite+TS+Preact/React 77 | Vue and SvelteKit 73, FastHTML 73 | outside top 6 |
| **C**: safety 20, stream 20, explorer 20, types 10, maintenance 10, tests 10, charts 10, static 0 | Vite+TS+Preact/React 86 | Vue and SvelteKit 84 | htmx and Next 80 | 6th (78) |

Plain JS wins only when the static-demo weight is 15 and types, explorer and accessibility are absent. Under every reasonable alternative it drops to 6th or lower. The **runner-up (Vite+TS+Preact/React) is the more robust choice** if the UI will grow into an eval explorer (runs, gate receipts, flakiness, retrieval ablation). The report itself lists that growth as the runner-up's advantage. The backend design transfers unchanged.

### 5. What held up

- **Registry versions, rechecked:** fastapi 0.163.1, streamlit 1.67.0, gradio 6.32.0, nicegui 4.0.0, chainlit 2.12.0, sse-starlette 3.7.0, uplot 1.6.32 (modified 2025-03-14), @gradio/lite 5.45.0 (2025-09-10), htmx.org 2.0.11, react 19.3.1, vite 8.3.8, @modelcontextprotocol/server 2.4.0, claude-agent-sdk 0.3.326.
- **FastAPI SSE:** 0.135.0 uploaded 2026-03-01. The tutorial says "Added in FastAPI 0.135.0".
- **Chainlit:** GitHub API says `archived: true`, last pushed 2026-09-18. @gradio/lite lags Gradio's major version, consistent with "frozen".
- **Quotes verified verbatim:**
  - The headless doc: "waits for still-pending servers before running the first turn".
  - The legal-and-compliance doc's third-party credential sentence, and "ordinary, individual usage".
  - The MCP spec's "Servers MUST validate the Origin header" and "SHOULD bind only to localhost".
- **Lockfile:** starlette 1.10.0, sse-starlette 3.6.0, uvicorn 0.54.0 are in the repo's `uv.lock`. `fastapi` is absent, as claimed.
- **Code claims:**
  - `_stream` uses `stdin=DEVNULL`, `start_new_session=True` and `killpg` in `finally` (`ask.py` ~379, 389).
  - `ask.py:34` imports `SERVER_NAME` from `mcp_server`. `mcp_config` is at line 111.
  - `on_event` is called at lines 342 and 358.
  - `search()` and `cards()` each open their own connection (`search/tables.py:38, 46`).
  - `gate.py` `INPUTS` matches the report (lines 58–66).
  - `transcripts.slim()` is at `evals/transcripts.py` and drops timestamps. The report cited it as `transcripts.py`, a path slip with no consequence.
  - `inject-03` (r3) has `error.code = ANSWER_REJECTED` and still contains the attacker's `structured_output`.
  - The `mcp_server` import dominating CLI import time is plausible, and the 0.247 s handshake matched across the report's three runs. I did not re-run them.
- **uPlot under the proposed CSP:** the vendored file has 0 `innerHTML`, `eval`, `new Function` and `setAttribute('style')` hits.
- **Sonnet transcripts:** I reproduced n=24, median wall 7.45 s, median duration 6.98 s.
- **Not independently re-measured:** import timings, MCP handshake, in-process search cost, memory, the pytest runtime, and npm/PyPI dependency counts. I did not check the Chainlit "125 dependencies" figure or the sizes of Streamlit and stlite.