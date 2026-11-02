# Retrieval ablation

Measured on the 15-question retrieval set (`evals/retrieval/questions.yaml`), which was committed before any search code. Index: 584 in-scope tables. **recall@5:** is the expected table in the top 5? **MRR:** mean of 1/rank of the first hit, 0 if absent. Strict = the first listed table; lenient = any listed table. Reproduce with `canada-eval-retrieval --method <method>`.

| # | Method | recall@5 strict | recall@5 lenient | MRR strict | MRR lenient | Date |
|---|---|---|---|---|---|---|
| 1 | Full-text, ORed terms, `ts_rank_cd` over title + all members | 0.13 | 0.13 | 0.05 | 0.05 | 2026-10-27 |
| 2 | **Full-text v2:** title weighted A, member names D with positions stripped, `ts_rank` | **0.33** | **0.33** | **0.22** | **0.22** | 2026-10-27 |
| 3 | **Vector only:** Voyage `voyage-4` (1024-d), exact cosine scan (ADR 0003) | **0.67** | **0.67** | **0.49** | **0.49** | 2026-11-01 |
| 4a | Hybrid: plain RRF (k=60) of 2 + 3, 50 candidates each, equal weights | 0.40 | 0.40 | 0.29 | 0.29 | 2026-11-01 |
| 4 | **Hybrid: weighted RRF:** full-text top 10 + vector top 50, vector weight 2 (provisional) | **0.73** | **0.73** | 0.41 | 0.41 | 2026-11-01 |
| 5 | Hybrid + `rerank-3` | pending | | | | |

## What we tried for full-text, and why v2 won
- **Length normalisation** (`ts_rank_cd` flags 1, 2, 8, 16, 32): no flag beat row 1, and `len` (2) fell to 0.00. Long tables weren't the core problem.
- **Title weighted A, members D, positions kept:** still 0.13. Weights alone don't help when member words are counted per occurrence.
- **Diagnosis:** for "How many people live in British Columbia right now?", the top hits were census-tract and census-subdivision tables. They list thousands of places, so "British Columbia" appears in them hundreds of times. Counting every occurrence let sheer repetition win.
- **Fix:** strip positions from member names, so each word counts **once per table**, and rank by `ts_rank`. Title words keep their weight. Recall@5 went from 0.13 to 0.33 and MRR from 0.05 to 0.22.

**Re-measured 2026-10-27 after the code-review fix to double stemming** (`docs/reviews/2026-10-27-phase0-2-code-review.md`, finding 1): row 2 is unchanged at 0.33 / 0.22. None of the 15 questions used a word the second stemming pass broke.

## What full-text can't fix
Most remaining misses are **vocabulary mismatches**: the question's key word isn't in the expected table at all.

| Question says | The table says |
|---|---|
| "jobless rate" (r04) | "unemployment rate" |
| "gas" (r06) | "gasoline" |
| "people live" (r08) | "population" |
| "moved" (r09) | "migrants" |
| "unfilled positions" (r11) | "job vacancies" |

That's the gap embeddings are meant to close, and row 3 shows they mostly do.

## What vectors fixed, and what they didn't (row 3)
- **Fixed 4 of the 5 vocabulary gaps:** "gas" (r06), "people live" (r08), "moved" (r09) → rank 1, and "unfilled positions" (r11) → rank 2.
- **Still missed:** "jobless rate" (r04) is at rank 16. r01, r03, r05 and r12 also fall outside the top 5.
- **The two methods are complementary.** Full-text finds r01 and r03, which vector misses; vector finds 8 that full-text misses. Their top-5 hits together cover 12 of 15 questions, which is the case for hybrid RRF (row 4).
- Queries are recorded once (`make record`) and replayed from `query_embedding`, so CI reproduces this row with no key.

## Hybrid: why plain RRF lost, and the sweep (row 4)
Plain RRF scored **worse than vector alone** (0.40 vs 0.67). Full-text's 50 candidates are mostly noise for questions it can't match. A table that's mediocre in both lists (ranks 3 and 10: 1/63 + 1/70 = 0.030) outscores the right table at vector rank 1 that full-text never found (1/61 = 0.016).

| full-text candidates | vector weight 1 | 2 | 3 |
|---|---|---|---|
| 50 | 0.40 / 0.29 | 0.40 / 0.34 | 0.60 / 0.39 |
| 20 | 0.40 / 0.32 | 0.53 / 0.35 | 0.60 / 0.40 |
| 10 | 0.67 / 0.35 | **0.73 / 0.41** | 0.73 / 0.47 |
| 5 | 0.67 / 0.34 | 0.73 / 0.41 | 0.73 / 0.46 |

Cells are recall@5 / MRR (strict).

**Chosen:** top 10, weight 2. It's the smallest change that reaches the best recall, and it isn't the single best cell.

**Caveats:**
- It was picked from 12 variants on the same 15 questions, and 0.73 vs 0.67 is **one question**, so it's provisional until the golden dev set (PLAN 4.1) confirms it.
- MRR is below vector-only (0.41 vs 0.49): hybrid finds more right tables but ranks some lower. That's what the reranker (row 5) is meant to fix.

