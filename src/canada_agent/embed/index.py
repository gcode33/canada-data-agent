"""`canada-embed`: embed every table card that has no embedding yet.

Resumable by design: a card's embedding is cleared only when its content hash changes
(`upsert_card`), and each batch commits on its own. A rerun, or a run after a rate limit
or crash, embeds exactly what's missing, so the second run embeds 0 (PLAN 2.2).
"""

import argparse
import json
import sys
from collections.abc import Iterator

import psycopg

from canada_agent.config import Settings
from canada_agent.embed.voyage import MAX_INPUTS, EmbedError, VoyageClient


def vector_literal(values: list[float]) -> str:
    """pgvector's text form, cast with ::vector; avoids a client-side adapter dependency."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def estimate_tokens(text: str) -> int:
    # Conservative: real cards average ~4 chars per token; 3 keeps batches under budget.
    return len(text) // 3 + 1


def batches(
    rows: list[tuple[int, str]], max_tokens: int, max_inputs: int = MAX_INPUTS
) -> Iterator[list[tuple[int, str]]]:
    batch: list[tuple[int, str]] = []
    used = 0
    for row in rows:
        cost = estimate_tokens(row[1])
        if batch and (used + cost > max_tokens or len(batch) >= max_inputs):
            yield batch
            batch, used = [], 0
        batch.append(row)
        used += cost
    if batch:
        yield batch


def embed_missing(
    conn: psycopg.Connection, client: VoyageClient, max_tokens: int, log=print
) -> dict[str, int]:
    rows = conn.execute(
        "SELECT product_id, card_text FROM table_card WHERE embedding IS NULL ORDER BY product_id"
    ).fetchall()
    done = tokens = n_batches = 0
    for batch in batches(rows, max_tokens):
        result = client.embed([text for _, text in batch], "document")
        with conn.transaction():
            for (pid, _), vec in zip(batch, result.vectors, strict=True):
                conn.execute(
                    "UPDATE table_card SET embedding = %s::vector WHERE product_id = %s",
                    (vector_literal(vec), pid),
                )
        done += len(batch)
        tokens += result.total_tokens
        n_batches += 1
        log(f"  embedded {done}/{len(rows)} ({tokens} tokens)", file=sys.stderr)
    return {"missing": len(rows), "embedded": done, "batches": n_batches, "tokens": tokens}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--batch-tokens",
        type=int,
        default=8_000,
        help="estimated tokens per request; small enough for Voyage's no-card free tier",
    )
    args = parser.parse_args()
    settings = Settings()
    try:
        client = VoyageClient(settings.voyage_api_key.get_secret_value())
        with psycopg.connect(settings.database_url, autocommit=True) as conn:
            summary = embed_missing(conn, client, args.batch_tokens)
    except EmbedError as exc:
        sys.exit(f"canada-embed: {exc} (already-embedded cards are kept; rerun to resume)")
    print(json.dumps(summary, indent=2))
