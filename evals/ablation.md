# Retrieval ablation

Measured on the 15-question retrieval set (`evals/retrieval/questions.yaml`), which was committed before any search code. Index: 584 in-scope tables. **recall@5:** is the expected table in the top 5? **MRR:** mean of 1/rank of the first hit, 0 if absent. Strict = the first listed table; lenient = any listed table. Reproduce with `canada-eval-retrieval --method <method>`.

| # | Method | recall@5 strict | recall@5 lenient | MRR strict | MRR lenient | Date |
|---|---|---|---|---|---|---|
| 1 | Full-text, ORed terms, `ts_rank_cd` over title + all members | 0.13 | 0.13 | 0.05 | 0.05 | 2026-10-27 |
| 2 | **Full-text v2:** title weighted A, member names D with positions stripped, `ts_rank` | **0.33** | **0.33** | **0.22** | **0.22** | 2026-10-27 |
| 3 | Vector only (Voyage `voyage-4`) | pending | | | | needs `VOYAGE_API_KEY` |
| 4 | Hybrid: RRF of 2 + 3 | pending | | | | |
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

That's the gap embeddings are meant to close; rows 3–4 will measure whether they do.
