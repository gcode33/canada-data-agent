from pathlib import Path

import psycopg
import pytest
from test_cards import cpi

from canada_agent.db.migrate import apply_migrations
from canada_agent.index.store import CardRow, prune_cards, upsert_card

pytestmark = pytest.mark.db
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


@pytest.fixture
def db(fresh_db_url):
    apply_migrations(fresh_db_url, MIGRATIONS)
    return fresh_db_url


def row(card_text="card v1") -> CardRow:
    return CardRow.from_metadata(cpi(), subject_codes=["18"], card_text=card_text, model="voyage-4")


def test_rent_is_found_by_full_text_and_stored_as_a_member(db):
    with psycopg.connect(db) as conn:
        assert upsert_card(conn, row()) is True
        hit = conn.execute(
            "SELECT product_id FROM table_card WHERE tsv @@ to_tsquery('english', 'rent')"
        ).fetchone()
        member = conn.execute(
            "SELECT name, parent_id FROM member WHERE product_id = 18100004 AND member_id = 81"
        ).fetchone()
    assert hit == (18100004,)
    assert member == ("Rent", 80)


def test_unchanged_card_is_skipped_and_changed_card_resets_its_embedding(db):
    with psycopg.connect(db) as conn:
        upsert_card(conn, row())
        conn.execute("UPDATE table_card SET embedding = array_fill(0.1, ARRAY[1024])::vector")
        assert upsert_card(conn, row()) is False  # same hash: no write, embedding kept
        kept = conn.execute("SELECT embedding IS NOT NULL FROM table_card").fetchone()[0]
        assert upsert_card(conn, row("card v2")) is True
        reset = conn.execute("SELECT embedding IS NULL FROM table_card").fetchone()[0]
    assert kept is True
    assert reset is True  # content changed, so it must be re-embedded


def test_members_are_replaced_not_duplicated(db):
    with psycopg.connect(db) as conn:
        upsert_card(conn, row("a"))
        upsert_card(conn, row("b"))
        count = conn.execute("SELECT count(*) FROM member WHERE product_id = 18100004").fetchone()
    assert count == (sum(len(d.members) for d in cpi().dimensions),)


def test_tables_that_left_scope_are_pruned_with_their_members(db):
    with psycopg.connect(db) as conn:
        upsert_card(conn, row())
        assert prune_cards(conn, {18100004}) == []  # still in scope: kept
        assert prune_cards(conn, {99999999}) == [18100004]
        left = conn.execute(
            "SELECT (SELECT count(*) FROM table_card), (SELECT count(*) FROM member)"
        )
        assert left.fetchone() == (0, 0)


def test_prune_refuses_an_empty_scope(db):
    with psycopg.connect(db) as conn, pytest.raises(ValueError, match="empty scope"):
        prune_cards(conn, set())
