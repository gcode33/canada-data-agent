# 0010. A web UI with a replay-only public demo, and `web/` outside the gate

Date: 2026-11-18 · Status: Accepted (A8, approved by George 2026-11-18)

## Context
Until A8 the agent was a CLI (SPEC §3: "no chat UI or hosted site"). A8 adds a web UI. Three facts shape it:
- **The agent runs on George's subscription** through `claude -p` (ADR 0009). Anthropic's terms say: "Anthropic does not permit third-party developers to … route requests through Free, Pro, Max, or Ultra plan credentials on behalf of their users" (code.claude.com/docs/en/legal-and-compliance, checked 2026-11-17). A public page therefore can't ask Claude anything.
- **A live Sonnet question takes up to ~27 s** (`docs/demo/ask-trace.txt`), so the user needs to see progress.
- **Tool results can carry injected text.** Poisoned cards, member names and error bodies (SPEC §11) must never reach a browser as anything but inert text, and never before the runtime checks have passed.

## Decision
- **Two modes, one page.**
  - **Demo mode** is a static site on GitHub Pages that replays 24 recorded dev runs and never calls a model.
  - **Live mode** runs only on George's machine, at `127.0.0.1`.
  - Both feed one reducer through one event contract (A8 §9).
- **Live transport: one `POST /api/ask` whose response body is a Server-Sent Events stream,** read with `fetch`. Stop is `abort()`.
- **Local protection:** a Host check (`127.0.0.1`), an exact `Origin`, `Sec-Fetch-Site: same-origin` and a JSON content type. **No token:** a local process that could steal one could run `claude` itself.
- **Nothing the checks could still reject is shown first.**
  - Step events carry server-built summaries ("13 points, 2025-09 to 2026-09") and redacted, capped arguments, never tool text.
  - `series` and `answer` are emitted only once an `AskResult` exists.
  - A failed run ends with `run_failed` and a fixed message.
- **`web/` is its own uv project, outside the gate's fingerprint.** It depends on `canada-data-agent` through an editable path source and imports every rule it needs (`run_events`, `CITABLE_URL`, `foreign_links`, `untrusted_text`, `series_values`, the error codes). It can change how a result looks, not what the agent does. A test fails if `web/` re-implements any of those rules. Contract and fidelity tests tie what the page shows to the recorded runs.
- **Front end:** Vite + React + TypeScript, with a hand-written event union checked against the pydantic schema, and hand-written SVG charts.

## Why not
- **Next.js or another server-rendering framework:** the backend is already Python, so a second server would duplicate it.
- **A no-build plain-JavaScript page:** it won the first scoring only while "static demo" carried a heavy weight and type safety, accessibility and room to grow carried none. Under three other weightings it fell to 6th or lower (`docs/reviews/2026-11-17-stack-review.md`). Vite's output is static files anyway.
- **Streamlit, Gradio, NiceGUI or Chainlit:**
  - no static demo without shipping a Python runtime to the browser;
  - looser defaults (Streamlit, NiceGUI and FastHTML bind `0.0.0.0`);
  - Chainlit's repository is archived.
- **POST plus a GET event stream:** a same-origin GET carries no `Origin` header, the browser reconnects on its own, and a run can start with no one listening.
- **A per-launch token:** any process that can fetch the page gets the cookie, and cookies aren't isolated by port (RFC 6265 §8.5).
- **A hosted live mode, even for friends:** it would route other people's requests through George's subscription credentials.
- **Recharts:** it was verified CSP-clean, but it's ~110 kB gzip more, and its default chart is an unnamed `role="application"`. 10 of the 20 answer replays have ≤ 3 points, so most show a value tile anyway. The front-end critic dissented; it's recorded in A8 §16 D4.

## Consequences
- Two languages in the repo, but TypeScript only in `web/frontend`, with the agent and every rule in Python.
- The demo shows pre-release recordings (commit 9e183c1, 2026-11-07), labelled as such on every replay.
- `web/` changes never need a re-baseline. Its own CI job runs on every PR, with no secrets.
