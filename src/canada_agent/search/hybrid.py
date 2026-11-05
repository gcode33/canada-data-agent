"""Hybrid table search: Reciprocal Rank Fusion of full-text and vector results.

RRF scores each table by summing 1 / (k + rank) over the lists it appears in. It uses
ranks only, so `ts_rank` scores and cosine distances never need to share a scale, and a
table ranked well by both methods beats one ranked first by only one. k = 60 is the value
from the original paper (Cormack et al., 2009); it damps the gap between ranks 1 and 2.

Plain RRF (equal weights, 50 candidates each) scored *worse* than vector alone (recall@5
0.40 vs 0.67): full-text's long noisy tail let tables that were mediocre in both lists
outscore the right table at vector rank 1. Feeding only full-text's top 10 and weighting
vector 2x gave 0.73 / MRR 0.41 (evals/ablation.md, row 4). Chosen from 12 variants on
the same 15 questions, so it is provisional until the golden dev set confirms it (4.1).
"""

from collections.abc import Sequence
from dataclasses import dataclass

import psycopg

from canada_agent.embed.voyage import EmbedError, VoyageClient
from canada_agent.search.fts import search_fts
from canada_agent.search.rerank import RERANK_CANDIDATES, rerank
from canada_agent.search.vector import query_vector, search_vector

RRF_K = 60
FTS_CANDIDATES = 10
VECTOR_CANDIDATES = 50
VECTOR_WEIGHT = 2.0


def rrf(
    rankings: Sequence[Sequence[int]],
    weights: Sequence[float] | None = None,
    k: int = RRF_K,
) -> list[int]:
    weights = weights or [1.0] * len(rankings)
    if len(weights) != len(rankings):
        raise ValueError("one weight per ranking")
    scores: dict[int, float] = {}
    for ranking, weight in zip(rankings, weights, strict=True):
        for rank, table in enumerate(ranking, 1):
            scores[table] = scores.get(table, 0.0) + weight / (k + rank)
    # Ties broken by product id, so results are deterministic.
    return sorted(scores, key=lambda t: (-scores[t], t))


@dataclass(frozen=True)
class HybridResult:
    tables: list[int]
    degraded_retrieval: bool  # True when the question had no vector: full-text only
    reranked: bool = False  # False if reranking was asked for but unavailable offline


def search_hybrid(
    conn: psycopg.Connection,
    question: str,
    client: VoyageClient | None = None,
    limit: int = 10,
    use_rerank: bool = False,
    record: bool = True,
) -> HybridResult:
    fts = search_fts(conn, question, limit=FTS_CANDIDATES)
    # Live Voyage trouble degrades search; it never fails the question (the flags say so).
    try:
        vector = query_vector(conn, question, client, record)
    except EmbedError:
        vector = None
    if vector is None:
        return HybridResult(fts[:limit], degraded_retrieval=True)
    fused = rrf(
        [fts, search_vector(conn, vector, limit=VECTOR_CANDIDATES)],
        weights=[1.0, VECTOR_WEIGHT],
    )
    if use_rerank:
        top = fused[:RERANK_CANDIDATES]
        try:
            ordered = rerank(conn, question, top, client, record)
        except EmbedError:
            ordered = None
        if ordered is not None:
            return HybridResult((ordered + fused[len(top) :])[:limit], False, reranked=True)
    return HybridResult(fused[:limit], degraded_retrieval=False)
