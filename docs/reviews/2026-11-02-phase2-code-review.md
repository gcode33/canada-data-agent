# Code review: Phase 2 (PRs #13–#15) before merge

Date: 2026-11-02 · Reviewer: an independent Claude agent (read-only; no paid API calls) · Fixes: the last commit of #15.

This is the first review under George's rule that each phase is reviewed before it merges.
- **High-severity findings:** none.
- **Replayed evals:** reproduced every ablation row exactly (0.33/0.22, 0.67/0.49, 0.73/0.41, 0.80/0.63).
- **Verification:** every finding was confirmed by reading the code before it was fixed.

| # | Sev | Finding | Fix | Test |
|---|---|---|---|---|
| 1 | Med | The rerank cache key (question + candidate ids) ignored card text. After a card rewrite with the same top 20, the old ordering was replayed for text that no longer exists. | `upsert_card` deletes any recorded rerank that included a changed card; unchanged cards keep theirs. | `test_changed_card_text_drops_recorded_reranks_that_read_it` |
| 2 | Med | CI eval steps failed only on unrecorded questions. A change dropping hybrid-rerank from 0.80 to 0.40 stayed green. | `--min-recall` / `--min-mrr` floors. CI pins each method at its ablation row (recall exact, MRR −0.01 for rounding). | CLI check: today's floor gives exit 0; a floor of 0.87 gives "retrieval got worse … 0.800 < floor 0.870", exit 1. |
| 3 | Low | The query cache normalises case and spacing, so different spellings share the first-seen vector. | Kept on purpose and documented at `question_hash`: a stable replay key matters more than a trivial vector difference. | Existing `test_question_hash_ignores_case_and_spacing_only` |
| 4 | Low | Card embeddings had no model tag while query vectors did. A model bump would compare new queries with old cards. | Migration 0006 `embedding_model`. `canada-embed` re-embeds other-model cards; vector search only uses current-model cards. | `test_cards_from_another_model_are_re_embedded_and_never_searched` |
| 5 | Low | A 3xx from Voyage surfaced as "unexpected response shape". | An explicit `unexpected redirect: HTTP 3xx` (redirects are still never followed, so the key never travels). | `test_a_redirect_is_reported_as_such_not_as_a_parse_error` |
| 6 | Low | The ablation's rerank claim didn't carry the "one question" caveat that row 4 has. | Row 5 notes the recall gain is one question; the MRR gain is the larger, steadier effect. | n/a |

**Re-verified after the fixes:** the dump was regenerated with the new column; a fresh database + 6 migrations + `make seed` gives 584/584 embedded; all four CI eval commands pass their floors with no key; 173 offline tests pass.

**Checked and found fine (reviewer):** retry/backoff and the 60 s 429 window; the key never leaves `api.voyageai.com` (hook on every request, errors carry no headers); `canada-embed` resumability; response validation; degraded paths fail the eval instead of inflating it; deterministic RRF and SQL; Makefile pipefail and seed order; PLAN 2.2–2.5 done-when items.
