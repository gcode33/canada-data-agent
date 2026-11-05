"""The logic of the `search_tables` tool (SPEC §8): question in, top-k table cards out.

Runtime discovery: the agent finds the few relevant tables itself instead of being handed
an id or loading all 584 cards into context (the idea Uber's MCP gateway calls discovery;
docs/ideas/0001-uber-mcp-gateway.md). Uses hybrid search + rerank (0.80 recall@5).
"""

from typing import Any, Protocol

import psycopg

from canada_agent.embed.voyage import VoyageClient
from canada_agent.search.hybrid import HybridResult, search_hybrid
from canada_agent.series.service import table_url
from canada_agent.untrusted import untrusted_text

MAX_QUERY_CHARS = 200
MAX_K = 5
CARD_LIMIT = 2400  # card_text is already capped at this when built (index/cards.py)


class TableIndex(Protocol):
    def search(self, query: str, limit: int) -> HybridResult: ...
    def cards(self, product_ids: list[int]) -> dict[int, tuple[str, str]]: ...  # title, card


class PostgresTableIndex:
    """The real index. Without a Voyage key, unrecorded queries fall back to full-text."""

    def __init__(self, database_url: str, client: VoyageClient | None) -> None:
        self.database_url, self.client = database_url, client

    def _connect(self) -> psycopg.Connection:
        # Per call, like PostgresCache: starting needs no database, and a restart heals itself.
        return psycopg.connect(self.database_url, autocommit=True)

    def search(self, query: str, limit: int) -> HybridResult:
        with self._connect() as conn:
            # record=False: the tools are read-only, and the agent's queries (which injected
            # text could steer) must never reach the committed index dump.
            return search_hybrid(
                conn, query, self.client, limit=limit, use_rerank=True, record=False
            )

    def cards(self, product_ids: list[int]) -> dict[int, tuple[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT product_id, title, card_text FROM table_card WHERE product_id = ANY(%s)",
                (product_ids,),
            ).fetchall()
        return {pid: (title, card) for pid, title, card in rows}


def search_tables(index: TableIndex, query: str, k: int = MAX_K) -> dict[str, Any]:
    query = " ".join(query.split())
    if not query:
        raise ValueError("query is empty")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"query is longer than {MAX_QUERY_CHARS} characters")
    if not 1 <= k <= MAX_K:
        raise ValueError(f"k must be between 1 and {MAX_K}")

    found = index.search(query, limit=k)
    cards = index.cards(found.tables)
    return {
        "query": query,
        "results": [
            {
                "product_id": pid,
                "title": untrusted_text(cards[pid][0], 300),
                "card": untrusted_text(cards[pid][1], CARD_LIMIT),
                "source_url": table_url(pid),  # built from the id, never taken from data
            }
            for pid in found.tables
            if pid in cards
        ],
        # Tells the model (and the logs) that ranking ran without vectors or reranking.
        "degraded_retrieval": found.degraded_retrieval or not found.reranked,
    }
