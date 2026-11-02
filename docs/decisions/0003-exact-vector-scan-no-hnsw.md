# 0003. Exact cosine scan for table search; no HNSW index

Date: 2026-11-01 · Status: Accepted

## Context
Vector search ranks the 584 in-scope table cards (1024-dim `voyage-4` embeddings) by cosine distance to the question. pgvector offers exact search (a sequential scan with `<=>`) or approximate indexes (HNSW, IVFFlat) that trade some recall for speed on large tables.

## Decision
**Exact scan, no index:** `ORDER BY embedding <=> $1::vector LIMIT k` over `table_card`.
- At 584 rows × 1024 floats (about 2.4 MB), an exact scan takes about a millisecond. That's noise next to a Voyage query embedding (about 100 ms) or a Claude turn (seconds).
- Exact search has **recall 1.0 by definition**, so every number in `evals/ablation.md` measures the embeddings and the cards, not index approximation.

## Revisit when
- The index grows past about 50k cards (e.g. all ~8k StatCan tables split into chunks), or
- p95 search latency in the eval logs exceeds 50 ms.

Then add HNSW (`vector_cosine_ops`) and record its recall@k against the exact scan as a new ablation row before switching.

## Why not
- **HNSW now:** build time and memory for no measurable gain, plus a recall loss that would blur the ablation.
- **IVFFlat:** it needs a training step on representative data and `lists`/`probes` tuning, so worse ergonomics than HNSW for no benefit at this size.
- **A separate vector database:** a second service to run and back up, duplicating Postgres, which already holds the cards, members and full-text index.
