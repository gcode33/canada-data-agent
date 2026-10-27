# Build plan: Canada Data Agent & Eval Lab v1.0

Implements `SPEC.md` v1.0 + amendment A1 (below). Status: **final draft v1.0, 2026-10-27, awaiting George's approval.** It went through two adversarial rounds (tech lead, spec auditor, schedule sceptic, learning coach); all four round-2 verdicts were "ready with changes", and those changes are applied here. The transcripts are in `docs/reviews/2026-10-27-plan-review.md`, and the response log is in §R.

## 1. Ground rules
- **One step = one branch = one PR** off `main`: test-first, Conventional Commit title, squash merge.
- **Each phase ends with a tag.** We stop for George's go-ahead before each phase.
- **Golden-set rule (SPEC §10.2 + A1):**
  - **No change to the system prompt or tool descriptions may be made in response to eval results until all 40 golden cases are committed** (tag `w4`). First drafts written before any results are fine.
  - Retrieval choices (full-text, RRF, rerank) are decided on the **15 retrieval questions**. Those are committed before any search code exists.
- **Spec-changing cuts** (case counts, k, flakiness repeats) only through the pre-written amendment drafts in `docs/amendments/`, which George approves.
- **Hours log:** George records his hours per session in `docs/HOURS.md`; it feeds the 125% rule in §4.

## 2. Who writes what (default; George can change any row)
| George writes: judgment work interviewers probe, **including its tests** | Claude writes: plumbing (George passes the explain-back) |
|---|---|
| Limiter, RRF, coordinate builder, graders, and **the failing tests for each** | Skeleton, CI, migrations, config, logging |
| System prompt and canary; the 3 tool descriptions | WDS client body, retries, cache |
| `gate_rules.py` + the statistics ADR (why k=3; the Wilson interval at n=16 is about ±20 points) | Indexer, Voyage batching, snapshot backend |
| Agent budget/stop logic and refusal path | MCP server and agent-loop wiring |
| 15 retrieval questions and 40 golden cases, each checked on the StatCan site | Linters, fixtures, transcript recorder, chart script |
| Injection pass criteria | Injection fixtures |
| **Every PR description** (SPEC §2); the Decision + "Why not X" of every ADR | A list of changed files for George to draw on; ADR context sections |

> **Decision D1:** on payments you handed all code to Claude. This plan defaults to the split above, about **22 h of George-written work**. Say "Claude writes everything" and the left column becomes explain-back only (saves about 12 h).

## 3. How each step runs
1. **Learn:** a plain-words explanation plus a vault lesson.
2. **Tests first.**
3. **Build.**
4. **Verify:** CI green. Network tests are `@pytest.mark.live` and run only via `make live`.
5. **Explain-back** (every Claude-written PR; skipped for pure chores):
   - **Claude posts the answer key as a PR comment first.**
   - George then answers: *why this over the alternative*, and *how a test of it would fail*.
   - On ★ PRs, George also runs the **deletion experiment**: he deletes the named function, runs the tests, and pastes which test fails. *No failing test is itself a finding.*
   - George can dispute the key.
   - **One-retry escape:** two misses → the PR merges anyway, a "learning debt" entry goes in the FINDINGS-LOG, and that lesson must be rewritten in George's words before the phase tag.
6. **Log:** George adds 3 lines to `docs/FINDINGS-LOG.md`: what surprised me, what broke, what I'd change.
7. **Lesson:** update the vault; **George's Check-yourself answers are committed** to the lesson's "My notes".

**Mock interviews, three in total:** after `w1`, after `w3`, and before `v1.0.0`.
- A **fresh-context agent** that sees only the target postings and the README asks 5 questions, 2 with the repo closed.
- Verbatim answers go in the FINDINGS-LOG.
- A miss → George rewrites that lesson before the tag.

## 4. Calendar (10 h/week; this project first, payments at 2 h/week or less until v0.9, see D2)
| Week | Dates | Phase | Gate |
|---|---|---|---|
| W1 | Oct 26 – Nov 1 | 0 Spikes + plumbing (10 h) | Spikes done or defaults taken by **Sun Nov 1** |
| W2 | Nov 2 – 8 | 1 Thin vertical slice (10 h) | **`w1`: one real answer end to end by Sun Nov 8** |
| W3–W4 | Nov 9 – 22 | 2 Index + hybrid search (20 h) | `w2` by **Sun Nov 22**, otherwise take cut 1 |
| W5–W6 | Nov 23 – Dec 6 | 3 MCP + agent (16 h) | `w3` by **Sun Dec 6** |
| W6–W8 | Dec 1 – 20 | 4 Golden, graders, snapshot (24 h) | **`w4` = v0.9 by Sun Dec 20**, otherwise take the next cut |
| W9–W10 | Dec 21 – Jan 3 | Holidays (about 2 h/week, slack only) | |
| W11–W12 | Jan 4 – 17 | 5 Gate + security (18 h) | `w5` by **Sun Jan 17** |
| W13 | Jan 18 – 24 | 6 Release (10 h) | **`v1.0.0` Sun Jan 24** |
| W14 | Jan 25 – 31 | Buffer | |

**Total: about 108 h of planned work + about 10 h of slack ≈ 118 h** (process overhead of about 12 h is included in the phase budgets).

**125% rule:** at each phase end, if `HOURS.md` shows cumulative hours over 125% of the cumulative budget, **George picks** the next cut from §6.

## 5. Before we start (George)
| When | What |
|---|---|
| Now | Create the GitHub repo (command already given), then make CI a **required check** on `main` (admin-only) |
| W1 | Anthropic Console: a dev key with a **$20/month** org limit, plus a **CI workspace key capped at $10** |
| W1 | MongoDB Atlas → AI Model APIs → Voyage key (free 200M tokens, no card) |
| W1 | `uv python install 3.13` (uv reports Homebrew's 3.14 as broken). uv 0.12.23 and Docker 29.8 are already installed |

---

## Phase 0 · Spikes and plumbing (W1; 10 h) → no tag

**0.1 `chore/skeleton`** (Claude, chore)
- uv (Python 3.13, `uv.lock`), ruff, pytest + `hypothesis`, `.env.example`, `docs/HOURS.md`, `docs/FINDINGS-LOG.md`.
- Migrations as numbered SQL files plus a small runner (`make migrate`; **ADR 0002**).
- `make up` = compose + migrate (+ seed **only if an index dump exists**).
- CI: `on: pull_request`, default `permissions: contents: read`, SHA-pinned actions, `uv sync --locked`, ruff, pytest, gitleaks, and a Postgres + pgvector service container.
- **Done when:** a lint error fails CI; a migration test passes against the container.

**0.2 `chore/core-plumbing`** (Claude ★)
- pydantic-settings config; a JSON logger with trace ID that **redacts headers and keys**; an `ErrorCode` enum with every SPEC §8 code; `config/prices.toml`, dated, with its source.
- **Done when:** a test proves `Authorization`/`x-api-key` values never reach the logs; a cost test computes USD from a fixed usage object.

**0.3 `spike/unknowns`** (George runs it, Claude scaffolds; **5 h timebox**) → **ADR 0001**
1. **WDS:** 20 calls each to LatestNPeriods and the range call; record the reset rate.
2. **MCP:** a hello-world stdio server on `mcp` 2.x, registered via `claude mcp add`.
3. **Agent ↔ MCP:** confirm the SDK's beta helper `anthropic.lib.tools.mcp.async_mcp_tool` wraps a local stdio session under `mcp` 2.x, then measure one 3-tool round trip on Sonnet 5.5 and Haiku 5.5.
   - **Default if it fails:** one tool core with two front doors (the agent calls the Python tool functions in-process; MCP serves Claude Code).
- `spikes/` is deleted at the end; ADR 0001 records versions, the reset rate, the adapter choice and the cost.

## Phase 1 · Thin vertical slice (W2; 10 h) → `w1` + mock interview 1

**1.1 `feat/wds-client`**: **George: the limiter + its tests**; Claude: the client ★
- httpx host-allowlist hook (re-checked on redirects); 3 retries with jitter (resets, empty bodies, 5xx); 409 → `UPSTREAM_LOCKED_409`.
- `http_cache` migration with TTLs (24 h metadata, 6 h data); **errors and 409s are never cached**; error bodies returned only as escaped `untrusted_text`.
- **Done when:** vcr tests (`filter_headers`) cover every failure path; a `hypothesis` property test on a fake clock shows ≤10 requests per second; TTL and never-cache tests pass.

**1.2 `feat/get-series`**: **George: the coordinate builder + its tests**; Claude: the rest ★
- `DataBackend` + `LiveBackend`.
- `members` validated against metadata; ≤50 members per dimension; ≤120 points.
- LatestNPeriods as the primary call; `responseStatusCode != 0` or `vectorId == 0` → `BAD_MEMBERS`; the range call; null → suppressed; `NOT_FOUND` and `RATE_LIMITED`.
- **Done when:** unit tests cover each rule (Ontario + Rent = `14.81.0.0.0.0.0.0.0.0`), plus a `@live` test of 161.2 → 164.4.

**1.3 `feat/slice-cli`** (Claude)
- `canada-ask --table 18100004`, wired the way ADR 0001 decides, so 3.2 extends it rather than redoing it.
- **Done when:** `make live` answers the Rent question with +2.0% and a StatCan link; a demo recording is saved.

**1.4 `test/retrieval-set`** (**George: the 15 retrieval questions**; Claude: the linter)
- The linter checks schema, category mix, `checked_on_statcan_site`, ≥⅓ paraphrased and the low-overlap warning.
- **Done when:** the questions are committed **before any search code**, and the linter runs in CI.
- Lessons: [[Golden Sets]] (recaps [[Scoring Jobs for Fit]]), [[Rate Limiting with Token Buckets]], [[Retries, Backoff and Jitter]], [[Coordinates and Vectors in StatCan WDS]].

## Phase 2 · Index and hybrid search (W3–W4; 20 h) → `w2`

**2.1 `feat/scope-and-cards`** (Claude ★)
- `config/scope.toml` with prefixes confirmed live; archived tables (`"1"`) and the 525 null-subject tables excluded and logged.
- `table_card` + `member` migrations; cards ≤600 tokens with escaped footnotes; full-text over **all** member names.
- **Done when:** a test confirms Rent (81) is in `member` and in the full-text vector but not in the card text.

**2.2 `feat/embeddings-index`** (Claude ★)
- Voyage batching with 429 backoff; re-index keyed on hash(card + model).
- `make index` / `make seed` (`index.sql.zst` size measured; Git LFS if over 50 MB).
- The **query-embedding cache** + `make record`; on a miss, full-text only with a `degraded_retrieval` flag.
- Exact cosine scan with no HNSW (**ADR 0003**).
- **Done when:** a second index run embeds 0 cards; `make seed` works with no Voyage key.

**2.3 `feat/retrieval-eval`** (Claude)
- recall@5 (strict and lenient) and MRR on the 15 questions; ablation row 1 (vector).
- **Done when:** it runs on every PR from `make seed` + the cache.

**2.4 `feat/hybrid-search`**: **George: RRF + its tests**; Claude: the ORed full-text query
- **Done when:** ablation rows 2–3 are committed; the README notes `ts_rank_cd` ≠ BM25.

**2.5 `feat/rerank`** (Claude; cut 1)
- **Done when:** ablation row 4; **ADR 0004** records enable or disable from the measured recall@5.
- **George: golden batch 1 (10 cases).**
- Lessons: [[Chunking for Retrieval]], [[Embeddings]], [[Retrieval Metrics]], [[Hybrid Search and RRF]].

## Phase 3 · MCP tools and agent (W5–W6; 16 h) → `w3` + mock interview 2

**3.1 `feat/mcp-server`**: **George: the 3 tool descriptions**; Claude: the wiring ★
- Strict schemas; `untrusted_text` with marker-like tags stripped; server-built URLs; a 4k result cap; a tool-description snapshot test; stdio only (**ADR 0005**).
- **Done when:** an in-process MCP client test lists and calls all 3 tools against a fake backend.

**3.2 `feat/agent`**: **George: system prompt v1 + canary, budget/stop logic, refusal path**; Claude: the loop ★
- The Learn step includes the docs check of the model IDs, `fallbacks: "default"` and the structured-output syntax.
- Sonnet 5.5 locally, **Haiku 5.5 in CI**; the prompt version is recorded per run; `answer_values` + `refused`.
- Logs carry trace ID, per-tool latency, cache hit, tokens and USD.
- **Done when:** a stub-model test covers `BUDGET_EXCEEDED`; `make live` answers 5 demo questions; a GIF is recorded from `--trace`.
- **George: golden batch 2 (10 cases).**
- Lessons: [[MCP Servers]], [[Tool Description Design]], [[System Prompts and Canaries]], [[Structured Outputs]], [[Prompt Injection]].

## Phase 4 · Golden set, graders, snapshot (W6–W8; 24 h) → `w4` = **v0.9**

**4.1 `test/golden-final`** (**George: batches 3–4, 20 cases → 40**)
- **Done when:** the linter passes on 40 (24 dev / 16 test). **Iterating the prompt and tool descriptions on results is allowed from this merge onward.**

**4.2 `feat/snapshot`** (Claude ★)
- `make snapshot`; a `SnapshotBackend` with live-shaped errors; `SNAPSHOT_MISS` counts as a failure (**ADR 0006**).
- **Done when:** the SnapshotBackend returns the same error codes as the LiveBackend for every vcr failure fixture.

**4.3 `feat/offline-and-transcripts`** (Claude)
- A strict host hook (Anthropic only); `make transcripts` records and commits dev-run transcripts as grader fixtures.
- **Done when:** a dev run (k=1) completes offline except for Claude; the transcripts are committed.

**4.4 `feat/graders`** (**George: the graders + their tests**; Claude: the good/bad fixtures)
- Retrieval inside the run, values-in-prose, grounding recompute, citation host, refusal, trajectory (**ADR 0007**).
- **Done when:** the graders pass 10 good transcripts and fail each of 10 bad ones for the stated reason, and run on the 4.3 transcripts in every-PR CI.

**4.5 `feat/history`** (Claude)
- The `history.jsonl` writer with every SPEC §10.7 field, plus a schema test.

**v0.9 release note:** retrieval ablation, agent, offline graders and history. **A portfolio-ready state even if the plan stops here.**

## Phase 5 · Gate and security (W11–W12; 18 h) → `w5`

**5.1 `spike/flakiness-study`** (Claude runs it; 4 h; about $5)
- The dev set ×5 on `main` → the quarantine list in the README, plus the measured cost per gate run.
- **If it's over the spec's $2 cap,** George chooses amendment draft A3 (k=2) or A4 (fewer dev cases). There's no silent fallback.

**5.2 `ci/eval-gate`**: **George: `gate_rules.py` + its tests + the statistics ADR (0008)**; Claude: the CI wiring ★
- k=3 on ready-for-review PRs; the flip rule; a mean drop over 10 points; the $2 actual-cost cap; a CI diff flag on `evals/`, `snapshots/` and the baseline.
- Forks never get the key. **`pull-requests: write` only on this job.**

**5.3 `test/injection-suite`** (**George: the pass criteria**; Claude: the fixtures)
- 6 cases (card/footnote, member name, error body × 2 goals), each passing at k=3.
- A "limits of this suite" README section.

**The gate's evidence:** the README links **the first PR the gate fails naturally** (from the FINDINGS-LOG). Only if none has happened by `w5` does a demo PR stand in: a degraded tool description, with the failure predicted in writing first, **labelled as staged**.
- Lesson: [[Eval Gate Statistics]].

## Phase 6 · Release (W13; 10 h) → `v1.0.0` + mock interview 3

**6.1 `docs/v1-release`** (**George: `FINDINGS.md` curated from the log, the claims table, every ADR decision section**; Claude: the chart script)
- The `v1.0.0` tag triggers the one test-split run → the headline with its Wilson interval.
- The chart, ADR index, quarantine list, and a `claude mcp add` quickstart.
- **Done when:** a **fresh-clone CI job** (tags and manual dispatch only, **stub model, no key**) runs `make seed` + `canada-ask --offline` in under 10 minutes.

---

## 6. Cut lines (in order)
1. Drop rerank (2.5).
2. Injection 6 → 3 (**amendment draft A2**).
3. Golden 40 → 30 (**A5**).
4. Flakiness ×5 → ×3 (**A6**).
5. Stop at v0.9.

The amendment drafts A2–A6 are written in Phase 0 (`docs/amendments/`), so they're ready to approve when needed.

## 7. ADR register
0001 spikes and the agent↔MCP adapter (0.3) · 0002 migrations without an ORM (0.1) · 0003 exact scan, no HNSW (2.2) · 0004 rerank decision (2.5) · 0005 stdio-only MCP (3.1) · 0006 snapshot vs cassettes (4.2) · 0007 grader design (4.4) · 0008 gate statistics (5.2). George writes each Decision and "Why not X".

## 8. Out of scope
SPEC §5 v1.1: the Open Canada/FX tools, LLM judge, weekly drift job, month-to-date guard, `compute` tool, more cases, Dependabot, image digests.

## 9. Decisions for George (approving this plan approves A1 and the defaults below)
- **D1 Ownership:** the split in §2 (default), or "Claude writes everything".
- **D2 Sequencing:** this project first, with payments at 2 h/week or less until v0.9 (default). Flip it if most of your live applications in the next month are fintech or .NET roles.
- **D3 Pre-approval:** approve Phases 0–1 now so W1–W2 run without a stop.
- **A1 Spec amendment:** add the 15 retrieval questions as an official dev-only set (SPEC §10.2). Retrieval choices are made on them; prompt and tool-description tuning waits for all 40 golden cases.

---

## §R Response to the reviews (round 1 → v0.3, round 2 → v1.0)
| Point | Critic | Response |
|---|---|---|
| Estimates reflected Claude's typing speed, not George's pace | Schedule | Accepted: 61 h → about 118 h, ending Jan 24 plus a buffer week |
| Calendar a day off; holiday weeks missing | Schedule (R2) | Accepted: dates recomputed (Oct 26 is a Monday); W9–W10 at about 2 h |
| Cut lines undated | Schedule | Accepted: dated gates, the 125% rule fed by `HOURS.md`, George picks the cut |
| Nothing demo-able until week 6; W2 overloaded | Schedule | Accepted: a thin slice demo by Nov 8; golden cases moved out of W2 (only the 15 retrieval questions remain) |
| Process weight is the biggest risk to finishing | Schedule (R2) | Accepted: the deletion experiment only on ★ PRs, 3 mock interviews (not 6), chores skip the explain-back, the one-retry escape |
| Tool runner can't use stdio MCP | Tech lead | **Rejected with evidence** (the SDK's beta `async_mcp_tool` helper); the tech lead agreed in R2. The spike confirms it with `mcp` 2.x |
| CI ordering, migrations, plumbing, price table, history writer, 4.3 size, live tests in CI | Tech lead, auditor | Accepted (0.1, 0.2, 2.2, 4.2–4.5, `@live`) |
| `make up` seeding before an index exists; CI permissions too broad; recorded transcripts missing; slice rework; 4.3a "Done when"; fresh-clone job spending the key | Tech lead (R2) | Accepted: a conditional seed; `pull-requests: write` only on the 5.2 job; `make transcripts` in 4.3; 1.3 wired the ADR 0001 way; a "Done when" added; the fresh-clone job uses a stub model with no key |
| Golden set written after tuning; then "results-justified" too loose for the rerank decision | Auditor (R1, R2) | Accepted: amendment A1 plus a strict rule (prompt and tool descriptions can't be tuned on results before all 40 cases) |
| k=2 / $4 trigger contradicts the spec's $2 cap; unmarked amendments | Auditor (R2) | Accepted: the trigger removed; every spec-changing cut goes through a pre-written amendment |
| Missing ADRs; George should write PR descriptions | Auditor (R2) | Accepted: the ADR register (§7); George writes each description (Claude supplies a list of changed files) |
| Ownership inverted | Coach | Accepted (D1 default) |
| Claude both writes the code and marks the explain-back | Coach (R2) | Accepted: the answer key is posted first, George can dispute it, the deletion experiment, a fresh-context interviewer with verbatim logs |
| George should write the tests for his own pieces | Coach (R2) | Accepted (§2) |
| Explain-back budget too light | Coach, schedule (R2) | Accepted: about 12 h of overhead built into the phase budgets |
