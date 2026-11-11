# 0006. Evals read a committed whole-table snapshot, not request cassettes

Date: 2026-11-05, revised 2026-11-06 after the Phase 4 review · Status: Accepted

## Context
Evals must give the same data on every run, or a score change could come from StatCan publishing a new month rather than from our code. vcr cassettes replay recorded *requests*, but the agent phrases its calls differently from run to run (other filters, wider date ranges), so a cassette misses on harmless differences.

## Decision
- `make snapshot` (`canada-snapshot`) writes, for each golden table:
  - `snapshots/<product_id>/metadata.json`: every member, from live WDS;
  - `series.json.gz`: **every series in the table from 2024-01 on**, from StatCan's full-table CSV download.

  That's 9 tables, 15,410 series, 1.3 MB, committed.
- `SnapshotBackend` implements the same `DataBackend` interface as `LiveBackend`, so the real `get_series` and `get_table_dimensions` code runs on top of it.
- **Errors mirror live:** an invalid coordinate gives `BAD_MEMBERS`, and an empty range gives no points.
- **The honest gaps are failures:** a table outside the snapshot, or a request starting before 2024-01, gives `SNAPSHOT_MISS`. The `harness` grader fails any run that hit one (SPEC 10.6).
- **`DATA_BACKEND=snapshot` builds no StatCan or Voyage client** (`mcp_server.components`, tested). Claude is the only outside service a recorded run reaches (PLAN 4.3). Search uses full-text plus recorded query vectors, and each search reports `degraded_retrieval`; the count is in every history line.

## The review finding this revision fixes
The first version held only the golden series. Any other real series answered "not a series", so the agent found the expected answer by elimination. That happened in 3 of 20 answerable dev runs (compare-04, lookup-07, multi-03). The original claim here, that a narrow snapshot "can only lower scores", was wrong.

## Consequences
- StatCan's quality letters (A–F, E) aren't in the CSV-built points: status codes are 0. Suppressed values (`x`, `..`) are null, as live.
- An agent that opens a non-golden table fails the case (`SNAPSHOT_MISS`). That's conservative: it may have recovered. Runs that hit it are visible in the grade output.
- Snapshot-mode search is weaker than the shipped hybrid + rerank (no live query embeddings), so in-run search recall is reported with its degraded count and never compared to the ablation rows.
- vcr cassettes stay for the HTTP-client unit tests only.

## Why not
- **Cassettes:** they miss on rephrased calls.
- **Live data in evals:** a new StatCan release would move scores with no code change.
- **Golden series only:** it leaks the answer key (above).
