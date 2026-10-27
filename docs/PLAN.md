# Build plan: Canada Data Agent & Eval Lab v1.0

Implements `SPEC.md` v1.0. Status: **draft v0.2, 2026-10-27, for adversarial review.**

Each step is **one branch and one PR** off `main`, built test-first, with a Conventional Commit title and a squash merge. Each phase ends with a tag and a short release note. **We stop for George's go-ahead before each new phase.** Claude commits, pushes, opens and reviews PRs. Background sessions can't merge, so in those cases George gets a one-line merge command.

The order **kills the biggest unknowns first** (Phase 0 spikes), then builds data → search → tools → agent → evals. Every later layer then sits on something already tested and measured.

## How each step runs
1. **Learn:** a plain-words explanation, with a vault lesson linked or written, before any code.
2. **Tests first:** write the failing tests from "Done when".
3. **Build:** make them pass. "Who writes it" says whether George writes the code (Claude reviews and explains) or Claude writes it (George reviews and must be able to explain every line).
4. **Verify:** CI is green, plus the step's manual check.
5. **PR:** what changed, how it was verified, what it proves. From Phase 4 on, the eval delta too.
6. **Lesson:** update the vault with the real commands and output.

**Time budget:** about 10 h a week (two weekend half-days plus two evenings) alongside the Lynked job, so about 6 weeks. Estimates are per step; if a phase runs over its budget by 50%, we stop and cut (see "Cut lines").

## Open decision for George: who writes the core?
SPEC §2's ownership rule says George hand-writes **RRF, the rate limiter, the coordinate builder and the graders**. On the payments project, George later handed all implementation to Claude. **Default in this plan: the spec rule** (four small, high-signal pieces, about 6 h in total). George can switch any step to "Claude writes" on request.

## Before we start (George)
| When | What | Why |
|---|---|---|
| Now | Create the GitHub repo (`gh repo create`), blocked earlier pending permission | PRs need a remote |
| Phase 0 | Anthropic Console: an API key for local dev with a **$20/month org spend limit**, and a second **workspace key capped at $10** for CI | SPEC §4 |
| Phase 1 | MongoDB Atlas account → AI Model APIs → a Voyage model API key (free 200M tokens, no card) | Embeddings |
| Phase 0 | `uv python install 3.13` (Homebrew's Python 3.14 reports as broken to uv) | Toolchain |
| Ready | uv 0.12.23 and Docker 29.8 are installed and running | Checked 2026-10-27 |

---

## Phase 0 · Spikes and skeleton (W1, first half; about 5 h) → no tag
Spikes are **throwaway code in `spikes/`** that answers one question each. The findings go in an ADR, and the code is deleted at the end of the phase.

### 0.1 `chore/skeleton`
**Who writes it:** Claude. George reviews.
- `uv` project (Python 3.13, `uv.lock`), ruff, pytest, `Makefile`, `docker-compose.yml` (Postgres 17 + pgvector), `.env.example`.
- CI: `on: pull_request`, `contents: read`, actions pinned by SHA, `uv sync --locked`, ruff, pytest, gitleaks.
- Make CI a required check on `main`.
- **Done when:** a PR with a lint error fails CI; a clean PR passes.
- **Lessons:** update [[uv and Virtual Environments]]; new [[Pinning GitHub Actions]].

### 0.2 `spike/three-unknowns` (findings → ADR 0001)
**Who writes it:** Claude, pairing with George.
1. **WDS:** call `getDataFromCubePidCoordAndLatestNPeriods` and `getDataFromVectorByReferencePeriodRange` 20 times each, with retries. Record the reset rate.
2. **MCP 2.x:** a hello-world stdio server with one tool, registered with `claude mcp add` and called from Claude Code.
3. **Tool runner + MCP:** can the Anthropic SDK tool runner use MCP tools directly, or does it need a thin adapter? Measure tokens for one 3-tool round trip on Haiku 5.5.
- **Done when:** ADR 0001 records versions, the reset rate, the adapter decision and cost per round trip. **If any spike fails, we revisit the spec before Phase 1.**
- **Lessons:** [[MCP Servers]] (Build section filled in).

---

## Phase 1 · Data and vector retrieval (W1–W2; about 10 h) → `w1`

### 1.1 `feat/wds-client`
**Who writes it:** Claude writes the client; **George writes the token-bucket limiter**.
- httpx client with a host-allowlist event hook (rejects anything but `www150.statcan.gc.ca`, including redirects).
- 3 retries with jitter on resets, empty bodies and 5xx.
- 409 → `UPSTREAM_LOCKED_409`.
- An `http_cache` table that never caches errors.
- **Done when:** unit tests with vcr cassettes (`filter_headers`) cover each failure path; a property test shows the limiter never exceeds 10 requests per second.
- **Lessons:** [[Rate Limiting with Token Buckets]], [[Retries, Backoff and Jitter]].

### 1.2 `feat/scope-and-cards`
**Who writes it:** Claude. George reviews.
- `config/scope.toml` with subject prefixes confirmed live, plus a script that prints counts.
- `table_card` and `member` schema with migrations.
- A card builder (≤600 tokens, top-level members first) and full-text built from **all** member names.
- **Done when:**
  - The in-scope table count is logged, and the 525 null-subject tables are logged.
  - A test confirms CPI 18-10-0004 has "Rent" (81) in `member` and in the full-text vector but not in the card text.
- **Lessons:** [[Chunking for Retrieval]].

### 1.3 `feat/embeddings-index`
**Who writes it:** Claude. George reviews.
- Voyage `voyage-4` batch embedding with 429 backoff.
- Idempotent re-index keyed on hash(card text + model).
- `make index`, plus `make seed` (restores a committed `index.sql.zst`).
- **Done when:** a second `make index` embeds 0 cards; `make seed` on a fresh database works with no Voyage key; Voyage token use is logged.
- **Lessons:** [[Embeddings]].

### 1.4 `feat/retrieval-eval`
**Who writes it:** **George writes the 15 retrieval questions** (before seeing results); Claude writes the harness.
- An offline retrieval eval that reports recall@5 (strict and lenient) and MRR.
- **Done when:** ablation row 1 (vector only) is committed in `evals/ablation.md`; CI runs it on every push using `make seed` and the cached query embeddings.
- **Lessons:** [[Retrieval Metrics]].

---

## Phase 2 · Hybrid search and MCP tools (W2–W3; about 10 h) → `w2`

### 2.1 `feat/hybrid-search`
**Who writes it:** **George writes RRF.** Claude writes the ORed full-text query.
- **Done when:** ablation rows 2 (full-text only) and 3 (RRF) are committed; RRF unit tests use hand-computed ranks.
- **Lessons:** [[Hybrid Search and RRF]].

### 2.2 `feat/rerank`
**Who writes it:** Claude.
- `rerank-3` behind a flag.
- **Done when:** ablation row 4 is committed; ADR 0002 records whether it's enabled, decided by the measured recall@5.

### 2.3 `feat/get-series`
**Who writes it:** **George writes the coordinate builder.** Claude writes the rest.
- `get_series` and `get_table_dimensions` over a `DataBackend` interface (live implementation now, snapshot implementation in Phase 4).
- **Done when:** tests cover:
  - Ontario + Rent → `14.81.0.0.0.0.0.0.0.0`
  - `responseStatusCode 2` / `vectorId 0` → `BAD_MEMBERS`
  - null → suppressed
  - ≤120 points
  - Live smoke test: Ontario rent 2025-09 → 2026-09 is 161.2 → 164.4.
- **Lessons:** [[Coordinates and Vectors in StatCan WDS]].

### 2.4 `feat/mcp-server`
**Who writes it:** Claude. George reviews.
- A `canada-data` stdio server with 3 strict tools.
- `untrusted_text` escaping, server-built URLs, a 4k result cap, and a tool-description snapshot test.
- **Done when:** `claude mcp add` works and Claude Code answers the Rent question using the three tools (screenshot in the PR).
- **Lessons:** [[MCP Servers]] (Verify), [[Prompt Injection]].

---

## Phase 3 · The agent (W3–W4; about 8 h) → `w3`

### 3.1 `feat/agent-cli`
**Who writes it:** Claude. George reviews.
- `canada-ask` on the tool runner (or the ADR 0001 adapter).
- System prompt v1 in `prompts/` with a canary token.
- Budgets: ≤8 tool calls, 60 s, capped `max_tokens`.
- Sonnet 5.5 with `fallbacks: "default"`.
- **Done when:** it answers "+2.0%" with a StatCan link; `BUDGET_EXCEEDED` is tested with a stub model.

### 3.2 `feat/structured-answers`
**Who writes it:** Claude.
- `answer_values` (`label`, `value`, `vector_id`, `ref_period(s)`) and `refused` via structured output.
- `--trace` and JSON logs with tokens and USD.
- **Done when:** 5 demo questions are answered and the README GIF is recorded from `--trace`; cost per question is logged.
- **Lessons:** [[Structured Outputs]].

---

## Phase 4 · Golden set, graders, snapshot (W4–W5; about 12 h) → `w4`

### 4.1 `test/golden-set` (**must merge before any prompt or tool-description tuning**)
**Who writes it:** **George writes all 40 cases** and checks each value on the StatCan website. Claude writes the schema linter.
- **Done when:** the linter passes (40 cases, 24 dev / 16 test, the category mix, every case `checked_on_statcan_site: true`, ≥⅓ paraphrased).
- **Lessons:** [[Golden Sets]] (builds on [[Scoring Jobs for Fit]]).

### 4.2 `feat/graders`
**Who writes it:** **George writes the graders.** Claude writes the fixtures.
- Values-in-prose, grounding recompute, citation host, refusal and trajectory graders.
- **Done when:** graders pass on 10 hand-made good transcripts and fail each of 10 hand-made bad ones for the right reason.
- **Lessons:** [[LLM Evals]].

### 4.3 `feat/snapshot-backend`
**Who writes it:** Claude. George reviews.
- `make snapshot`, a `SnapshotBackend` returning live-shaped errors, `SNAPSHOT_MISS` counted as a failure, and the query-embedding cache with `degraded_retrieval`.
- **Done when:** a full dev run (k=1) works with network access only to the Anthropic API (checked with the host hook in strict mode).
- **Lessons:** [[Test Doubles: Snapshots vs Cassettes]].

---

## Phase 5 · Gate and security (W5–W6; about 10 h) → `w5`

### 5.1 `ci/eval-gate`
**Who writes it:** Claude. George reviews.
- Flakiness study (dev × 5 on `main`) → quarantine list.
- `baseline.json`, the k=3 dev gate on ready-for-review PRs, the flip rule, the 10-point mean drop, the $2 actual-cost cap.
- A CI diff flag on `evals/`, `snapshots/` and the baseline; the CI key as a repo secret, never available to forks.
- **Done when:** the gate passes on `main`; the first real gate cost is recorded and compared with the $1–2 estimate.

### 5.2 `test/injection-suite`
**Who writes it:** Claude writes the fixtures; George writes the pass criteria per case.
- 6 cases (3 vectors × 2 goals), with `allowed_tools`, `max_tool_calls` and canary checks.
- **Done when:** all 6 pass at k=3; the README has a "limits of this suite" section.

### 5.3 `demo/gate-catches-regression` (**never merged**)
- Deliberately degrade the `get_series` tool description.
- **Done when:** the gate fails it in CI. The PR stays closed and unmerged and is linked from the README.

---

## Phase 6 · Release (W6; about 6 h) → `v1.0.0`

### 6.1 `docs/v1-release`
**Who writes it:** George writes `FINDINGS.md` and the claims table. Claude writes the chart script.
- The `v1.0.0` tag triggers the one test-split run → the headline with its Wilson interval.
- `history.jsonl` chart, `FINDINGS.md` (3 real catches with before/after), claims-to-evidence table, ADR index, `claude mcp add` quickstart.
- **Done when:** a stranger can clone, `make seed`, set `ANTHROPIC_API_KEY`, and run `canada-ask` in under 10 minutes (tested from a fresh clone).

---

## Cut lines (in order, if behind)
1. Drop 2.2 (rerank); keep the ablation row saying "not tried".
2. Ship **v0.9 at the end of Phase 4**: retrieval, agent and offline graders with no LLM gate. Gate and injection follow in v1.0.
3. Shrink the golden set to 30 cases (18/12), and state the smaller n next to the Wilson interval.

## Out of scope
SPEC §5 v1.1: the Open Canada and FX tools, the LLM judge, the weekly drift job, the month-to-date guard, the `compute` tool, more cases.

## Total
**17 PRs + 1 never-merged demo PR. About 61 h**, roughly 6 weeks at 10 h a week.
