"""A deliberately small migration runner: numbered SQL files, one transaction each.

Files in `migrations/` are named `NNNN_description.sql` and applied in numeric order.
Each applied file is recorded in `schema_migrations` with a SHA-256 checksum, so editing
a migration after it has run is detected and refused instead of silently diverging.
See ADR 0002 for why this exists instead of an ORM-based tool.
"""

import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

FILENAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")

LEDGER = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     integer PRIMARY KEY,
    name        text        NOT NULL,
    checksum    text        NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now()
)
"""


class MigrationError(Exception):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode()).hexdigest()


def discover(directory: Path) -> list[Migration]:
    migrations: dict[int, Migration] = {}
    for path in directory.glob("*.sql"):
        match = FILENAME.match(path.name)
        if not match:
            raise MigrationError(f"{path.name}: expected NNNN_description.sql")
        version = int(match.group(1))
        if version in migrations:
            other = migrations[version].name
            raise MigrationError(f"duplicate version {version}: {path.name}, {other}")
        migrations[version] = Migration(version, path.name, path.read_text())
    return [migrations[v] for v in sorted(migrations)]


ADVISORY_LOCK_ID = 727_001  # any constant unique to this app's migrations


def apply_migrations(database_url: str, directory: Path) -> list[Migration]:
    """Apply every pending migration in order. Returns the ones applied this run."""
    pending = discover(directory)
    applied_now: list[Migration] = []
    # autocommit so each `conn.transaction()` below is a real, independent transaction.
    # Without it the first SELECT opens an implicit transaction, every block becomes a
    # savepoint inside it, and one failure rolls back migrations that already "applied".
    with psycopg.connect(database_url, autocommit=True) as conn:
        # Two runs at once (e.g. two containers starting) would both apply the same file.
        # A session-level advisory lock queues the second run; it then reads the ledger
        # the first one wrote. The lock is released when the connection closes.
        conn.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_LOCK_ID,))
        conn.execute(LEDGER)
        done = {v: c for v, c in conn.execute("SELECT version, checksum FROM schema_migrations")}
        if orphans := sorted(set(done) - {m.version for m in pending}):
            # Usually a branch older than the database; worth knowing, not worth failing on.
            print(f"warning: applied migrations with no file here: {orphans}", file=sys.stderr)
        for migration in pending:
            if migration.version in done:
                if done[migration.version] != migration.checksum:
                    raise MigrationError(
                        f"{migration.name} was edited after it was applied (checksum mismatch); "
                        "add a new migration instead"
                    )
                continue
            try:
                with conn.transaction():
                    conn.execute(migration.sql)
                    conn.execute(
                        "INSERT INTO schema_migrations (version, name, checksum)"
                        " VALUES (%s, %s, %s)",
                        (migration.version, migration.name, migration.checksum),
                    )
            except psycopg.Error as exc:
                raise MigrationError(f"{migration.name} failed: {exc}") from exc
            applied_now.append(migration)
    return applied_now


def main() -> None:
    url = os.environ.get("DATABASE_URL", "postgresql://canada:canada@localhost:5432/canada")
    directory = Path(os.environ.get("MIGRATIONS_DIR", "migrations"))
    try:
        applied = apply_migrations(url, directory)
    except MigrationError as exc:
        sys.exit(f"migration failed: {exc}")
    print(f"applied {len(applied)} migration(s)" + "".join(f"\n  {m.name}" for m in applied))


if __name__ == "__main__":
    main()
