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
## fix/phase0-2-review
- **Surprised:** Porter stemming isn't idempotent. Stemming an already-stemmed word again changes it ("decreas" → "decrea"), so the full-text query silently missed words. The retrieval numbers didn't move, which shows how a 15-question set can hide a real bug.
- **Broke:** nothing new, but the review found 12 issues in merged code, 2 of them high. The worst pattern: WDS failures arriving as HTTP 200 were treated as successes by the cache. That was the exact lesson of feat/get-series, applied in the backend but not in the cache.
- **Would change:** review each phase before it merges (now the rule), and when a fact is learned, such as "errors come as 200", search the code for every place it applies.

## feat/embeddings-index
- **Surprised:** with no payment method, Voyage throttles to about 10K tokens a minute. Embedding 584 cards (about 180K tokens) took about 40 min instead of seconds, so the indexer had to be resumable: it embeds only `embedding IS NULL` rows and commits per batch. Vector search doubled recall@5 (0.33 → 0.67).
- **Broke:** (1) the first run died at 90/584 on "429 after 6 attempts", because exponential backoff (2–32 s) doesn't outlast a one-minute window. A 429 without `Retry-After` now waits 60 s. (2) `make dump` wrote a 13-byte file: Compose named the project after the worktree folder and found no `db`, and the pipe into zstd hid the error. Fixed with a fixed `name:` in compose and `pipefail` in the Makefile.
- **Would change:** check a provider's rate limits for *your* tier before designing a batch job. And never pipe a producer in make without pipefail.

## feat/hybrid-search
- **Surprised:** textbook RRF (k=60, equal weights) made search *worse* than vector alone (recall@5 0.40 vs 0.67). Fusion is only as good as its weakest list: full-text's long tail of noise outvoted vector's correct rank-1 hits.
- **Broke:** nothing in code; the assumption that "hybrid always wins" broke. Feeding only full-text's top 10 and weighting vector 2x reached 0.73.
- **Would change:** with 15 questions, one question is 0.07 of recall, so a 12-way sweep on the same set overfits easily. Record every cell and treat the winner as provisional until a held-out set confirms it.

## feat/rerank
- **Surprised:** the reranker's untuned default beat every tuned variant upstream: MRR 0.41 → 0.63. Reading the question and card together beats comparing two separately made vectors. Also, PLAN's `rerank-3` doesn't exist, and checking the docs caught it before any code.
- **Broke:** nothing. Keying the cache on the exact candidate list means a search change can't replay a stale order; the test proves it.
- **Would change:** n/a. Recording expensive model calls once and replaying them is now the pattern for everything slow: embeddings, reranks, and next, agent transcripts (4.3).

## Phase 2 review (fixes on feat/rerank)
- **Surprised:** every cache we added keys on *inputs we chose*, and the reviewer found the input we forgot: card text for reranks, and model for card vectors. A cache key must cover everything the cached answer depends on.
- **Broke:** nothing in production, but CI would have stayed green through a 2× drop in retrieval quality. Evals that can't fail aren't gates; score floors fix that.
- **Would change:** for every new cache, list "what does this result depend on?" and test that changing each one invalidates it.

## feat/mcp-server
- **Surprised:** an MCP schema's `additionalProperties: false` is only a promise. The SDK dropped unknown arguments and ran the tool anyway, and a test written to confirm the rule exposed it. Also, given "last year", the agent chose calendar 2025 and stated that assumption; I had assumed it would use the latest 12 months.
- **Broke:** nothing shipped. The merged idea file was a garbled chat paste at the repo root; it's now `docs/ideas/0001-uber-mcp-gateway.md`, checked against Uber's post.
- **Would change:** test what a boundary *does*, not what its schema says. Run the real question through the agent before predicting its behaviour in an interview answer.

## feat/agent
- **Surprised:** the `--trace` view showed `search_tables` taking 60.8 s against 0.05 s for the other tools. A live rerank hit Voyage's free-tier limit and waited a full minute, which suits a batch job and not a waiting agent. Interactive search now gets one attempt and degrades with a flag. Without per-tool latency we'd have blamed the model.
- **Broke:** seven of my own tests, because a fake canary of "c" matches almost any text. Also, `claude -p` had no visibility until `stream-json`: over-budget runs couldn't be stopped mid-way.
- **Would change:** retry policy belongs to the caller, not the client: batch jobs wait, interactive calls degrade.

