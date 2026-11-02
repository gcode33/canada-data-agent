from pathlib import Path

import psycopg
import pytest

from canada_agent.db.migrate import apply_migrations
from canada_agent.embed.voyage import Reranked
from canada_agent.search.rerank import rerank

pytestmark = pytest.mark.db
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


class FakeReranker:
    """Puts documents containing 'rent' first."""

    def __init__(self):
        self.calls = 0

    def rerank(self, query, documents):
        self.calls += 1
        order = sorted(range(len(documents)), key=lambda i: "rent" not in documents[i])
        return Reranked(order, [1.0] * len(order), 5)


@pytest.fixture
def conn(fresh_db_url):
    apply_migrations(fresh_db_url, MIGRATIONS)
    with psycopg.connect(fresh_db_url, autocommit=True) as c:
        for pid, text in [(11, "gasoline prices"), (22, "rent index"), (33, "population")]:
            c.execute(
                "INSERT INTO table_card (product_id, title, subject_codes, frequency, card_text,"
                " tsv, metadata_hash) VALUES (%s, 't', '{}', 6, %s, ''::tsvector, 'h')",
                (pid, text),
            )
        yield c


def test_reorders_candidates_and_replays_offline(conn):
    fake = FakeReranker()
    assert rerank(conn, "rent?", [11, 22, 33], fake) == [22, 11, 33]
    assert rerank(conn, "rent?", [11, 22, 33], client=None) == [22, 11, 33]
    assert fake.calls == 1


def test_a_different_candidate_list_is_not_served_a_stale_order(conn):
    rerank(conn, "rent?", [11, 22, 33], FakeReranker())
    assert rerank(conn, "rent?", [33, 22, 11], client=None) is None


def test_unrecorded_offline_is_none_and_empty_is_empty(conn):
    assert rerank(conn, "never", [11, 22], client=None) is None
    assert rerank(conn, "anything", [], client=None) == []
