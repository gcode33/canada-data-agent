from pathlib import Path

import psycopg
import pytest

from canada_agent.db.migrate import apply_migrations
from canada_agent.search.fts import search_fts

pytestmark = pytest.mark.db
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

TABLES = {
    18100004: "Consumer Price Index monthly | Ontario | Shelter | Rented accommodation | Rent",
    18100001: "Monthly average retail prices for gasoline and fuel oil | Toronto | Regular",
    17100009: "Population estimates quarterly | British Columbia | Ontario",
}


@pytest.fixture
def conn(fresh_db_url):
    apply_migrations(fresh_db_url, MIGRATIONS)
    with psycopg.connect(fresh_db_url) as c:
        for pid, text in TABLES.items():
            c.execute(
                "INSERT INTO table_card (product_id, title, subject_codes, frequency, card_text,"
                " tsv, metadata_hash) VALUES (%s, %s, '{}', 6, %s,"
                " to_tsvector('english', %s), 'h')",
                (pid, text.split(" | ")[0], text, text),
            )
        yield c


def test_or_query_finds_a_table_from_a_natural_question(conn):
    # An AND query would need every word ("much", "cost", ...) and would match nothing.
    assert (
        search_fts(conn, "How much does a litre of regular gasoline cost in Toronto?")[0]
        == 18100001
    )


def test_ranks_the_best_match_first(conn):
    assert search_fts(conn, "rent in Ontario")[0] == 18100004


def test_question_of_only_stop_words_returns_nothing(conn):
    assert search_fts(conn, "what is the") == []


def test_respects_the_limit(conn):
    assert len(search_fts(conn, "Ontario", limit=1)) == 1


def test_words_the_stemmer_would_cut_twice_still_match(conn):
    # 'decreasing' is stored as 'decreas'; stemming the query again gave 'decrea' (no match).
    conn.execute(
        "INSERT INTO table_card (product_id, title, subject_codes, frequency, card_text, tsv,"
        " metadata_hash) VALUES (99000001, 'x', '{}', 6, 'x',"
        " to_tsvector('english', 'Decreasing universal series'), 'h')"
    )
    assert search_fts(conn, "decreasing") == [99000001]
    assert search_fts(conn, "universal") == [99000001]


def test_quotes_and_operators_in_the_question_are_data(conn):
    assert search_fts(conn, "rent's & | ! (Ontario) <-> :*")[0] == 18100004
