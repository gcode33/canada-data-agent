# Canada Data Agent & Eval Lab

An AI assistant that answers questions with **live Statistics Canada data** and cites every number, plus an **eval suite that blocks any pull request that makes it worse**.

Status: in progress (PLAN Phase 2). It answers live questions end to end today:

```text
$ canada-ask --table 18100004 "By how much did the rent index in Ontario change from September 2025 to September 2026, in percent?"
Ontario's rent index (CPI, Rent component) rose 2.0% from September 2025 (161.2) to September 2026 (164.4).
Source: https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810000401
```

## How it works
- **Agent:** `canada-ask` runs Claude through `claude -p` with this project's MCP server as its only tools (ADR 0009).
- **Tools:** a stdio MCP server (`canada-mcp`) over the StatCan WDS API: host allowlist, rate limit, retries, cache, and machine-readable error codes.
- **Table search:** 584 in-scope tables, each with a short card.

| Method | recall@5 | MRR |
|---|---|---|
| Full-text (Postgres `ts_rank`) | 0.33 | 0.22 |
| Vector (Voyage `voyage-4`, exact cosine) | 0.67 | 0.49 |
| Hybrid (weighted RRF) | 0.73 | 0.41 |
| **Hybrid + Voyage `rerank-2.5`** | **0.80** | **0.63** |

Measured on a 15-question retrieval set committed before any search code. Every variant tried, including the failures, is in [`evals/ablation.md`](evals/ablation.md).

> **Full-text is not BM25.** Postgres `ts_rank` weights how often and where a word appears in a document. It has no corpus-wide term weighting (IDF) and no length saturation, so a rare word counts no more than a common one. That's one reason vector search beats it here.

## Run it
```bash
make up          # Postgres + migrations; seeds the index from data/index.sql.zst
make test        # offline tests (CI runs these plus the retrieval eval on every PR)
make live        # tests against real StatCan and Claude
uv run canada-eval-retrieval --method hybrid
```

`make seed` needs no Voyage key: question embeddings are recorded once with `make record` and replayed.

Design: [`docs/SPEC.md`](docs/SPEC.md), [`docs/PLAN.md`](docs/PLAN.md), decisions in [`docs/decisions/`](docs/decisions/).
