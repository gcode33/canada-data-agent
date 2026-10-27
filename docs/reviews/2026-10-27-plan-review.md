# Plan review transcripts (2026-10-26)

Two-round adversarial review of PLAN v0.2 (round 1) and v0.3 (round 2). Round 1: independent critiques. Round 2: critics verify the planner's revision.


---

## r1-techlead

# R1 Tech-lead review of PLAN v0.2

## BLOCKERS
1. **1.4 CI depends on 4.3.** "CI runs it on every push using `make seed` and the cached query embeddings" needs the query-embedding cache and `make record` (4.3), plus a Postgres+pgvector service container nobody added. Also contradicts 0.1 (`on: pull_request` only). **Change:** move the query-embedding cache (keyed on normalised text, `make record`) into 1.3; add a pgvector service container to CI in 1.2 (first step with a DB test); reword 1.4 to "on every PR".
2. **No migration tool.** 1.2 says "with migrations", 1.1 already needs `http_cache`. **Change:** 0.1 picks one (numbered SQL files + a small runner, or Alembic without ORM) and `make migrate`; 1.1 adds the `http_cache` migration explicitly.
3. **Spike 0.2.3 asks the wrong question.** The SDK tool runner runs local Python tool functions; the API's MCP connector reaches remote HTTP servers, not stdio. The real decision is "one tool core, two front doors (MCP server + tool-runner functions)" vs "agent spawns a stdio MCP client". **Change:** spike question becomes "can the agent call the same tool functions in-process, keeping MCP for Claude Code only?"; check the installed SDK for any MCP-to-tool helper and record the version in the ADR. Measure tokens on the model the agent ships with (Sonnet, 3.1), not only Haiku. (Not web-verified in this review; the spike must verify.)

## MAJOR
4. **Config/secrets/logging/errors have no home.** **Change:** add 0.3 `feat/core-plumbing`: pydantic-settings config (fail fast only on keys a command needs), JSON logger with header/key redaction + test, an `ErrorCode` enum (`UPSTREAM_LOCKED_409`, `BAD_MEMBERS`, `BUDGET_EXCEEDED`, `SNAPSHOT_MISS`).
5. **Price table and `history.jsonl` writer missing.** 3.2 logs USD with no price source; 5.1's "$2 actual-cost cap" and 6.1's chart need the writer. **Change:** 3.2 adds `config/prices.toml` (dated, source URL) + cost test; new 4.4 adds the `history.jsonl` writer with a schema test.
6. **4.3 too big** (recorder, backend, error fidelity, embedding cache, strict host hook). **Change:** 4.3a `make snapshot` + `SnapshotBackend`; 4.3b strict offline mode (embedding cache moved to 1.3 per #1).
7. **2.4 Done-when is a manual Claude Code session.** **Change:** in-process MCP client test lists 3 tools and calls each against a fake backend; screenshot supplementary.
8. **2.3 live smoke test will flake in CI** on WDS resets. **Change:** `@pytest.mark.live`, excluded from CI, run via `make live`.
9. **5.1 flakiness study (dev x5) is a spike.** Budget it ($ and h) as its own step before building the gate.

## MINOR
10. Making CI a required check needs repo admin (George) - move to "Before we start".
11. 1.1: name `hypothesis`; limiter property test on a fake clock, not wall time.
12. 1.3: state the size of `index.sql.zst` and whether it needs Git LFS.
13. Local dev: add `make up` / `make dev` (compose + migrate + seed) in 0.1.
14. 6.1 "stranger in <10 min": add a CI fresh-clone job or a named tester.
15. 61 h has no slack for the Learn/Lesson steps; add ~15% buffer.

## PLANNER BLIND SPOTS
- **Layer-by-layer transcription of the spec:** features were placed where the spec mentions them, without tracing cross-cutting needs (cache, DB in CI, prices) back to the first step that uses them.
- **Demo-shaped "Done when":** screenshots, GIFs and "answers +2.0%" stand in for automated assertions; live-network checks leak into CI.
- **Plumbing invisibility:** config, logging, migrations and error enums are assumed to exist because they are boring.
- **Over-trust in its own API recall:** the tool-runner/MCP spike presumes a capability instead of asking an open question, and prices on Haiku while shipping Sonnet.


---

## r1-audit

# R1 spec-conformance audit: PLAN v0.2 vs SPEC v1.0

## Gaps
| Spec ref | Status | Proposed change |
|---|---|---|
| §10.2 golden set "committed before any tuning" | ORDER | 2.1/2.2 (ablation, rerank decision), 2.4 (tool descriptions), 3.1 (prompt v1) all tune before 4.1. Move 4.1 to Phase 0/1 (George writes cases early; values checked later), or the plan has to say in writing that retrieval-only tuning uses the separate 15 questions |
| §10.6 query-embedding cache + `make record`; §4 no Voyage key in CI | ORDER | 1.4 says CI uses "cached query embeddings", but the cache only arrives in 4.3. Move the cache and `make record` into 1.4 |
| §10.5 permissions `pull-requests: write` | PARTIAL | 0.1 sets only `contents: read`, so 5.1's CI diff comment can't post. Add it in 0.1 (or 5.1) |
| §10.5 every push: graders on recorded transcripts | PARTIAL | 4.2 builds fixtures but never wires them into CI. Add to 4.2's Done when |
| §10.3 retrieval grader inside the agent run | MISSING | 4.2 lists values, grounding, citation, refusal and trajectory, but no recall@5/MRR per run |
| §10.7 history.jsonl schema (model, prompt version, cache tokens, USD from a price table, p50/p95, per-category scores) | MISSING | No step creates it; 6.1 only charts it. Add it to 4.3 or 5.1, with a price-table file |
| §9 run records the prompt version; Haiku 5.5 in CI | PARTIAL | 3.1 configures only Sonnet. Add a model switch and record the prompt version |
| §7.1 archived tables excluded | MISSING | Add to 1.2's Done when |
| §8 validate members against cached `member` table; WDS range call `getDataFromVectorByReferencePeriodRange`; `NOT_FOUND`/`RATE_LIMITED` codes; ≤50 members per dimension, `filter` | PARTIAL | Add tests to 2.3 |
| §8 cache TTLs (24 h metadata, 6 h data); 409s never cached | PARTIAL | 1.1 says only "never caches errors". Add TTLs and a 409 test |
| §11 marker-like tags stripped; upstream error bodies routed through `untrusted_text` | MISSING | 2.4 escapes but doesn't strip. Error-body poisoning is one of the 3 injection vectors (5.2), so 1.1/2.4 must carry error bodies as `untrusted_text` |
| §11 headers/keys never logged | MISSING | Add a log-redaction test in 3.2 |
| §12 logs: trace ID, per-tool latency, cache hit | PARTIAL | 3.2 says only "tokens and USD" |
| §7.4 README states `ts_rank_cd` ≠ BM25; §10.4 quarantine listed in README; §10.2 low-overlap warning | MISSING | Add to 6.1 / 5.1 / the 4.1 linter |
| §13.1 day one: verify model IDs + `fallbacks` | PARTIAL | 0.2 checks mcp only. Add model ID and fallbacks checks to ADR 0001 |
| §2 / F10 ADR per decision | PARTIAL | Only ADRs 0001 and 0002 exist. Add ADRs for snapshot vs cassettes, no HNSW, stdio-only, gate thresholds and graders |
| §2 FINDINGS: 3 real failures the evals caught | PARTIAL | Nothing records catches as they happen. Add a running `FINDINGS.md` log from 4.2 on |

## CONTRADICTIONS
- **PR descriptions:** §2 says "George writes each description". The plan has Claude open PRs and write them (step 5 of "How each step runs").
- **"A linked PR that the gate really failed" (§2, W5):** 5.3 is a deliberate sabotage of a tool description, which is a staged demo, not a real catch. It's fine as a fallback, but label it honestly, or prefer a genuine failed PR.
- **Cut line 3 (30 cases):** this changes F5/§10.2 (40 cases, 24/16) in an approved spec. It needs a spec amendment, not a plan footnote. Cut line 2 also drops injection from "v0.9", but §14 allows only retrieval plus the offline gate. That's consistent, but say the injection claim is withdrawn.
- **1.4's 15 extra retrieval questions** aren't in the spec (it measures retrieval on golden `expected.tables`). That's acceptable scope, but say they are dev-only and not the headline.
- **"Out of scope"** omits Dependabot and image digests (§3/§5 v1.1). Harmless, but incomplete.
- No v1.1 scope creep found.

## PLANNER BLIND SPOTS
- **It traced the features (F1–F10) and the milestone table, not the MUST rules buried in §7–§12.** Small invariants (archived exclusion, TTLs, tag stripping, key redaction, error-body escaping, prompt-version recording) silently fell out.
- **It got dependency order wrong on cross-cutting artifacts.** The query-embedding cache, history.jsonl and the "before tuning" rule are consumed earlier than they're built. Claude ordered by layer (data → agent → evals), but the spec's integrity rules are time-ordered.
- **It favoured its own workflow over the spec's ownership rules.** "Claude opens PRs", the staged failed PR and a cut line that edits approved scope all quietly weaken the "did he build this himself?" evidence the spec was designed around.


---

## r1-schedule

# R1 Schedule review: ai-eval-lab PLAN v0.2

Verdict: 61 h is a best-case, zero-friction number. Honest range is 90-105 h. At 10 h/week that is 9-10 weeks; sharing time with the payments project it is 5+ months.

## Re-estimate
| Phase | Plan | Honest | Why |
|---|---|---|---|
| 0 Spikes/skeleton | 5 | 8 | uv/Docker/CI SHA-pinning/gitleaks/required checks, 3 spikes against a flaky API, ADR writing |
| 1 Data/retrieval | 10 | 16 | WDS resets, scope confirmation, schema/migrations, Voyage onboarding, George-written limiter + property test (~4 h), 15 retrieval questions with real labelling |
| 2 Hybrid/MCP | 10 | 15 | RRF by hand ~2 h, coordinate builder vs real StatCan quirks, MCP 2.x is new, snapshot test, screenshot |
| 3 Agent | 8 | 10 | tool runner/MCP adapter surprises, budgets, GIF |
| 4 Golden/graders/snapshot | 12 | 22 | 40 cases x ~20 min (find table, pick members, read value off site, paraphrase, refusal cases) = ~13 h alone; graders 4-5 h incl. 20 transcripts; snapshot ~4 h |
| 5 Gate/security | 10 | 15 | flakiness study = 5 full runs plus triage; gate logic, secrets, fork safety, 6 injection cases; CI debug loops |
| 6 Release | 6 | 9 | fresh-clone test always finds 2-3 bugs; FINDINGS.md needs real before/after |
| Total | 61 | ~95 | |

17 PRs x (learn + review + PR description + vault lesson) is ~1 h overhead each; the per-step numbers do not visibly include it.

## BLOCKERS
1. **Capacity is double-booked.** 10 h/week here while the 13-week payments project and the Lynked job also run. Change: state an explicit weekly split (see sequencing); replace "about 6 weeks" with "about 10 weeks at 10 h/week, with calendar dates".
2. **Cut lines have no dates.** "Phase over by 50%" is per phase; uniform +30% drift never triggers it. Change: add calendar gates (Phase 2 tagged by end of W4, Phase 4 by end of W7) with the next cut applied automatically at the date, plus a rolling rule: at each phase end, if cumulative hours > 125% of cumulative budget, take the next cut.
3. **Nothing demo-able until end of Phase 2 (~hour 35, realistically week 6).** Change: add a thin vertical slice by end of W2: one hardcoded table, one get_series call, one CLI answer. Move 2.3 (get_series) ahead of 1.3/1.4 so "Ontario rent 161.2 -> 164.4" runs early.

## MAJOR
1. Golden set is the biggest underestimate and sits behind Phases 1-3 where tuning pressure builds. Change: land the linter first, then write ~10 cases per week from Phase 1 (cap 2 h/week), merged in 4 batches. 4.1 becomes a finish, not a cliff.
2. Cut order is wrong for the portfolio claim. Cut 2 (v0.9, no gate) removes the headline ("PR the gate really failed"). Reorder: (1) rerank, (2) injection suite 6 -> 3 cases, (3) golden set 40 -> 30, (4) flakiness study dev x 3, and only then (5) v0.9.
3. Spike 3 failing "revisits the spec" is an unbounded cost. Add: timebox 5 h total; MCP + tool-runner failure defaults to the thin adapter, not a spec revisit.
4. Ownership rule: George-written pieces are learning, not delivery. Budget 2x (limiter, RRF, coordinates, graders ~12 h, not 6 h) and decide now explicitly.
5. CI flakiness study is one bullet for what is normally a multi-evening effort. Give it its own PR and 4 h.

## MINOR
- Add a 15% contingency line to Total.
- Pre-agree an action if the first gate run costs >$4 (it would eat the $10 CI key in ~3 PRs).
- Do Voyage/Atlas signup in Phase 0; if it stalls it blocks Phase 1.
- "Stop for go-ahead before each phase" adds latency; pre-approve planned phases.

## Sequencing vs payments project
Do not run both at 10 h/week. Recommend: **eval lab first to v0.9 (Phases 0-4), payments frozen to <=2 h/week** (keep a PR cadence alive, nothing more); then resume payments full pace while eval lab Phases 5-6 run at ~3 h/week. Reasons: the eval lab maps directly to the AI/LLM target postings and is demo-able in ~5 weeks; payments is a 13-week .NET project (secondary stack), still early, so a pause costs little; one finished flagship beats two half-built ones. Counter-consideration: if live applications are fintech/.NET in the next 4 weeks, flip it. Ask which applications are live.

## PLANNER BLIND SPOTS
- Estimated Claude's typing speed, not George's throughput: learning, whiteboarding and George-writes steps run 2-3x.
- Treated manual human work (40 cases verified on the StatCan site, hand-labelled retrieval questions, hand-made transcripts) as small tasks; it is ~25 h and cannot be delegated.
- No slack for Lynked crunch weeks or illness, and ignored the concurrent payments commitment; 10 h/week is assumed fixed.


---

## r1-coach

# R1 Coach review of PLAN v0.2

## BLOCKERS
1. **Ownership split is inverted.** Hand-written: RRF (about 15 lines), token bucket, coordinate builder, graders. These are the easiest-to-explain pieces. Interviewers (Cohere, BMO, Deloitte AppSec) probe: why this golden set, why these tool descriptions, why the gate flips, what the CI statistics mean, what the injection suite does NOT prove. All of those are "Claude writes, George reviews" in the plan. Change: add to George-writes: system prompt v1 and every revision (3.1), tool descriptions and their snapshot (2.4), the eval-gate decision rules (flip rule, 10-point drop, Wilson interval, k=3 rationale; 5.1 becomes "George writes `gate_rules.py` + ADR; Claude wires CI"), injection pass criteria (already his).
2. **"George reviews" has no pass condition.** The payments project showed review-only does not stick. Add to every Claude-writes step an explain-back gate: before merge, George answers 3 questions in the PR description in his own words (what breaks if X is deleted; why this over the alternative; how would a test of it fail). Claude marks each right or wrong; no merge until all are right. Without this, "must be able to whiteboard every file" is unenforceable.
3. **Golden set lands too late and is under-budgeted.** 4.1 is 40 cases checked by hand on the StatCan site, probably 5-6 h alone inside a 12 h phase. Move the 15 retrieval questions of 1.4 into the golden file as the seed (labels before results), so 4.1 is 25 new cases.

## MAJOR
- **Agent code (3.1/3.2) entirely Claude's.** "Walk me through your agent loop" is the most-asked question. George writes the budget/stop logic (about 40 lines) and the refusal path.
- **Spikes (0.2) "Claude, pairing".** The WDS reset rate and the MCP adapter question are exactly what he should run and log. Flip it: George runs, Claude scaffolds.
- **No running FINDINGS log.** 6.1 asks for 3 real catches written in week 6 from memory. Add `docs/FINDINGS-LOG.md`: a 3-line entry after every PR (surprised me / broke / would change). 6.1 curates it.
- **Lesson order and gaps.** [[Golden Sets]] is scheduled at 4.1 but its idea (labels before results) is needed at 1.4; write it there, recapping [[Scoring Jobs for Fit]] (status `new`). Add missing lessons: Eval Gate Statistics (Wilson, repeats k, flake quarantine), Tool Description Design, System Prompts and Canaries. Claude writes the lesson, but George owns `status` and My notes: require him to answer one Check-yourself question unprompted per lesson before the phase moves on.
- **No mock interview.** Add a 20-minute gate at the end of each phase: Claude plays a skeptical interviewer built from the target JDs, 5 questions, 2 of them with the repo closed. Log result in FINDINGS-LOG. A miss means rewriting the relevant lesson in his words before the tag.
- **Statistics are unowned.** If George cannot say why k=3 and what a Wilson interval on n=16 means (very wide, roughly plus or minus 20 points), the headline claim is indefensible. 5.1 needs his written justification.

## MINOR
- 5.3 never-merged PR: George authors the degradation and writes his predicted failure in the PR first.
- Say explicitly that plumbing (0.1, 1.3, 2.2, 2.4 server shell, CI, cassettes, migrations) is Claude's by decision, not by default.
- Time budget ignores explain-back and mock-interview time.
- Claude writes ADRs and lessons, so the reasoning trail is Claude's. George drafts ADR "Decision" and "Why not X" himself; Claude only edits.

## OWNERSHIP RECOMMENDATION
Keep the four spec pieces (about 6 h). Add: system prompt + tool descriptions (about 3 h incl. iteration), gate rules + stats justification (about 3 h), agent budget/stop logic (about 1.5 h), running the spikes (about 1 h extra), ADR decision sections (about 1.5 h). George-writes total about 16 h. Add about 4 h of explain-backs (about 20 min x 12 reviewed PRs) and about 2 h of mock interviews (6 x 20 min). Net plan grows from about 61 h to about 72 h, roughly 7 weeks at 10 h. Pay for it by dropping 2.2 rerank first (about 3 h). Do not hand-write plumbing.

## PLANNER BLIND SPOTS
- Claude kept the judgment-heavy artefacts (prompt, tool descriptions, gate, ADRs, lessons) and gave George the well-specified, unit-testable ones. That is the easy-to-delegate set, not the interview set.
- Done means "CI green and PR merged", never "George demonstrated understanding". Claude reviewing its own PRs is no independent check.
- "We stop for go-ahead" is a permission checkpoint, not a comprehension checkpoint.


---

## r2-techlead

# R2 Tech-lead verification of PLAN v0.3

## 1. Verdicts on round-1 points
1. 1.4 CI needed the 4.3 cache and Postgres: **FIXED** (cache in 2.2, pgvector container in 0.1, "every PR").
2. No migration tool: **FIXED** (numbered SQL + runner, `make migrate`, `http_cache` migration in 1.1).
3. Tool runner + stdio MCP: **the rejection is fair.** I asserted the limitation without checking. The fallback is the design I proposed, and it applies without a spec revisit. Measuring cost on Sonnet is also **FIXED**.
4. Config, logging, ErrorCode: **FIXED** (0.2, with a redaction test).
5. Price table and history writer: **FIXED** (0.2 prices, 4.4 writer).
6. 4.3 too big: **FIXED** (4.3a/b), but 4.3a has no "Done when" (see below).
7. MCP Done-when was manual: **FIXED** (in-process client test).
8. Live test in CI: **FIXED** (`@live`, `make live`).
9. Flakiness study as a spike: **FIXED** (5.1, timeboxed, with a pre-agreed rule).
10. Required check / admin: **FIXED**.
11. `hypothesis` + fake clock: **FIXED**.
12. `index.sql.zst` size: **FIXED** (measured, LFS over 50 MB).
13. `make up`: **PAPERED OVER**. It runs `seed`, but `make seed` only exists from 2.2.
14. Fresh-clone check: **FIXED in form**, see new problem e.
15. Buffer: **FIXED**.

## 2. New problems
a. **4.2 "graders on recorded transcripts in every-PR CI"**: no step records or commits transcripts. **Change:** 4.3b or 4.4 adds `make transcripts` with committed fixtures, and 4.2 depends on it.
b. **The 1.3 slice wires the tool runner to plain functions, and 3.2 may switch to the MCP adapter.** That is rework. **Change:** 1.3 uses whichever adapter ADR 0001 chose.
c. **Phase 0 is 10 h with a 5 h spike plus two plumbing PRs.** That is tight. **Change:** move the 0.3 docs check (item 4) into 3.2's Learn step, or accept slipping into W2.
d. **0.1 grants `pull-requests: write`** without a stated need. **Change:** keep `contents: read` and grant write only in the job that posts comments (5.2).
e. **6.1 fresh-clone CI job runs `canada-ask --offline`, which still calls Anthropic.** That spends the CI key on every run. **Change:** run it on tags or manual dispatch only, with a stub model for the timing check.
f. **4.3a has no "Done when".** **Change:** "SnapshotBackend returns the same error codes as LiveBackend for each vcr failure fixture."
g. **Inconsistency:** the ground rules say golden batches start in W1, §R row 10 says W2, and 1.4 is in W2. Pick W2.

## 3. Ready for Phase 0?
**YES-WITH-CHANGES:** fix 13 (`make up` seeds only when an index exists), d, and g now. Fix a, b, c, e and f before their phases start.


---

## r2-audit

# R2 spec-conformance audit: PLAN v0.3

## 1. Round-1 items
- Golden set before tuning (§10.2): **PAPERED OVER.** See N1.
- Query-embedding cache order: **FIXED** (2.2, before 2.3).
- `pull-requests: write`: **FIXED** (0.1).
- Graders on recorded transcripts in CI: **FIXED** (4.2).
- Retrieval grader inside the run: **FIXED** (4.2).
- `history.jsonl` schema and price table: **FIXED** (0.2, 4.4).
- Haiku in CI and prompt version per run: **FIXED** (3.2).
- Archived tables excluded: **FIXED** (2.1).
- §8 member validation, range call, codes, ≤50 members: **FIXED** (1.2).
- TTLs and never caching 409s: **FIXED** (1.1).
- Tag stripping and error bodies as `untrusted_text`: **FIXED** (1.1, 3.1).
- Header/key logging test: **FIXED** (0.2).
- §12 log fields: **FIXED** (0.2, 3.2).
- README notes (BM25, quarantine list, overlap warning): **FIXED** (2.4, 5.1/6.1, 1.4).
- §13.1 model IDs and `fallbacks`: **FIXED** (0.3).
- ADR per decision: **PAPERED OVER.** Only 0001, 0002 and the gate ADR are named. The snapshot-vs-cassette, no-HNSW, stdio-only, adapter and grader ADRs are still unassigned.
- FINDINGS evidence: **FIXED** (per-PR log).
- PR descriptions by George: **PAPERED OVER.** George writing the "why" is a defensible reading of §2, but the spec says "writes each description". Either amend the spec or have George write the whole description.
- Staged failed PR: **FIXED** (a natural failure is preferred; any staged one is labelled).
- Cut to 30 cases: **FIXED** (needs a spec amendment).
- Out-of-scope list: **FIXED.**

## 2. New contradictions
- **N1, golden rule vs §10.2.** "Committed before any tuning" is weakened to "no change justified by results until all 40 exist". Yet 2.5 enables or disables rerank from measured recall, and 2.4 commits ablation rows, before 4.1. The rerank ADR is a results-driven tuning decision made with only 20 of the 40 cases committed. The fix is either to put the 15 retrieval questions in the spec as the ablation set, or to finish the golden set before 2.5.
- **N2.** The ground rule says batches start in W1; §R #10 says W2. Pick one.
- **N3, 5.1's "drop to k=2" via an ADR.** This changes §10.4/§10.5 (k=3) without the amendment the plan's own ground rule requires. The >$4 trigger also contradicts the spec's $2-per-run cap: a run costing over $2 already fails the gate.
- **N4, cut 4 (flakiness study ×5 → ×3).** This edits §10.4 but isn't marked "needs a spec amendment".
- **N5, the 15 retrieval questions.** They're not in the spec, and nothing defines their relationship to golden `expected.tables` (the source §10.3 names for offline recall). State whether ablation uses them, the golden dev cases, or both.
- **N6, CI fresh-clone job.** `canada-ask --offline` still calls Claude, so the job needs the key. Restrict it to tag/ready-for-review runs so it follows the §10.5 fork and cost rules.

## 3. Verdict: YES-WITH-CHANGES
Phase 0 touches none of the open items, so it can start now. Resolve these before Phase 2:
1. Fix N1 and N2: write the 15 retrieval questions into the spec, or move the rerank decision after `w4`.
2. Mark k=2 and flakiness ×3 as spec amendments, and remove the $4 trigger.
3. Assign an owner and step to each outstanding ADR.
4. Settle the PR-description rule with a spec amendment, or have George write the whole description.
5. Scope the fresh-clone job to keyed, non-fork runs.


---

## r2-schedule

# R2 Schedule review: PLAN v0.3

## 1. Round-1 points
- Capacity double-booked: FIXED on paper (D2, 2 h/week payments). Not tested against Lynked crunch weeks; no weekly hour log or trigger if the 10 h isn't happening.
- Undated cut lines: PARTLY FIXED. Dates exist for W2/W4/W7 only, and all are wrong (below). The 125% rolling rule is good.
- Nothing demo-able until W6: FIXED (slice demo in W2), but W2 is overloaded (below).
- Cut order: FIXED for the headline claim. Cuts 2 and 3 now need a spec amendment, which is correct. The reordering skips "shrink the injection suite" being cheap, fine.
- Spike unbounded: FIXED (5 h timebox, default adapter).
- Golden set cliff: FIXED in structure (4 batches), PAPERED OVER in hours (see 2).
- George-written 2x: PAPERED OVER. Plan says "about 20 h George-written" but the per-phase hours barely moved from the 61 h plan structure.
- Flakiness study own PR: FIXED (4 h, $5, k=2 fallback).
- Contingency 15%: FIXED. Gate cost action: FIXED. Voyage signup in Phase 0: FIXED (W1). Phase pre-approval: FIXED (D3).

## 2. Is ~108 h honest?
Close, but the composition is off. Phase sums (10+10+16+12+18+14+9) = 89, +6, x1.15 = 109. Arithmetic holds. Problems:
- **Explain-backs and overhead are under-counted.** 19 PRs x 3 answers, marked by Claude, rewrites on a miss, ~20 min each = ~6-7 h alone. Mock interviews 7 x 20 min = 2.3 h plus rewrites after misses. FINDINGS-LOG 19 x 10 min = 3 h. Lesson Check-yourself per phase ~2 h. Realistic ~12-14 h, not 6. The 15% buffer then covers only 60% of what it needs to cover.
- **W2 (10 h) is not feasible.** Limiter + property test on a fake clock (~4 h George), coordinate builder (~2.5 h George), slice CLI (1.5 h), golden batch 1 = 15 retrieval questions + 10 cases checked on the site (~6-7 h), 4 lessons, explain-backs. ~16-18 h. Move golden batch 1 to be 5 questions + 5 cases, or push the slice demo to W3.
- **Phase 4 at 18 h is thin:** batch 4 (3-4 h) + graders by George with 20 transcripts (5-6 h) + snapshot generation across all 40 cases (4 h) + offline mode + history = ~20-22 h.
- **Phase 5:** George writing gate_rules plus ADR on Wilson statistics is new learning (~4 h); at 14 h total it is tight.
- Realistic total ~115-120 h, i.e. 12 weeks at 10 h, not 10 + 1 buffer.

**Calendar dates are wrong.** Oct 27 2026 is a **Tuesday**, not Monday. The "Mon" labels (Nov 3, Nov 10, Dec 1, Dec 15, Jan 5) are all Tuesdays, and the "Sun" gates (Nov 2, Nov 9, Nov 23, Dec 14) are actually **Mondays**, one day late. W1 starts with 6 days and the Sunday gate sits in the next week. Holidays: only Dec 15 week is counted at 5 h. Missing: Dec 22 week (Christmas, likely 0-3 h) and Dec 29 week (New Year; W10 Jan 5 start gives the Release phase no real slack). With W8 at 5 h and the Christmas week lost, Phase 5 (14 h) cannot finish in W8-W9: it ends ~mid Jan. Plan for v1.0 around **end of January**, with v0.9 on Dec 14 as the realistic, honest first milestone (and that date itself is at risk).

## 3. New risks in v0.3 and readiness
- **Gate fatigue / process-heavy:** explain-back + mock interview + log + lesson on every PR and phase turns a 10 h week into ~7 h of building. Biggest abandonment risk. Make explain-back apply only to Claude-written PRs touching security/gates, and mock interviews at v0.9 and v1.0 only (plus one midway), or budget the time explicitly.
- **"No merge until all three right"** makes Claude both grader and builder; a stall blocks everything and the 125% rule trips from comprehension, not code. Add a 1-retry-then-merge-with-follow-up escape.
- Golden-set rule contradiction: golden batches 2/3 interleave with retrieval and prompt tuning, but "no iteration justified by results until 40 committed" is untestable; fine, but 2.3-2.5 ablation decisions (rerank enable) are results-driven. Clarify that retrieval ablation on the 15 questions is exempt.
- Spec amendments for cut 2/3 add a step at the moment the project is behind; pre-write them.
- Rolling rule needs an hours log; none exists. Add `docs/HOURS.md`.

**Verdict: YES-WITH-CHANGES.**
1. Fix weekday labels and shift gates to real dates (Mondays/Sundays); add Dec 22 and Dec 29 weeks at 0-3 h; state v1.0 as ~end of January.
2. Rebalance W2: golden batch 1 smaller, or demo slice Nov 16.
3. Re-budget overhead at ~12 h (explain-backs, interviews, logs) and raise Phase 4 to ~22 h; total ~115-120 h.
4. Trim ceremony: mock interviews at 3 points, explain-back for key PRs, with a one-retry escape.
5. Add an hours log and pre-written amendment PRs for cuts 2 and 3.


---

## r2-coach

# R2 Coach review of PLAN v0.3

## 1. Round-1 points
- Inverted ownership: FIXED. Prompt, tool descriptions, gate rules, budget logic, golden set, injection criteria, ADR decisions are now George's.
- No pass condition for "George reviews": PAPERED OVER. The gate exists, but Claude marks it (see 2).
- Golden set late / under-budgeted: PARTLY FIXED. Weekly batches from W2 and 15 retrieval questions in Phase 1 are good; the hours for 40 hand-verified cases are still not itemised (about 5-6 h).
- Agent budget/stop logic George's: FIXED.
- Spikes run by George: FIXED (5 h timebox).
- FINDINGS-LOG: FIXED, as a per-PR step.
- Lesson order and missing lessons: FIXED. Golden Sets moved to Phase 1; three lessons added. The "one Check-yourself question unprompted" rule is only self-reported.
- Mock interview per phase: PAPERED OVER. It exists and gates the tag, but Claude plays the interviewer and judges the misses.
- Statistics owned: FIXED (5.2 ADR on k=3 and the Wilson interval).
- Minor: staged-PR prediction FIXED; ADR Decision sections FIXED; plumbing-as-decision FIXED; time for explain-backs FIXED (about 6 h, looks light; see 3).

## 2. Is the explain-back enforceable?
Not as written. Claude writes the code, then writes the questions and marks the answers, and its own merge depends on the result. That is a grader with a stake in passing, and George has no reason to push back on a mark he cannot independently judge.

Smallest honest change, two parts:
1. **Answer key first.** Claude posts the expected answers as a PR comment before George writes his. Marking is then a comparison against a pre-committed key, not a post-hoc judgment, and George can dispute the key.
2. **Make "what breaks if X is deleted" a mechanical check.** George names the line or function, deletes it, runs the tests and pastes which test fails (or that none does, which is itself a finding: a gap in the tests). No Claude marking needed.

For mock interviews, use a fresh subagent with no repo context and only the postings, and record the verbatim answers in the FINDINGS-LOG so the misses are visible later.

## 3. New problems
- **Claude writes the tests for George's pieces ("Tests first" is unowned).** If Claude writes the RRF, limiter and coordinate-builder tests, Claude has specified the behaviour. Change: George writes the failing tests for his own pieces (hand-computed RRF ranks, the hypothesis limiter property, the Rent coordinate). Cheap, high signal.
- **Load.** About 20 h of George-written work plus reviews plus explain-backs in 10 h/week on top of Lynked is plausible but has no slack. Phase 1 and the 4 holiday weeks are tightest (Phase 5 at 5 h in the holiday week). The 125% rolling rule is the right backstop; make sure the "who took the cut" decision is George's, not Claude's.
- **Explain-back budget is light.** About 6 h covers roughly 19 PRs at under 20 min plus 6 mock interviews. A real answer key and a deletion experiment is about 25-30 min per Claude-written PR. Budget about 8-9 h.
- **Lessons are Claude-written and gate the phase.** Fine, but the lesson answers George gives should be committed, not just claimed.
- D3 pre-approval of Phases 0-1 is reasonable.

## Ready to start: YES-WITH-CHANGES
1. Answer key posted before George answers, plus the deletion experiment.
2. Fresh-context interviewer, verbatim answers logged.
3. George writes the tests for his own four pieces.
4. Raise the explain-back budget to about 8-9 h and the total to about 110 h.
