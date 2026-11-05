from pathlib import Path

import psycopg
import pytest

from canada_agent.db.migrate import apply_migrations
from canada_agent.wds.cache import TTL_SECONDS, PostgresCache

pytestmark = pytest.mark.db

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


@pytest.fixture
def cache(fresh_db_url):
    apply_migrations(fresh_db_url, MIGRATIONS)
    return PostgresCache(fresh_db_url)


def test_ttls_match_the_spec():
    assert TTL_SECONDS == {"metadata": 24 * 3600, "data": 6 * 3600}


def test_hit_before_ttl_and_miss_after(cache):
    cache.put("k", "https://www150.statcan.gc.ca/x", {"v": 1}, kind="data", now=0.0)
    assert cache.get("k", now=6 * 3600 - 1) == {"v": 1}
    assert cache.get("k", now=6 * 3600 + 1) is None


def test_metadata_lives_longer_than_data(cache):
    cache.put("meta", "u", {"m": 1}, kind="metadata", now=0.0)
    cache.put("data", "u", {"d": 1}, kind="data", now=0.0)
    assert cache.get("meta", now=7 * 3600) == {"m": 1}
    assert cache.get("data", now=7 * 3600) is None


def test_put_overwrites(cache):
    cache.put("k", "u", {"v": 1}, kind="data", now=0.0)
    cache.put("k", "u", {"v": 2}, kind="data", now=10.0)
    assert cache.get("k", now=20.0) == {"v": 2}


def test_unreachable_database_is_a_miss_not_a_crash():
    down = PostgresCache("postgresql://nobody@127.0.0.1:1/none?connect_timeout=1")
    assert down.get("k") is None
    down.put("k", "url", {"a": 1}, "data")  # skipped, logged, no exception


def test_expired_rows_are_deleted_on_write(cache):
    cache.put("old", "u", {"a": 1}, "data", now=1000.0)
    cache.put("new", "u", {"a": 2}, "data", now=1000.0 + TTL_SECONDS["data"] + 1)
    with psycopg.connect(cache.database_url) as conn:
        assert conn.execute("SELECT key FROM http_cache").fetchall() == [("new",)]
