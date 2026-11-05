# Code review: Phase 3 (PRs #17–#18) before merge

Date: 2026-11-05 · Reviewer: an independent Claude agent (read-only) · Fixes: the last commit of #18.

| # | Sev | Finding | Fix |
|---|---|---|---|
| 1 | High | An outage became a clean refusal: database down → MCP server failed → no tools → "refused", exit 0 (confirmed on the real CLI). | `run_events` requires server status `connected` from the init event; a refusal where every tool call failed is `UPSTREAM_UNAVAILABLE`; the database connects per call, so the server starts without it. |
| 2 | High | Citations and values weren't tied to tool results; a made-up StatCan URL from memory passed. | `check_grounded`: cited URLs and vector ids must have been returned in this run, and an answer needs a successful `get_series`. `check_answer` allows only the exact StatCan table URL form, in citations, prose and refusals. |
| 3 | High | Over budget didn't stop the agent while the exception was held. | `contextlib.closing` around the stream; tested through the real raising path. |
| 4 | Med | Database errors had no code; a dead connection never recovered. | `UPSTREAM_UNAVAILABLE`; per-call connections. |
| 5 | Med | Unread stderr could block the child; only the direct child was killed. | Stderr drained in a thread; own process group, killed as a group. |
| 6 | Med | Agent queries were stored and could reach the committed dump; `http_cache` never pruned. | Tool path has `record=False`; expired cache rows are deleted on write. |
| 7 | Med | Canary check was exact-match, on the final answer only. | Case- and punctuation-insensitive, also on every tool argument. Encoded forms still pass; the README says so. |
| 8 | Med | A raw dimension name reached the model in a `BAD_MEMBERS` error. | Escaped with `untrusted_text`. |
| 9 | Med | Nothing told the model what `truncated` and `degraded_retrieval` mean. | Prompt rules, plus `first_period_returned`. |
| 10 | Med | The prompt file wasn't packaged. | Moved into the package, loaded with `importlib.resources`. |
| 11 | Med | Failed runs left no log; no cost limit; no "show the arithmetic". | Logged in `finally` with outcome and tool arguments (`logs/ask.jsonl`); `--max-budget-usd`; prompt rule. Cache hits and the GIF are amended in PLAN D4. |
| 12 | Low | The database URL was visible in `ps`. | Passed by environment. The per-run canary stays in argv: it's random, local and short-lived. |
