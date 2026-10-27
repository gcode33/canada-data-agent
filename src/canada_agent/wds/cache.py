"""Response cache for successful WDS calls. Errors and 409s are never stored (SPEC §8)."""

import hashlib
import json
import logging
import time
from typing import Any, Literal, Protocol

import psycopg
from psycopg.types.json import Jsonb

Kind = Literal["metadata", "data"]
TTL_SECONDS: dict[str, int] = {"metadata": 24 * 3600, "data": 6 * 3600}
log = logging.getLogger(__name__)


def cache_key(method: str, url: str, body: Any) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{method} {url} {canonical}".encode()).hexdigest()


class Cache(Protocol):
    def get(self, key: str, now: float | None = None) -> Any | None: ...
    def put(self, key: str, url: str, body: Any, kind: Kind, now: float | None = None) -> None: ...


class MemoryCache:
    def __init__(self) -> None:
        self._items: dict[str, tuple[Any, float]] = {}

    def get(self, key: str, now: float | None = None) -> Any | None:
        item = self._items.get(key)
        if item is None or item[1] <= (time.time() if now is None else now):
            return None
        return item[0]

    def put(self, key: str, url: str, body: Any, kind: Kind, now: float | None = None) -> None:
        self._items[key] = (body, (time.time() if now is None else now) + TTL_SECONDS[kind])


class PostgresCache:
    """`http_cache` table (migration 0002). `now` is epoch seconds, injectable for tests.

    The cache is an optimisation: if Postgres is down, a read is a miss and a write is
    skipped (logged), so StatCan is still reachable.
    """

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def get(self, key: str, now: float | None = None) -> Any | None:
        now = time.time() if now is None else now
        try:
            with psycopg.connect(self.database_url) as conn:
                row = conn.execute(
                    "SELECT body FROM http_cache"
                    " WHERE key = %s AND extract(epoch FROM fetched_at) + ttl_seconds > %s",
                    (key, now),
                ).fetchone()
        except psycopg.Error as exc:
            log.warning(
                "cache read failed; treating as a miss", extra={"error": type(exc).__name__}
            )
            return None
        return row[0] if row else None

    def put(self, key: str, url: str, body: Any, kind: Kind, now: float | None = None) -> None:
        now = time.time() if now is None else now
        try:
            self._put(key, url, body, kind, now)
        except psycopg.Error as exc:
            log.warning("cache write skipped", extra={"error": type(exc).__name__})

    def _put(self, key: str, url: str, body: Any, kind: Kind, now: float) -> None:
        with psycopg.connect(self.database_url) as conn:
            conn.execute(
                "INSERT INTO http_cache (key, url, body, fetched_at, ttl_seconds)"
                " VALUES (%s, %s, %s, to_timestamp(%s), %s)"
                " ON CONFLICT (key) DO UPDATE SET body = EXCLUDED.body,"
                " fetched_at = EXCLUDED.fetched_at, ttl_seconds = EXCLUDED.ttl_seconds",
                (key, url, Jsonb(body), now, TTL_SECONDS[kind]),
            )
