# Findings log

Three lines per PR: what surprised us, what broke, what we'd change. `FINDINGS.md` is curated from this at release.

## chore/skeleton
- **Surprised:** uv reports Homebrew's Python 3.14 as a broken install (`platform.mac_ver()` returned an empty value), so the project uses a uv-managed Python 3.13.
- **Broke:** the rollback test caught a real bug in the migration runner. In psycopg 3's default mode, the first `SELECT` silently opened a transaction, so each `conn.transaction()` became a *savepoint* inside it. When migration 0002 failed, the already-"applied" 0001 was rolled back too (`assert [] == [1]`). Fixed by opening the connection with `autocommit=True`, so each migration gets a real transaction of its own.
- **Would change:** write the failure-path test first for anything transactional; the happy-path tests all passed with the bug present.

## chore/core-plumbing
- **Surprised:** gitleaks didn't flag the deliberately fake `sk-ant-api03-…` test key; its Anthropic rule needs the full-length key shape.
- **Broke:** nothing; ruff's `S105` flagged the fake key, now marked intentional.
- **Would change:** n/a.

## spike/unknowns
- **Surprised:** `mcp` 2.x renamed `FastMCP` to `MCPServer`; v1 imports fail outright. The SDK's `async_mcp_tool` drops `additionalProperties: false` even with `strict=True`.
- **Broke:** nothing; WDS was 40/40 on the first try today (a different endpoint was 0/4 yesterday).
- **Would change:** check installed package source before writing code against an API from memory; it caught the rename in one command.
