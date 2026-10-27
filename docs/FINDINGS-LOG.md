# Findings log

Three lines per PR: what surprised us, what broke, what we'd change. `FINDINGS.md` is curated from this at release.

## chore/skeleton
- **Surprised:** uv reports Homebrew's Python 3.14 as a broken install (`platform.mac_ver()` returned an empty value), so the project uses a uv-managed Python 3.13.
- **Broke:** the rollback test caught a real bug in the migration runner. In psycopg 3's default mode, the first `SELECT` silently opened a transaction, so each `conn.transaction()` became a *savepoint* inside it. When migration 0002 failed, the already-"applied" 0001 was rolled back too (`assert [] == [1]`). Fixed by opening the connection with `autocommit=True`, so each migration gets a real transaction of its own.
- **Would change:** write the failure-path test first for anything transactional; the happy-path tests all passed with the bug present.
