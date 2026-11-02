"""Rerank hybrid candidates with Voyage `rerank-2.5` (PLAN step 2.5, ADR 0004).

A cross-encoder reads the question and each card *together*, so it can judge relevance
better than comparing two separately computed vectors. It's too slow and costly to run
over every table, so it reorders only the top `RERANK_CANDIDATES` from hybrid search.

Results are cached per (question, exact candidate list): replayed offline, re-fetched
only when the candidates change.
"""

import hashlib

import psycopg

from canada_agent.embed.voyage import RERANK_MODEL, VoyageClient
from canada_agent.search.vector import question_hash

RERANK_CANDIDATES = 20


def candidates_hash(candidates: list[int]) -> str:
    return hashlib.sha256(",".join(map(str, candidates)).encode()).hexdigest()


def rerank(
    conn: psycopg.Connection,
    question: str,
    candidates: list[int],
    client: VoyageClient | None = None,
) -> list[int] | None:
    """`candidates` reordered by relevance, or None if unrecorded and offline."""
    if not candidates:
        return []
    key = (RERANK_MODEL, question_hash(question), candidates_hash(candidates))
    row = conn.execute(
        "SELECT ranked FROM rerank_cache"
        " WHERE model = %s AND question_hash = %s AND candidates_hash = %s",
        key,
    ).fetchone()
    if row:
        return list(row[0])
    if client is None:
        return None
    cards = dict(
        conn.execute(
            "SELECT product_id, card_text FROM table_card WHERE product_id = ANY(%s)",
            (candidates,),
        ).fetchall()
    )
    present = [pid for pid in candidates if pid in cards]
    result = client.rerank(question, [cards[pid] for pid in present])
    ranked = [present[i] for i in result.order]
    conn.execute(
        "INSERT INTO rerank_cache (model, question_hash, candidates_hash, ranked)"
        " VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
        (*key, ranked),
    )
    return ranked
