from pathlib import Path

import psycopg
import pytest
from test_vector_search import FakeVoyage

from canada_agent.db.migrate import apply_migrations
from canada_agent.embed.index import embed_missing
from canada_agent.embed.voyage import EmbedError
from canada_agent.search.hybrid import rrf, search_hybrid


def test_rrf_rewards_agreement_between_lists():
    # 7 is 2nd in both lists: 2/62 = 0.0323 beats 1st in one list only (1/61 = 0.0164).
    assert rrf([[1, 7, 3], [2, 7, 4]])[0] == 7


def test_rrf_scores_match_the_formula():
    # k=60: table 1 = 1/61 + 1/62; table 2 = 1/62 + 1/61 -> tie, broken by id.
    assert rrf([[1, 2], [2, 1]]) == [1, 2]
    assert rrf([[5]], k=0) == [5]


def test_weights_let_one_method_count_more():
    # Unweighted, 1 (rank 1 in A) beats 2 (rank 1 in B) only by the id tie-break;
    # doubling B's weight makes 2 win outright.
    assert rrf([[1], [2]]) == [1, 2]
    assert rrf([[1], [2]], weights=[1.0, 2.0]) == [2, 1]


def test_one_weight_per_ranking():
    with pytest.raises(ValueError, match="one weight"):
        rrf([[1], [2]], weights=[1.0])


def test_empty_lists_fuse_to_nothing():
    assert rrf([[], []]) == []


MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


@pytest.fixture
def conn(fresh_db_url):
    apply_migrations(fresh_db_url, MIGRATIONS)
    with psycopg.connect(fresh_db_url, autocommit=True) as c:
        for pid, text in [(11, "a rent ontario"), (22, "b gasoline toronto")]:
            c.execute(
                "INSERT INTO table_card (product_id, title, subject_codes, frequency, card_text,"
                " tsv, metadata_hash) VALUES (%s, 't', '{}', 6, %s,"
                " to_tsvector('english', %s), 'h')",
                (pid, text, text),
            )
        embed_missing(c, FakeVoyage(), max_tokens=10_000, log=lambda *a, **k: None)
        yield c


@pytest.mark.db
def test_unrecorded_question_offline_falls_back_to_full_text_and_says_so(conn):
    result = search_hybrid(conn, "rent in ontario", client=None)
    assert result.degraded_retrieval is True
    assert result.tables == [11]


@pytest.mark.db
def test_recorded_question_fuses_both_methods(conn):
    # FakeVoyage embeds by first letter: "b..." is nearest card 22, which full-text also finds.
    result = search_hybrid(conn, "b gasoline price", client=FakeVoyage())
    assert result.degraded_retrieval is False
    assert result.tables[0] == 22


class RateLimited(FakeVoyage):
    def embed(self, texts, input_type):
        raise EmbedError("HTTP 429 after 1 attempts")

    def rerank(self, query, documents):
        raise EmbedError("HTTP 429 after 1 attempts")


class EmbedsButRerankLimited(FakeVoyage):
    def rerank(self, query, documents):
        raise EmbedError("HTTP 429 after 1 attempts")


@pytest.mark.db
def test_a_rate_limited_embedding_falls_back_to_full_text_and_says_so(conn):
    result = search_hybrid(conn, "rent in ontario", RateLimited(), use_rerank=True)
    assert result.tables == [11]
    assert result.degraded_retrieval is True


@pytest.mark.db
def test_a_rate_limited_rerank_keeps_the_hybrid_order_and_says_so(conn):
    result = search_hybrid(conn, "b gasoline", EmbedsButRerankLimited(), use_rerank=True)
    assert result.tables[0] == 22
    assert result.degraded_retrieval is False
    assert result.reranked is False


@pytest.mark.db
def test_the_tool_path_records_nothing(conn):
    search_hybrid(conn, "b gasoline", FakeVoyage(), use_rerank=False, record=False)
    assert conn.execute("SELECT count(*) FROM query_embedding").fetchone() == (0,)
