"""Vector table search: exact cosine scan over `table_card.embedding`, no HNSW (ADR 0003).

Query vectors come from `query_embedding` first. On a miss they are embedded live only if
a Voyage client is given (and then recorded); otherwise the caller gets None and falls
back to full-text, flagged `degraded_retrieval`. So CI replays recorded questions with
no key, and an unrecorded question still gets an answer.
"""

import hashlib

import psycopg

from canada_agent.embed.index import vector_literal
from canada_agent.embed.voyage import MODEL, VoyageClient


def question_hash(question: str) -> str:
    normalised = " ".join(question.split()).casefold()
    return hashlib.sha256(normalised.encode()).hexdigest()


def query_vector(
    conn: psycopg.Connection, question: str, client: VoyageClient | None = None
) -> str | None:
    """The question's embedding as a pgvector literal, or None if unrecorded and offline."""
    key = question_hash(question)
    row = conn.execute(
        "SELECT embedding::text FROM query_embedding WHERE model = %s AND question_hash = %s",
        (MODEL, key),
    ).fetchone()
    if row:
        return row[0]
    if client is None:
        return None
    literal = vector_literal(client.embed([question], "query").vectors[0])
    conn.execute(
        "INSERT INTO query_embedding (model, question_hash, question, embedding)"
        " VALUES (%s, %s, %s, %s::vector) ON CONFLICT DO NOTHING",
        (MODEL, key, question, literal),
    )
    return literal


def search_vector(conn: psycopg.Connection, vector: str, limit: int = 50) -> list[int]:
    # <=> is cosine distance. 584 rows: an exact scan is ~1 ms, so an approximate index
    # would only add recall loss (ADR 0003).
    rows = conn.execute(
        "SELECT product_id FROM table_card WHERE embedding IS NOT NULL"
        " ORDER BY embedding <=> %s::vector, product_id LIMIT %s",
        (vector, limit),
    )
    return [r[0] for r in rows]
