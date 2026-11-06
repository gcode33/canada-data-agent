# 0006. Evals read a committed snapshot of the golden tables, not request cassettes

Date: 2026-11-05 · Status: Accepted

## Context
Evals must give the same data on every run, or a score change could come from StatCan publishing a new month rather than from our code. vcr cassettes replay recorded *requests*, but the agent phrases its calls differently from run to run (other filters, wider date ranges), so a cassette misses on harmless differences.

## Decision
- `make snapshot` (`canada-snapshot`) writes `snapshots/<product_id>/metadata.json` (every member) and `series.json` (each golden case's series over 2024-01 to 2026-09) from live StatCan: 9 tables, 284 KB, committed.
- `SnapshotBackend` implements the same `DataBackend` interface as `LiveBackend`, so `get_series` and `get_table_dimensions` run the real service code on top of it.
- **Errors mirror live:** an uncovered coordinate gives `BAD_MEMBERS`; an empty range gives no points; an uncovered table gives `SNAPSHOT_MISS`, which a run counts as a failure, not a crash.
- `DATA_BACKEND=snapshot` makes the MCP server build no WDS client at all, so a run cannot reach StatCan.
- A test proves every golden value can be answered from the snapshot through the real service.

## Consequences
- An agent that picks a valid but different series (say, unadjusted instead of seasonally adjusted) gets `BAD_MEMBERS` here when live would have answered. That can only lower scores, never inflate them. If it shows up in transcripts, widen the snapshot.
- Search is not part of the snapshot: the index dump already covers it. Voyage is still called when a key is set (the agent rewrites queries, so they aren't pre-recorded), and each run reports whether retrieval was degraded.
- vcr cassettes stay for the HTTP-client unit tests only.

## Why not
- **Cassettes:** they miss on rephrased calls (above).
- **Live data in evals:** a new StatCan release would move scores with no code change.
