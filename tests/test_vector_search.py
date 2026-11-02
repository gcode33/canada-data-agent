from pathlib import Path

import psycopg
import pytest

from canada_agent.db.migrate import apply_migrations
from canada_agent.embed.index import embed_missing, vector_literal
from canada_agent.embed.voyage import DIMENSIONS, Embeddings
from canada_agent.search.vector import query_vector, question_hash, search_vector

pytestmark = pytest.mark.db
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def unit(axis: int) -> list[float]:
    v = [0.0] * DIMENSIONS
    v[axis] = 1.0
    return v


class FakeVoyage:
    """Embeds text by its first character, so tests control which vectors are near."""

    def __init__(self):
        self.calls: list[tuple[list[str], str]] = []

    def embed(self, texts, input_type):
        self.calls.append((texts, input_type))
        return Embeddings([unit(ord(t[0]) % DIMENSIONS) for t in texts], 7 * len(texts))


@pytest.fixture
def conn(fresh_db_url):
    apply_migrations(fresh_db_url, MIGRATIONS)
    with psycopg.connect(fresh_db_url, autocommit=True) as c:
        for pid, text in [(11, "a rent"), (22, "b gas"), (33, "c people")]:
            c.execute(
                "INSERT INTO table_card (product_id, title, subject_codes, frequency, card_text,"
                " tsv, metadata_hash) VALUES (%s, 't', '{}', 6, %s, ''::tsvector, 'h')",
                (pid, text),
            )
        yield c


def test_embeds_only_missing_cards_so_a_second_run_embeds_zero(conn):
    voyage = FakeVoyage()
    first = embed_missing(conn, voyage, max_tokens=10_000, log=lambda *a, **k: None)
    second = embed_missing(conn, voyage, max_tokens=10_000, log=lambda *a, **k: None)
    assert first == {"missing": 3, "embedded": 3, "batches": 1, "tokens": 21}
    assert second == {"missing": 0, "embedded": 0, "batches": 0, "tokens": 0}
    assert voyage.calls == [(["a rent", "b gas", "c people"], "document")]


def test_a_failed_batch_keeps_earlier_batches(conn):
    class FailsSecond(FakeVoyage):
        def embed(self, texts, input_type):
            if self.calls:
                raise RuntimeError("429 forever")
            return super().embed(texts, input_type)

    with pytest.raises(RuntimeError):
        embed_missing(conn, FailsSecond(), max_tokens=3, log=lambda *a, **k: None)
    left = conn.execute("SELECT count(*) FROM table_card WHERE embedding IS NULL").fetchone()
    assert left == (2,)  # one batch committed; a rerun resumes with the other two


def test_nearest_card_ranks_first(conn):
    embed_missing(conn, FakeVoyage(), max_tokens=10_000, log=lambda *a, **k: None)
    assert search_vector(conn, vector_literal(unit(ord("b"))))[0] == 22


def test_query_vectors_are_recorded_once_and_replayed_offline(conn):
    embed_missing(conn, FakeVoyage(), max_tokens=10_000, log=lambda *a, **k: None)
    voyage = FakeVoyage()
    recorded = query_vector(conn, "b  How much is GAS?", voyage)
    replayed = query_vector(conn, "b how much is gas?", client=None)  # same normalised text
    assert recorded is not None and replayed is not None
    assert len(voyage.calls) == 1 and voyage.calls[0][1] == "query"
    assert search_vector(conn, replayed)[0] == 22


def test_unrecorded_question_offline_is_none_not_a_crash(conn):
    assert query_vector(conn, "never recorded", client=None) is None


def test_question_hash_ignores_case_and_spacing_only():
    assert question_hash("Rent  in Ontario") == question_hash("rent in ontario")
    assert question_hash("rent in ontario") != question_hash("rent in quebec")


def test_cards_from_another_model_are_re_embedded_and_never_searched(conn):
    embed_missing(conn, FakeVoyage(), max_tokens=10_000, log=lambda *a, **k: None)
    conn.execute("UPDATE table_card SET embedding_model = 'old-model' WHERE product_id = 22")
    assert 22 not in search_vector(conn, vector_literal(unit(ord("b"))))  # no cross-model cosine
    again = embed_missing(conn, FakeVoyage(), max_tokens=10_000, log=lambda *a, **k: None)
    assert again["embedded"] == 1
    assert search_vector(conn, vector_literal(unit(ord("b"))))[0] == 22
