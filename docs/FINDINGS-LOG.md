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

## feat/wds-client
- **Surprised:** a vcr cassette can't reproduce a connection reset faithfully, so failure paths use `httpx.MockTransport` and vcr covers the real happy path.
- **Broke:** nothing.
- **Would change:** n/a.

## feat/get-series
- **Surprised:** WDS reports problems as HTTP 200. A missing table is `status: FAILED` with a text message; an invalid coordinate is `status: SUCCESS`, `responseStatusCode: 2`, `vectorId: 0`; an empty range is `SUCCESS` with `[]`. Error handling has to read the body, not the status code.
- **Broke:** a test fixture (`161.2 + 1/10` gives `161.29999999999998`), and a live test of the table URL, which failed twice in ~28 s runs then passed in 1.6 s. The StatCan *website* stalls intermittently, so the live test now retries.
- **Would change:** build float fixtures from literal, already-rounded values, as WDS sends them.

## test/retrieval-set
- **Surprised:** two table titles were cut off in the search output; the `@live` check confirmed the completions matched StatCan exactly. That check is cheap insurance.
- **Broke:** nothing.
- **Would change:** n/a.

## feat/scope-and-cards
- **Surprised:** WDS frequency code 21 means "Occasional Daily", and the quarterly population table uses it. The scalar-factor map from step 1.2 was **missing codes 4, 5, 7 and 8** (tens of thousands … hundreds of millions); fixed from `getCodeSets`.
- **Broke:** a card test failed because the fixture's member tree was too shallow to push "Rent" off the card. Reshaping it to the real tree (19 / 10 / 27 members at depths 0 / 1 / 2) fixed it.
- **Would change:** take code tables (frequency, scalar) from `getCodeSets` from the start, not from memory. Live run: 584 tables carded in 2.5 min with 1 recovered retry; the rerun took 3.8 s, all unchanged.

## feat/retrieval-eval
- **Surprised:** keyword search scored **recall@5 0.13**: 8 of 15 questions never found their table in the top 50. My first guess (long tables) was wrong; normalisation flags didn't help. The real cause was census-tract tables repeating place names hundreds of times. Counting member words once per table (stripped positions, `ts_rank`) lifted recall to **0.33** and MRR from 0.05 to 0.22.
- **Broke:** my hypothesis, twice (normalisation, then weights alone). Measuring each variant before changing the schema kept the wrong fixes out of the code.
- **Would change:** look at failing questions' actual top hits first; the diagnosis took one query and saved two dead ends. The remaining misses are vocabulary mismatches ("jobless" vs "unemployment"), which is the case for embeddings.

## feat/ask-slice
- **Surprised:** `claude -p` hung for 180 s with no output when run from Python, because it reads stdin and the subprocess inherited an open one. `stdin=DEVNULL` fixed it. Also, the first answer said "+1.99%", which is correct but not how StatCan publishes it (+2.0%); one line in the system prompt fixed that.
- **Broke:** two MCP error tests. The SDK prefixes anticipated `ToolError`s with "Error executing tool <name>:". Our code survives inside the message, so the tests now match the code and assert the error is not an `UnexpectedToolError`.
- **Would change:** decide the billing model before the spec. ADR 0009 moved the agent from the API to the subscription, and with it the CI eval gate became a local run that CI verifies by hash.
