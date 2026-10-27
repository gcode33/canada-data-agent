# 0002. Numbered SQL migrations with a small runner, no ORM

Date: 2026-10-27 · Status: Accepted

## Context
The schema is small: about 4 tables, plus pgvector and a full-text column. The SQL itself is the interesting part (`vector(1024)`, `tsvector`, RRF queries), so it should be readable and reviewable as SQL. The project also needs migrations in CI against a service container, and an index dump (`make seed`) that restores onto a migrated schema.

## Decision
Plain SQL files `migrations/NNNN_description.sql`, applied in numeric order by about 80 lines of Python (`canada_agent.db.migrate`):
- Each file runs in its own transaction.
- Each applied file is recorded in `schema_migrations` with a SHA-256 checksum.
- An applied file that's later edited is **refused**, so a new migration has to be written instead.
- Badly named or duplicate-version files are rejected before anything runs.

## Why not
- **Alembic / SQLAlchemy:** brings an ORM model layer the project doesn't use, plus autogeneration that handles `vector` and `tsvector` poorly. It's more to explain than to gain.
- **A hosted tool (Flyway, Sqitch):** another runtime in CI for four tables.
- **`CREATE TABLE IF NOT EXISTS` at startup:** no history, no way to change a column safely, nothing to test.

## Consequences
- Migrations are forward-only. A mistake is fixed with a new migration, never by editing history.
- The runner is tested against a real Postgres (`tests/test_migrate.py`), including the failure path. That test caught a real savepoint bug (see `docs/FINDINGS-LOG.md`).
