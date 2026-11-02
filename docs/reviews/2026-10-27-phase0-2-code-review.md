# Code review: Phases 0–2 (merged PRs #3–#10)

Date: 2026-10-27 · Reviewer: an independent Claude agent (read-only) · Fixes: this PR, plus #11 for finding 9.

George asked for a code review before every phase merges. Phases 0–2 merged before that rule existed, so they were reviewed afterwards. Every finding below was checked before it was fixed: finding 1 by reproducing it in Postgres, the rest by a failing scenario and a regression test.

| # | Sev | Finding | Fix | Test |
|---|---|---|---|---|
| 1 | High | Full-text search stemmed words twice. `to_tsquery('english', …)` re-stemmed lexemes that `to_tsvector` had already stemmed, so "decreasing" (`decreas` → `decrea`) and "universal" (`univers` → `univ`) could never match. | `to_tsquery('simple', …)` over the quoted lexemes. | `test_words_the_stemmer_would_cut_twice_still_match`; operators and quotes in questions are treated as data. |
| 2 | High | StatCan failures that arrive as HTTP 200 (`status: FAILED`, or `responseStatusCode != 0`) were cached for 6–24 h, breaking SPEC "errors are never cached". | `_cacheable()` checks the body before `put`. | Both failure shapes are returned but not cached; lists with no status field are still cached. |
| 3 | Med | An off-host redirect, a redirect loop or a decoding error escaped as a raw exception, not `WdsError`. | `DisallowedHostError` now subclasses `WdsError` and is never retried; the client catches `httpx.RequestError`. | Redirect loop; off-host redirect gives one request and a `WdsError`. |
| 4 | Med | Log redaction matched any key containing "token", so `input_tokens` was logged as `[REDACTED]` although SPEC §10 requires token counts. | "token" is redacted only as a whole key or suffix; `cookie` was added. | Token counts survive; `access_token` and `x-auth-token` are still redacted. |
| 5 | Med | The host allowlist ignored ports (`www150.statcan.gc.ca:8443` passed). | Ports other than 443 are refused. | A redirect to another port is refused. |
| 6 | Med | Tables that left scope stayed searchable forever. | `prune_cards()` runs after each build; members cascade; an empty scope is refused. | Prune keeps in-scope tables, removes the rest, refuses an empty scope. |
| 7 | Med | `TokenBucket` was not thread-safe. | A lock is held across refill, wait and spend. | 8 threads at 50/s take at least 7 intervals. |
| 8 | Low | A 429's `Retry-After` was ignored. | Wait for the larger of the header (capped at 30 s) and our backoff. | Header 7 → a 7.0 s sleep. |
| 9 | Low | Malformed tool arguments raised a raw `ValueError` or `TypeError`. | At the MCP boundary (#11): pydantic types, plus `ValueError` → `BAD_ARGUMENTS`. | #11 `test_bad_periods_become_bad_arguments_not_crashes`. |
| 10 | Low | A database outage in the HTTP cache crashed StatCan calls. | A cache read failure counts as a miss; a write failure is skipped. Both are logged. | An unreachable database gives a miss, not a crash. |
| 11 | Low | Two concurrent migration runs collided. | `pg_advisory_lock`; ledger rows with no file only warn. | Two concurrent runs apply once; an orphan row gives a warning. |
| 12 | Low | On long cards, the "more dimensions" marker landed after the note and could be cut. | The marker now goes before the note. | The marker precedes the note, and the card ends with the note. |

**Measured effect:** the live card rebuild rewrote 44 of 584 cards (finding 12) and pruned 0. Retrieval on the 15-question set is unchanged at recall@5 0.33 and MRR 0.22: none of those questions used a word the double stemming broke. The fix matters for questions to come.

**Checked and found fine:** the coordinate builder, cost maths, migration checksums, 409/404 handling, `untrusted_text`, and the card hash skip.
