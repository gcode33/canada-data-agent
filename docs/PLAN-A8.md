# Build plan: A8, web UI and performance (release v1.1.0)

Implements `docs/amendments/A8-web-ui-and-performance.md` v0.2. **A8 was approved by George on 2026-11-18, with decisions D1–D7 at their defaults:**
- D1: a public replay demo on GitHub Pages;
- D2: a "How it's tested" tab, no explorer;
- D3: no Rust experiment;
- D4: hand-written SVG charts;
- D5: release v1.1.0;
- D6: no re-recording;
- D7: show the attack runs.

Status of this plan: **draft v0.1 for George's approval.** Its own decisions are in §9.

The v1.0 plan's standing decisions still hold:
- Claude builds everything; George learns through the teaching track (PLAN D1, SPEC A7).
- No API billing, and no model in CI (PLAN D4, ADR 0009).

## 1. Ground rules

**PRs**
- **One step = one branch = one PR**, test-first, with a Conventional Commit title and a squash merge.
- A phase's PRs are stacked. George merges them in order with `~/projects/merge-canada-prs.sh`; background sessions can't merge.

**Reviews at the end of every phase** (George's standing rules, 2026-10-27 and 2026-11-06)
1. A code review of the phase diff against A8 (correctness and standards).
2. A 3-reviewer adversarial review (security/integrity, methodology/honesty, code/tests).
3. Fix everything. Record it in `docs/FINDINGS-LOG.md` and `docs/reviews/`. Show George the summary.
4. Then George merges.

U3's review is A8 §14's 2-reviewer release review.

**`src/` and the gate**
- **`src/canada_agent` changes in exactly one PR (U2.1).** Every other PR touches only `web/`, `perf/`, `docs/`, CI, the Makefile, or the judging file `gate.py` (U0.2). No other PR can change the agent or force a re-baseline.
- **No change to the system prompt or the tool descriptions** (A8 §5).
- **The held-out test split never runs.** CI's existing "test recordings never change" check stays green throughout.

**Usage limits:** a run stopped by the subscription's usage limit resumes with the same command. Runs already recorded are reused.

**Stop and ask George** only when:
- U2's regression check fails, because only George can supply `--accept-change "<reason>"`;
- a model run would be needed that this plan doesn't list;
- a step would contradict A8.

Everything else proceeds.

## 2. Before we start

| Who | What | When |
|---|---|---|
| Claude, on George's OK (P1) | Tag `w4` (v0.9 state) and `v1.0.0` at `d7cc29e` and push them, so v1.1.0 has a predecessor, the README's "v1.0" claims point at a real tag, and the provenance link has an anchor | Before U0 |
| Claude | Install Node 26 LTS locally (`brew install node@26`; Node 25 is installed now). CI uses `actions/setup-node` with 26 | U0.3 |
| Claude, on George's OK (P3) | Enable GitHub Pages with the "GitHub Actions" source (`gh api -X POST repos/gcode33/canada-data-agent/pages -f build_type=workflow`), and restrict the `github-pages` environment to `main` | U1.4 |
| George | Merge PR #25 (the approved spec), then this plan's PR, in that order | Now |

---

## Phase U0 · Contract and groundwork (0.5 day) → no tag

**U0.1 `docs/adr-0010-0011`**
- **ADR 0010:** the web UI and the replay-only demo.
  - The terms quote;
  - one streaming POST;
  - `web/` outside the fingerprint, with E2/E3 as the guard;
  - why not Next.js, a no-build page, Streamlit/Gradio, or a token.
- **ADR 0011:** stay in Python. The §6.1 budget, the per-option table, and the "Rust-backed library → PyO3 → never a rewrite" order.
- Updates the ADR index and §7 below.
- **Done when:** both ADRs are in `docs/decisions/README.md`, and every number they quote matches A8 §6.

**U0.2 `feat/gate-regression-check`**: `gate.py` only (a judging file: `agent_hash` is unchanged)
- `canada-gate baseline` first runs `judge(per_case(new study), outgoing baseline, usd=0)` with the gate's flip, mean-drop and leak rules.
  - It refuses on any reason unless given `--accept-change "<reason>"`.
  - It writes `replaces` (the old study hash) and `regression_check` (the verdict, the reasons and any accepted reason) into `baseline.json`.
  - With no outgoing baseline, it says so and passes.
- `check_evidence` accepts the new fields. A baseline whose `regression_check` failed without an accepted reason fails `verify`.
- **The receipt is refreshed with zero model runs.** A `gate.py` change alters `inputs_hash` but not `agent_hash`, so `make gate` reuses the recorded runs in `evals/runs/gate-…-<agent>/` and re-grades them.
  - **To prove it,** run `make gate` with `claude` removed from `PATH`. Any attempt to start a model run fails loudly.
- **Done when:** unit tests cover:
  - a flip blocks;
  - a mean drop blocks;
  - a leak blocks;
  - `--accept-change` records the reason;
  - the first baseline passes;
  - `verify` fails on an unaccepted failed check.

  In addition, `canada-gate verify` is green on the refreshed receipt, and the no-`claude` run is shown in the PR.

**U0.3 `feat/web-skeleton-and-events`**
- **The `web/` uv project:** its own `pyproject.toml` and `uv.lock`, depending on `canada-data-agent` through `[tool.uv.sources]` (path `..`, editable). It is **not** a workspace member.
- **`canada_web/events.py`:** the seven §9 pydantic models, each with a required `type: Literal[...]`, plus `validate_stream(events)` for the ordering rules.
- **`canada-web schema`** writes `web/schema/events.v1.json`; a test fails if the committed file is stale.
- **E2 test:** `web/` must not define `CITABLE_URL`-, `foreign_links`- or `run_events`-like code. It greps `web/` for their regex sources and function names.
- **CI:** a `web` job with no secrets: `uv sync --locked` in `web/`, ruff, pytest.
- **Done when:** ordering tests pass (good streams, plus each rule broken once); the schema check runs in CI.

**U0.4 `perf/bench`**: lives in `perf/`, outside `src/` and the fingerprint
- **`make bench REF=<git ref>`** measures four things interleaved, base (a temporary worktree at `REF`) against head, on one named machine:
  - `import canada_agent.ask`;
  - `import canada_agent.mcp_server`;
  - the tool-server handshake (start → `initialize` reply over stdio, snapshot backend);
  - in-process `search_tables`.

  It runs 3 warm-ups, then n = 30 per side, with bytecode compiled first (`uv sync --compile-bytecode`).
- **Output:** raw samples plus the environment (machine, OS, Python, lock hash, Postgres image, power state) in `docs/perf/<date>-<label>.json`, and a Markdown table of the medians and a bootstrap 95% interval of the difference.
- **Done when:** an A/A run (`REF=main` against main) is committed, and its interval for every measurement contains 0. This shows the harness doesn't invent improvements.

**Phase-end:** a code review only. U0 adds no user-facing surface, so there is no adversarial review here; the U1 review covers U0's contract and gate changes too.
- **Lessons:** [[Regression-Checked Baselines]], [[A/A Tests and Benchmark Noise]].

## Phase U1 · The public replay demo (2 days) → demo live

**U1.1 `feat/web-build-demo`**
- **`web/demo/allowlist.toml`:** the 24 dev runs with their category. 20 are `answer` or `refusal`, inject-01..03 are `attack_resisted`, and lookup-07 is `rejected`.
- **`canada-web build-demo` fails closed** if:
  - the grade verdicts are missing;
  - a run isn't on the dev split;
  - a run is off the allow-list;
  - an allow-listed run is missing.
- **For each run:**
  1. Re-wrap the slimmed events into stream shape.
  2. Run the imported `run_events` with a fixed clock and a dummy canary.
  3. Require the expected outcome: a pass for 23 runs, `ANSWER_REJECTED` for lookup-07.
- **`canada_web/convert.py`** is the one converter both modes use. It turns raw stream events plus the result into §9 events:
  - **summaries** are built from parsed fields only (`search_tables` → "5 tables", `get_table_dimensions` → "3 dimensions", `get_series` → "13 points, 2025-09 to 2026-09", or the error code);
  - **`arguments_text`** goes through `untrusted_text`, `foreign_links` redaction and a 200-character cap;
  - **`series`** comes from the parsed `get_series` payloads, emitted only after the result;
  - **links** are `linkable` by the imported `CITABLE_URL` plus "a tool returned it in this run";
  - **attack captions** come from `poison.parse` (goal and vector → a fixed sentence; the host is never used);
  - **`lookup-07`** becomes a fixed `run_failed`;
  - **provenance** uses the commit and its date, and "approximate pace" is spread over `wall_s`.
- **A scan runs `foreign_links()` over every emitted string;** any hit fails the build.
- **Outputs:**
  - `web/frontend/public/replays/<case>.json` and `index.json`. These are built, not committed: `.gitignore` excludes them, and CI and the Pages build create them.
  - `tested.json`, built from the committed `evals/gate-result.json`, `baseline.json` and `flakiness.json`, plus the README headline numbers, which are read from the README's table by a test-guarded parser.
- **Done when** all of these pass:
  - contract tests on all 24 bundles;
  - fidelity tests: the answer equals the recording's checked answer, and the chart points equal the recorded `get_series` points;
  - a determinism test: two builds produce identical bytes;
  - zero foreign links;
  - each fail-closed path tested;
  - a "failed run has no `series`, `answer` or tool text" test.

**U1.2 `feat/web-frontend-replay`**
- **The `web/frontend` scaffold:**
  - Node 26, Vite 8.3, React 19.3 and TypeScript 7.0, each pinned exactly, with `package-lock.json` committed;
  - `npm ci --ignore-scripts`;
  - ESLint bans `dangerouslySetInnerHTML` and any `statcan` URL pattern.
- **Design tokens** for light and dark themes. Contrast pairs (4.5:1 for text, 3:1 for chart lines) are checked by a Vitest test.
- **`events.ts`:** the hand-written union. A test checks its `type` names against the schema's.
- **`apply(event)`:** the reducer, plus a replay player with approximate pace that plays instantly under reduced motion.
- **Components:**
  - the question picker, with auto-play of `multi-04` on first visit (multi-step, with two 13-point series, so the first view shows steps *and* a chart; `multi-01`–`03` have single points);
  - the step list;
  - the answer card, with the "computed by the model…" line on change values;
  - the error panel, with fixed text for every code;
  - the run footer and the provenance banner.
- **Done when:**
  - Vitest drives the reducer over every bundle without error;
  - `<a>` renders only for `linkable: true`;
  - every error code has text;
  - the CI `web` job adds type check, lint, Vitest and `vite build` (`base` set to the repo path).

**U1.3 `feat/web-charts-and-a11y`**
- **The SVG chart:**
  - a line chart when a series has ≥ 3 non-null points, otherwise a value tile;
  - `null` is drawn as a gap labelled "suppressed";
  - the scalar factor is noted;
  - `role="img"`, with the summary sentence as `aria-label`, inside a `<figure>` with a `<figcaption>`;
  - a data table in `<details>`, with `<caption>` and `<th scope>`.
- **The "attack resisted" and "rejected by checks" views,** and the "How it's tested" tab built from `tested.json`, linking PR #24.
- **Accessibility:**
  - one hidden `role="status"` sentence per finished step;
  - focus moves to the answer heading or the alert;
  - the category header text from A8 §11.
- **CSP:** the `<meta>` tag (A8 §11 policy, without `frame-ancestors`) comes before any script in the built `index.html`.
- **Playwright tests, run against the built site:**
  - all 24 replays render;
  - a keyboard-only flow;
  - axe (tags `wcag2a`–`wcag22aa`, `target-size` on) finds zero serious or critical violations in every state;
  - zero `securitypolicyviolation` events;
  - a crafted fixture bundle, with `<script>` and `onerror` in `arguments_text` and the answer, stays inert text.
- **Done when:** all of the above run in the CI `web` job.

**U1.4 `ci/pages`**
- **`.github/workflows/pages.yml`, triggered on a push to `main` only:**
  - **build job** (`contents: read`): checkout, `setup-uv`, `setup-node`, `uv sync --locked` (root and `web/`), `make seed`-free `build-demo` (it needs no database), `npm ci --ignore-scripts`, `vite build`, the Playwright suite against the build, then `upload-pages-artifact`;
  - **deploy job:** `needs: build`, environment `github-pages`, permissions `pages: write` and `id-token: write` only, and only `actions/deploy-pages`.
  - Every action is pinned by commit SHA.
- **Pages setup** (P3).
- **README:** a demo link and one sentence at the very top.
- **Done when:** after George merges U1, the Pages URL serves the demo, and one Playwright run against the live URL shows all 24 replays with zero CSP violations. That URL check runs once, by hand, and is recorded in the PR.

**Phase-end:** the code review and the 3-reviewer adversarial review. U1 is merged by George; the demo goes live on that merge.
- **Lessons:** [[Server-Sent Events]] (the concept; it's used in U2), [[Content Security Policy and Trusted Types]], [[Testing Accessibility]], [[Static Sites on GitHub Pages]].

## Phase U2 · One agent PR and live mode (1.5 days) → no tag

**U2.1 `feat/agent-live-hooks`**: **the only `src/` PR in A8**
- **The changes** (P1–P5 and P8–P10, as specified in A8 §6.3), each with its own test:
  - P1: `SERVER_NAME` moves to `canada_agent/names.py`;
  - P2: lazy imports in the tool server;
  - P3: `t_ms`, `recorded_at` and `claude_version`;
  - P4: `on_step` after the canary check;
  - P5: the cancel watcher, tested by `test_cancel_kills_process_group` with a silent stub that has a child process;
  - P8: `migrations/` added to `INPUTS`, `config/` moved to `JUDGING`, and one `claude_version` required per receipt; CI's "flag changes to eval inputs" step covers both paths;
  - P9: `--` before the question, plus the `question="--version"` test;
  - P10: every `AskError` coded, with an AST test.
- **Checks before any recording:**
  - `make bench REF=main` shows improvements whose intervals exclude 0 for the P1 and P2 measurements;
  - all 418 existing tests, plus `canada-grade --check` for dev and test, plus the fresh-clone offline replay, still pass;
  - the U2 code review and adversarial review run **now, before recording.** P9 and P5 are security changes, and any later `src/` edit would mean recording again.

**U2.2 the re-baseline**, on the same PR, as its last commits
1. `make flakiness`: 24 dev × 5 = 120 Haiku runs.
2. `make baseline`: the U0.2 regression check against the v1.0 baseline. **If it fails, stop and report to George** with the flipped cases and runs; only he can accept.
3. `make gate`: 24 × 3 = 72 Haiku runs.
4. `canada-gate verify`, and commit the study, baseline, receipt and runs.
- **Budget:** 192 Haiku runs, ~35–40 minutes, ~$0.50 API-equivalent, on the subscription. D6 is "no", so the 24 dev Sonnet transcripts are not re-recorded.
- **Done when:**
  - the receipt passes and `verify` is green in CI;
  - the regression check is recorded as passed;
  - the new gate runs carry `t_ms`, `recorded_at` and `claude_version`.

  These new runs also provide the first real per-step timings, a small bonus for §6.1.

**U2.3 `feat/web-live`**
- **`canada-web serve`:**
  - binds 127.0.0.1 only, and refuses any other host and an `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` in the environment;
  - serves the built `dist/` with the A8 §10 header CSP;
  - offers `POST /api/ask` as the only API route.
- **The request path:**
  - **checks:** Host `127.0.0.1`, an exact `Origin`, `Sec-Fetch-Site: same-origin`, JSON content type, and the question rules from A8 §7 U1;
  - **concurrency:** a second request gets 409; the lock is released only after the process group is gone;
  - **worker:** a worker thread runs `ask(on_step=…, cancel=…, capture=…)`, feeding an async generator through `loop.call_soon_threadsafe`;
  - **conversion:** the shared `convert.py` turns steps and, after the checks, series and the answer into §9 events;
  - **cancel:** the generator's `finally` sets `cancel`, and the lifespan shutdown sets `cancel` and joins.
- **The live front end:**
  - a text box;
  - a `fetch` stream with a ~30-line SSE parser (no dependency);
  - Stop calls `abort()`;
  - focus handling when Stop disappears.
- **Tests,** using a stub `claude` on `PATH` that replays recorded stream-json slowly and spawns a child:
  - every header check rejects;
  - 409;
  - abort kills the group;
  - shutdown kills the group;
  - an API key in the environment refuses to start;
  - a failed run has no `series` or `answer`;
  - the Playwright live flow against the stub.
- **Done when:** the above pass in CI, and `make live-web` answers one real question locally: 1 Sonnet run, recorded in the PR with its trace.

**Phase-end:** the code review and adversarial review of U2.3. U2.1's review already ran before recording. Then George merges U2.
- **Lessons:** [[Argument Injection]] (written 2026-11-17), [[Cancelling Subprocesses]], [[Localhost Server Hardening]] (builds on [[DNS Rebinding and Localhost Security]]).

## Phase U3 · Polish and release (1 day) → `v1.1.0`

**U3.1 `docs/a11y-and-readme`**
- **Accessibility pass:**
  - Claude runs and records the keyboard-only pass in `docs/a11y.md`;
  - **George does a 20-minute VoiceOver pass** with the checklist in that file (P4), and Claude records his notes.
- **README:**
  - a "Try it" section: the demo link, plus a GIF made from a Playwright video of one replay;
  - a live-mode quickstart with the terms warning;
  - §6.1's latency budget, in short.
- **Done when:** `docs/a11y.md` has both passes, and the README GIF exists and is under 5 MB.

**U3.2 the release review**
- The A8 §14 review: 2 reviewers (security, honesty) over the whole A8 diff.
- Fix the findings and log them in `docs/reviews/`.

**U3.3 `docs/v1.1-release`**
- `FINDINGS.md` gains an A8 section (what the reviews caught, including the argument-injection bug).
- The claims table gains the A8 §3 rows.
- After George merges, Claude tags and pushes `v1.1.0` (P1).
- Check-yourself questions for the A8 lessons go in the vault.
- **Done when:** the tag is pushed, Pages serves the release, and the README claims link to evidence.

---

## 3. Budget

| Phase | Build days | George's review | Model runs |
|---|---|---|---|
| U0 | 0.5 | ~1.5 h | 0 (the receipt refresh is proven model-free) |
| U1 | 2 | ~4 h | 0 |
| U2 | 1.5 | ~4 h | 192 Haiku (study + gate) + 1 Sonnet (live smoke) |
| U3 | 1 | ~2 h + a 20-minute VoiceOver pass | 0 |
| **Total** | **5** | **~12 h** | **193** (~$0.55 API-equivalent, on the subscription) |

Reviewer agents run inside Claude's budget, not George's hours. George reads their summaries.

## 4. Order and dependencies

```
U0.1 ─┐
U0.2 ─┼─► U1.1 ─► U1.2 ─► U1.3 ─► U1.4 ─► [review, George merges: demo live]
U0.3 ─┤                                          │
U0.4 ─┘                                          ▼
                    U2.1 ─► [review] ─► U2.2 (192 runs) ─► U2.3 ─► [review, merge]
                                                                     │
                                                       U3.1 ─► U3.2 ─► U3.3 (v1.1.0)
```

U0.2 must merge before U2.2, so the regression check exists when the baseline is replaced.

## 5. Cut lines (in order, if the budget runs out)

1. Dark theme → light only.
2. The "How it's tested" tab → a README link to the evidence.
3. The attack-resisted replays (D7 → no). Keep lookup-07.
4. The manual VoiceOver pass. The claim becomes "automated accessibility checks" only.
5. **Stop after U1:** release v1.1.0 as the public demo only. U2 (the agent PR and live mode) becomes v1.2.

Each cut is George's call; none is taken silently.

## 6. Risks specific to the build

| Risk | Mitigation |
|---|---|
| The regression check fails after the `src/` bundle | Stop; show George the flipped cases. If a P-item caused it, revert that item and re-record. Never accept silently |
| The usage limit hits mid-recording | Resume with the same command; the runs already recorded are reused |
| The Pages build differs from local | The Playwright suite runs inside the Pages build job, plus one check against the live URL |
| The `claude` CLI changes its option parsing | P9's stub test plus the live smoke test; `claude_version` is pinned per receipt (P8) |
| Node or npm supply chain | Exact pins, a committed lockfile, `--ignore-scripts`, and only the dependencies the plan lists (React, Vite, TypeScript, ESLint, Vitest, Playwright, axe) |

## 7. ADR register (additions)

- **0010:** the web UI, the replay-only public demo, and `web/` outside the fingerprint (U0.1).
- **0011:** stay in Python: the latency budget and the rewrite decision (U0.1).

## 8. Out of scope

- Everything in A8 §5.
- SPEC §5's "later" list.
- Prompt and tool-description changes, including the round-trip experiment in A8 §6.5.
- Re-recording the dev transcripts (D6).

## 9. Decisions for George (approving this plan approves these defaults)

| # | Question | Default | Why |
|---|---|---|---|
| P1 | May Claude create and push tags: `w4` and `v1.0.0` at `d7cc29e` now, and `v1.1.0` after the release merge? | **Yes** | v1.0.0 was never tagged. The README, A8 and the demo all refer to it, and a release needs a predecessor |
| P2 | Adversarial reviews at the end of U1 and U2 (3 reviewers), plus the 2-reviewer release review at U3? | **Yes** | Your standing rule since 2026-11-06. U0 gets a code review only, because it adds no user-facing surface |
| P3 | May Claude enable GitHub Pages and set its environment rule with `gh api`? | **Yes** | It's needed for D1. It publishes the demo only after you merge U1 |
| P4 | Will you do the 20-minute VoiceOver pass at U3? | **Yes** | Automated tools miss screen-reader problems. If no, cut line 4 applies and the claim is softened |
