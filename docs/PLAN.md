# Build plan: Canada Data Agent & Eval Lab v1.0

Implements `SPEC.md` v1.0. Status: **draft v0.3, 2026-10-27**, revised after round-1 adversarial review (tech lead, spec auditor, schedule sceptic, learning coach). The response to every point is in §R at the end.

## Ground rules
- **One step = one branch = one PR** off `main`: test-first, Conventional Commit title, squash merge. Each phase ends with a tag and a release note.
- **Phase gates.** We stop for George's go-ahead before each phase. **A phase can't be tagged until George passes its explain-back and its mock interview** (below). These are comprehension gates, not permission checkpoints.
- **The golden-set rule** (SPEC §10.2): no prompt, tool-description or retrieval change may be *justified by eval results* until all 40 golden cases are committed. First drafts written before any results are fine; iterating on results is not. The golden set is written in weekly batches from W1 and completed at tag `w4`. Phase 4 is where iteration starts.
- **Cuts that change the approved spec** (case counts, injection count) need a spec amendment PR that George approves first.

## Who writes what (default; George can change any row)
| George writes (judgment work an interviewer probes) | Claude writes (plumbing; George must pass the explain-back) |
|---|---|
| Limiter, RRF, coordinate builder, graders (SPEC §2) | Project skeleton, CI, migrations, config, logging |
| System prompt and canary; the 3 tool descriptions | WDS client body, retries, cache |
| Gate rules (`gate_rules.py`: flip rule, mean drop, Wilson) + written justification | Indexer, Voyage batching, snapshot backend |
| Agent budget/stop logic and refusal path | MCP server wiring, agent loop wiring |
| All 15 retrieval questions + 40 golden cases, each checked on the StatCan site | Linters, fixtures, chart script, README scaffolding |
| Pass criteria for each injection case | Injection fixtures |
| The "why" section of every PR description; the Decision + "Why not X" of every ADR | The "what changed" section of PR descriptions; ADR context |

> **Open decision for George:** on the payments project you handed all code to Claude. This plan defaults to the split above because the left column is what interviews probe. It costs about **20 h** of George-written work out of about 100 h. Say "Claude writes everything" and the left column becomes explain-back only.

## How each step runs
1. **Learn:** a plain-words explanation, with a vault lesson linked or written.
2. **Tests first:** write the failing tests from "Done when". These are automated assertions; screenshots are only supplementary.
3. **Build.**
4. **Verify:** CI is green. Live-network tests are `@pytest.mark.live`, run only with `make live`, never in CI.
5. **PR:** George writes the "why" and the **explain-back**. For every Claude-written PR he answers three questions in his own words: *what breaks if X is deleted, why this over the alternative, how a test of it would fail*. Claude marks each one; nothing merges until all three are right.
6. **Log:** George adds a 3-line entry to `docs/FINDINGS-LOG.md` (what surprised me, what broke, what I'd change). `FINDINGS.md` is curated from it at release.
7. **Lesson:** update the vault, and answer one Check-yourself question unprompted before the phase moves on.

**Mock interview per phase (20 min):** Claude plays a sceptical interviewer built from the target postings and asks 5 questions, 2 of them with the repo closed. Any miss → George rewrites that lesson in his own words before the tag.

## Calendar (10 h/week; this project first, payments at 2 h/week or less until v0.9; see decision D2)
| Week (Mon) | Phase | Tag | Gate |
|---|---|---|---|
| W1 Oct 27 | 0 Spikes + plumbing | none | Spikes done or defaults taken by **Sun Nov 2** |
| W2 Nov 3 | 1 Thin vertical slice | `w1` | **Demo: one real answer end to end by Sun Nov 9** |
| W3–W4 Nov 10 | 2 Index + hybrid search | `w2` | Tagged by **Sun Nov 23**, or take cut 1 |
| W5 Nov 24 | 3 MCP tools + agent | `w3` | |
| W6–W7 Dec 1 | 4 Graders, snapshot, history | `w4` = **v0.9** | Tagged by **Sun Dec 14**, or take the next cut |
| W8–W9 Dec 15 | 5 Gate + security | `w5` | Holiday week counted at 5 h |
| W10 Jan 5 | 6 Release | `v1.0.0` | |
| W11 | Buffer (≈15% contingency) | | |

**Rolling rule:** at each phase end, if cumulative hours are over 125% of the cumulative budget, take the next cut automatically.

---

## Before we start (George)
| When | What |
|---|---|
| Now | Create the GitHub repo (the `gh repo create` command already given); then make CI a **required check** on `main` (admin-only) |
| W1 | Anthropic Console: a dev key with an org spend limit of **$20/month**, plus a **CI workspace key capped at $10** |
| W1 | MongoDB Atlas → AI Model APIs → a Voyage key (free 200M tokens, no card) |
| W1 | `uv python install 3.13` (uv reports Homebrew's 3.14 as broken). uv 0.12.23 and Docker 29.8 are already installed |

---

## Phase 0 · Spikes and plumbing (W1; 10 h) → no tag

### 0.1 `chore/skeleton` (Claude)
- uv project (Python 3.13, `uv.lock`), ruff, pytest + `hypothesis`, `Makefile` (`make up` = compose + migrate + seed, `make test`, `make live`), `.env.example`.
- **Migrations:** numbered SQL files plus a 30-line runner (`make migrate`); no ORM.
- **CI:**
  - `on: pull_request`, `permissions: contents: read, pull-requests: write`, SHA-pinned actions, `uv sync --locked`.
  - ruff, pytest, gitleaks.
  - A **Postgres + pgvector service container**.
- **Done when:** a PR with a lint error fails CI; a migration test passes against the service container.

### 0.2 `chore/core-plumbing` (Claude)
- pydantic-settings config.
- A JSON logger with trace ID that **redacts headers and keys**.
- An `ErrorCode` enum with every SPEC §8 code.
- `config/prices.toml`, dated, with its source URL.
- **Done when:** a test proves an `Authorization`/`x-api-key` value never reaches log output; a cost test computes USD from a fixed usage object.

### 0.3 `spike/unknowns` (George runs it; Claude scaffolds; **5 h timebox**) → ADR 0001
1. **WDS:** 20 calls each to `getDataFromCubePidCoordAndLatestNPeriods` and `getDataFromVectorByReferencePeriodRange`; record the reset rate.
2. **MCP:** a hello-world stdio server on `mcp` 2.x, registered with `claude mcp add`.
3. **Agent ↔ MCP:** the SDK has a beta helper `anthropic.lib.tools.mcp.async_mcp_tool` that turns tools from a **local stdio** MCP client session into tool-runner tools (checked in the SDK docs 2026-10-27). Confirm it works with `mcp` 2.x.
   - **Default if it fails (no spec revisit):** one tool core with two front doors. The agent calls the same Python tool functions in-process; MCP serves Claude Code.
4. **Docs check (SPEC §13.1):** confirm the model IDs, `fallbacks: "default"` and structured-output syntax against current docs. Measure one 3-tool round trip on **Sonnet 5.5 and Haiku 5.5**.
- **Done when:** ADR 0001 records versions, the reset rate, the adapter decision and cost per round trip; `spikes/` is deleted.

---

## Phase 1 · Thin vertical slice (W2; 10 h) → `w1`
The goal is one real question answered end to end, ugly but true, so there's something to demo in week 2.

### 1.1 `feat/wds-client`: **George: limiter**; Claude: client
- httpx host-allowlist hook (re-checked on redirects).
- 3 retries with jitter on resets, empty bodies and 5xx; 409 → `UPSTREAM_LOCKED_409`.
- `http_cache` migration with TTLs (metadata 24 h, data 6 h); **errors and 409s are never cached**.
- Upstream error bodies are returned only as escaped `untrusted_text`.
- **Done when:**
  - vcr tests (`filter_headers`) cover every failure path.
  - A `hypothesis` property test on a **fake clock** shows the limiter never exceeds 10 requests per second.
  - TTL and never-cache tests pass.

### 1.2 `feat/get-series`: **George: coordinate builder**; Claude: rest
- `DataBackend` interface + `LiveBackend`: `get_series` and `get_table_dimensions`.
- Validates `members` against metadata, ≤50 members per dimension (filtered), ≤120 points.
- The primary call is LatestNPeriods; `responseStatusCode != 0` or `vectorId == 0` → `BAD_MEMBERS`.
- The range call is `getDataFromVectorByReferencePeriodRange`; null values are suppressed.
- Codes: `NOT_FOUND`, `RATE_LIMITED`.
- **Done when:** unit tests cover each rule and code (Ontario + Rent = `14.81.0.0.0.0.0.0.0.0`), plus a `@live` test of 161.2 → 164.4.

### 1.3 `feat/slice-cli` (Claude, George reviews)
- A throwaway `canada-ask --table 18100004` that calls `get_series` through the tool runner, with a hardcoded table and no search.
- **Done when:** `make live` answers the Rent question with +2.0% and a StatCan link. A **demo recording** is saved.

### 1.4 `test/golden-linter` (Claude writes the linter; **George: golden batch 1**)
- The YAML schema linter checks: split and category mix, `checked_on_statcan_site`, ≥⅓ paraphrased, the **low word-overlap warning**, and the 15 retrieval questions marked dev-only.
- **Done when:** the linter runs in CI; batch 1 = **15 retrieval questions + 10 golden cases**, committed before any search exists.
- **Lessons:** [[Golden Sets]] (written now; it recaps [[Scoring Jobs for Fit]]), [[Rate Limiting with Token Buckets]], [[Retries, Backoff and Jitter]], [[Coordinates and Vectors in StatCan WDS]].

---

## Phase 2 · Index and hybrid search (W3–W4; 16 h) → `w2`

### 2.1 `feat/scope-and-cards` (Claude)
- `config/scope.toml` with prefixes confirmed live; archived tables (`"1"`) and the 525 null-subject tables excluded and logged.
- `table_card` + `member` migrations; cards ≤600 tokens with escaped footnotes; full-text over **all** member names.
- **Done when:** a test confirms Rent (81) is in `member` and in the full-text vector but not in the card text.

### 2.2 `feat/embeddings-index` (Claude)
- Voyage batching with 429 backoff; idempotent re-index on hash(card + model).
- `make index`, `make seed` (`index.sql.zst`; its size is measured and recorded, with Git LFS if it's over 50 MB).
- **Query-embedding cache** + `make record`; on a miss, CI falls back to full-text-only search flagged `degraded_retrieval`.
- **Done when:** a second index run embeds 0 cards; `make seed` works with no Voyage key.

### 2.3 `feat/retrieval-eval` (Claude harness; George already wrote the questions)
- recall@5 (strict and lenient) and MRR; ablation row 1 (vector).
- **Done when:** CI runs it on every PR from `make seed` + the query cache.

### 2.4 `feat/hybrid-search`: **George: RRF**; Claude: ORed full-text
- **Done when:** ablation rows 2–3 are committed; RRF tests use hand-computed ranks; the README notes `ts_rank_cd` ≠ BM25.

### 2.5 `feat/rerank` (Claude) *(cut 1)*
- **Done when:** ablation row 4 is committed; ADR 0002 records whether rerank is enabled. **George: golden batch 2 (10 cases).**
- **Lessons:** [[Chunking for Retrieval]], [[Embeddings]], [[Retrieval Metrics]], [[Hybrid Search and RRF]].

---

## Phase 3 · MCP tools and agent (W5; 12 h) → `w3`

### 3.1 `feat/mcp-server`: **George: the 3 tool descriptions**; Claude: wiring
- Strict schemas, `untrusted_text` with marker-like tags stripped, server-built URLs, 4k result cap, a tool-description snapshot test.
- **Done when:** an **in-process MCP client test** lists the 3 tools and calls each against a fake backend. `claude mcp add` works (screenshot is supplementary).

### 3.2 `feat/agent`: **George: system prompt v1 + canary, budget/stop logic, refusal path**; Claude: loop wiring
- Uses the tool runner (or the ADR 0001 default). Model from config: Sonnet 5.5 (`fallbacks: "default"`) locally, **Haiku 5.5 in CI**.
- `prompts/` versioned, with the **prompt version recorded per run**.
- Structured `answer_values` + `refused`.
- Logs carry trace ID, per-tool latency, cache hit, tokens and USD.
- **Done when:** a stub-model test covers `BUDGET_EXCEEDED`; `make live` answers 5 demo questions; a GIF is recorded from `--trace`.
- **George: golden batch 3 (10 cases).**
- **Lessons:** [[MCP Servers]] (Build/Verify), [[Tool Description Design]], [[System Prompts and Canaries]], [[Structured Outputs]], [[Prompt Injection]].

---

## Phase 4 · Graders, snapshot, history (W6–W7; 18 h) → `w4` = **v0.9**

### 4.1 `test/golden-final` (**George: batch 4, 10 cases → 40 total**)
- **Done when:** the linter passes on all 40 (24 dev / 16 test). **Eval-driven iteration is allowed from this merge onward.**

### 4.2 `feat/graders`: **George** writes the graders; Claude writes the fixtures
- Retrieval inside the run (recall@5/MRR), values-in-prose, grounding recompute, citation host, refusal, trajectory.
- **Done when:**
  - Graders pass on 10 hand-made good transcripts and fail each of 10 bad ones for the stated reason.
  - Graders on recorded transcripts run in the **every-PR** CI job.

### 4.3a `feat/snapshot` (Claude)
- `make snapshot`; `SnapshotBackend` with live-shaped errors; `SNAPSHOT_MISS` counted as a failure.

### 4.3b `feat/offline-mode` (Claude)
- Strict host hook: Anthropic only.
- **Done when:** a dev run (k=1) completes offline except for Claude.

### 4.4 `feat/history` (Claude)
- A `history.jsonl` writer with every SPEC §10.7 field (model, prompt version, cache tokens, actual USD, p50/p95, per-category scores) and a schema test.
- **Lessons:** [[LLM Evals]], [[Test Doubles: Snapshots vs Cassettes]].

**v0.9 release note:** retrieval ablation, agent, offline graders, history. This is a demo-able portfolio state even if the plan stops here.

---

## Phase 5 · Gate and security (W8–W9; 14 h) → `w5`

### 5.1 `spike/flakiness-study` (Claude runs it; **4 h, about $5 budget**)
- The dev set ×5 on `main` → the quarantine list in the README.
- **Pre-agreed rule:** if the measured cost is over $4 per gate run, drop to k=2 and record why in an ADR.

### 5.2 `ci/eval-gate`: **George: `gate_rules.py` + justification ADR**; Claude: CI wiring
- k=3 on ready-for-review PRs; the flip rule; a mean drop over 10 points; the $2 actual-cost cap; a CI diff flag on `evals/`, `snapshots/` and the baseline; forks never get the key.
- **Done when:**
  - `gate_rules` unit tests pass.
  - George's ADR explains **why k=3, and why a Wilson interval on n=16 is wide (about ±20 points)**.

### 5.3 `test/injection-suite`: **George: pass criteria**; Claude: fixtures
- 6 cases (card/footnote, member name, error body × 2 goals).
- **Done when:** all pass at k=3; the README has a "limits of this suite" section.

**The gate's evidence:** the README links **the first PR the gate fails naturally** (recorded in the FINDINGS-LOG). Only if none has happened by `w5` does a clearly labelled demo PR (a degraded tool description, failure predicted in writing beforehand) stand in, and the README says it was staged.
- **Lessons:** [[Eval Gate Statistics]].

---

## Phase 6 · Release (W10; 9 h) → `v1.0.0`

### 6.1 `docs/v1-release`: **George: `FINDINGS.md` (curated from the log), claims table, ADR decision sections**; Claude: chart script
- The `v1.0.0` tag triggers the one test-split run → the headline with its Wilson interval.
- Chart, ADR index, README quarantine list, a `claude mcp add` quickstart.
- **Done when:** a **CI fresh-clone job** (`make seed` + `canada-ask --offline`) passes in under 10 minutes.

---

## Cut lines (in order; dated gates above, or the 125% rolling rule)
1. Drop rerank (2.5); the ablation row says "not tried".
2. Injection 6 → 3 cases, one per vector (**needs a spec amendment**).
3. Golden 40 → 30 (**needs a spec amendment**); the smaller n is shown with the Wilson interval.
4. Flakiness study ×5 → ×3.
5. Stop at v0.9; ship the gate and injection later.

## Out of scope
SPEC §5 v1.1: the Open Canada/FX tools, LLM judge, weekly drift job, month-to-date guard, `compute` tool, more cases, Dependabot, image digests.

## Totals
**19 PRs (+ 2 spikes). About 89 h of build + about 6 h of explain-backs and mock interviews + about 15% contingency ≈ 108 h over 10 weeks + 1 buffer week.**

---

## Decisions for George
- **D1 Ownership:** the split above (default), or "Claude writes everything" with explain-backs only.
- **D2 Sequencing:** this project first, with payments at 2 h/week or less until v0.9 (default, since this maps to the AI/LLM postings). Flip it if most of your live applications in the next month are fintech/.NET.
- **D3 Pre-approval:** approve Phases 0–1 now so W1–W2 run without a stop between them.

## §R Response to round-1 review
| # | Point (critic) | Response |
|---|---|---|
| 1 | Estimates were Claude's typing speed; ~95 h is honest (schedule) | **Accepted.** 61 → about 108 h with contingency, 10 weeks plus a buffer |
| 2 | Undated cut lines never fire (schedule) | **Accepted.** Dated gates plus the 125% rolling rule |
| 3 | Nothing demo-able until week 6 (schedule) | **Accepted.** Phase 1 is now a thin vertical slice with a demo by Nov 9 |
| 4 | Cut order damaged the headline claim (schedule) | **Accepted.** Reordered; v0.9 is last |
| 5 | The spikes' "revisit the spec" was unbounded (schedule) | **Accepted.** 5 h timebox plus a pre-agreed default |
| 6 | The tool runner can't use stdio MCP (tech lead) | **Rejected after checking:** the SDK's beta `async_mcp_tool` helper wraps a local stdio session (SDK docs, 2026-10-27). The spike confirms it with `mcp` 2.x, and the two-front-door design is the default if it fails |
| 7 | 1.4 CI used the cache from 4.3; no Postgres in CI (tech lead, auditor) | **Accepted.** The cache moves to 2.2; the pgvector service container moves to 0.1; the "every push" wording is fixed |
| 8 | No migration tool; missing config, logging, error enum, prices, history writer (tech lead, auditor) | **Accepted.** 0.1, 0.2 and 4.4 |
| 9 | 4.3 too big; demo-style "Done when" criteria; live tests in CI (tech lead) | **Accepted.** Split into 4.3a/b; MCP test in-process; `@live` + `make live` |
| 10 | Golden set written after tuning breaks SPEC §10.2 (auditor) | **Accepted.** Weekly batches from W2, complete at `w4`, plus the golden-set ground rule |
| 11 | Missing MUST rules from §7–§12 (archived, marker stripping, error bodies, header-logging test, BM25 note, quarantine list, overlap warning, TTLs, codes, member validation, range call, log fields, Haiku in CI, prompt version) (auditor) | **Accepted.** Each is now an explicit "Done when" item in 0.2, 1.1, 1.2, 1.4, 2.1, 2.4, 3.1, 3.2, 5.1 |
| 12 | The staged 5.3 PR contradicts "a PR the gate really failed" (auditor) | **Accepted.** The real first failure is preferred; a staged demo only as a labelled fallback |
| 13 | Cut 3 edits the approved spec silently (auditor) | **Accepted.** Spec amendment required |
| 14 | Claude writes PR descriptions, contrary to SPEC §2 (auditor) | **Partly accepted.** George writes the "why" plus the explain-back; Claude drafts the mechanical "what changed" list |
| 15 | Ownership inverted: George got the easy pieces (coach) | **Accepted** as the default (D1). George now owns the prompt, tool descriptions, gate rules, budget logic, golden set and ADR decisions |
| 16 | "George reviews" has no pass condition (coach) | **Accepted.** An explain-back gates every merge; mock interviews gate every tag |
| 17 | Lessons in the wrong order; missing gate statistics, tool descriptions, prompts (coach) | **Accepted.** Golden Sets moves to Phase 1; 3 lessons added |
| 18 | FINDINGS reconstructed from memory (coach) | **Accepted.** A per-PR FINDINGS-LOG |
| 19 | Capacity double-booked with payments (schedule) | **Accepted** as decision D2, with a default |
| 20 | Required check needs admin rights; fresh-clone check needs CI (tech lead) | **Accepted.** Moved to "Before we start"; a CI fresh-clone job |
