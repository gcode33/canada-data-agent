# 0004. Rerank hybrid candidates with Voyage `rerank-2.5`: enabled

Date: 2026-11-01 · Status: Accepted (from the measured recall@5, as PLAN 2.5 requires)

## Context
Hybrid search (weighted RRF) reached recall@5 0.73 but MRR 0.41: it finds more of the right tables than vector alone, but often ranks them lower. A cross-encoder reranker reads the question and each candidate card *together* and scores relevance directly, which bi-encoder embeddings can't do. PLAN 2.5 said `rerank-3`; Voyage has no such model. The current recommended one is `rerank-2.5`.

## Measurement (15-question retrieval set, `evals/ablation.md` row 5)
| Pipeline | recall@5 | MRR (strict) |
|---|---|---|
| Hybrid (row 4) | 0.73 | 0.41 |
| **Hybrid → `rerank-2.5` over the top 20** | **0.80** | **0.63** |

This is a single configuration, not tuned on these questions (unlike the RRF weights). The gain is one more question in the top 5, and MRR up by half: the right table moves to rank 1–2.

## Decision
- **Enabled:** `search_hybrid(..., use_rerank=True)` reranks the top 20 fused candidates; the rest keep their RRF order behind them.
- **Results are recorded and replayed** (`rerank_cache`, migration 0005), keyed by question and the exact candidate list. CI and evals need no key, and a change to search invalidates old orderings automatically.
- **Offline and unrecorded** means the hybrid order is used, with `reranked=False`. The eval counts it as degraded and fails, so it never silently loses the reranker.

## Costs
- About 10K tokens per question (20 cards × about 500 tokens). That's within Voyage's free allowance, but on the no-card tier (about 10K tokens a minute) live reranking is about one question per minute. Recorded questions cost nothing.
- Latency: one extra Voyage call (about 200–400 ms), small next to a Claude turn.

## Revisit when
- The golden dev set (PLAN 4.1) is in: re-measure with and without rerank on held-out questions.
- A cheaper `rerank-2.5-lite` could be compared as a new ablation row if cost or latency matters.

## Why not
- **No rerank:** it leaves a 0.22 MRR gain on the table for one call per question.
- **Rerank everything (584 cards):** about 300K tokens per question, for no recall gain past what the top 20 already contains.
- **An LLM (Claude) as the reranker:** slower, uses subscription turns, and harder to cache deterministically. A dedicated reranker does this job well.
