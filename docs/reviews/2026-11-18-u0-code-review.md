> Phase U0 code review (PLAN-A8), by a Claude Opus 5.5 reviewer, read-only, 2026-11-18. How each finding was handled is in `docs/FINDINGS-LOG.md` (2026-11-18).

## U0 code review: `origin/docs/plan-a8..origin/perf/bench`

I found 1 blocking issue, 7 should-fix issues and some nits. Root `uv run --frozen pytest` passes (433), and `cd web && uv run pytest` passes (23). Ruff and format are clean in both projects, and `canada-web schema --check` is up to date. My probe scripts are in `~/.claude/jobs/e82029df/tmp/u0-review/` (`probe_gate.py`, `e2.py`).

### Blocking

**1. The baseline writer and `verify` work out the regression reasons differently, so a legitimately accepted regression fails `verify`.** `src/canada_agent/evals/gate.py:303-304` and `:447`
- `cmd_baseline` judges two inputs:
  - the new cases from `flakiness.json`, which was dumped with `sort_keys`, so the cases come in id order;
  - the old baseline's stored `pass_rates`.
- `check_regression` judges `per_case(...)`, which comes in golden-file order, against a re-graded old study.
- The golden dev order is not sorted (`lookup-01..07, compare-01..`), and `judge` lists flip and leak reasons in the order it iterates.
- Evidence from `probe_gate.py`, with flips on lookup-07 and compare-01:
  - writer: `['flip: compare-01 …', 'flip: lookup-07 …']`
  - verifier: `['flip: lookup-07 …', 'flip: compare-01 …']`
  - `equal: False`
- So George's `--accept-change` at the U2 re-baseline gets "the baseline's regression check doesn't match the committed runs" whenever there are 2 or more per-case reasons.
- The two sides can also diverge if the old study re-grades differently from what is stored, e.g. a dev case added since the old study grades as 0 in the old runs. That also dilutes the mean-drop rule.
- **Fix:**
  - In `cmd_baseline`, use `old = baseline_from(per_case("dev", <outgoing study runs via study_dir>))` and `new = per_case("dev", <new study runs>)`. PLAN U0.2 literally says `judge(per_case(new study), …)`.
  - Iterate `sorted(cases)` in `judge`.
  - In `check_regression`, compare `sorted(check["reasons"]) != sorted(expected)`.
  - Add a test with two flips in non-sorted golden order.

### Should-fix

**2. The first baseline can never pass `verify`, which contradicts U0.2.** `gate.py:311-315` vs `:440-442`
- With no outgoing baseline, `cmd_baseline` writes `replaces: None`, and `check_regression` then rejects it with "doesn't name the baseline it replaced". `probe_gate.py` shows exactly this.
- U0.2 says "With no outgoing baseline, it says so and passes". The command also prints nothing about it.
- `test_with_no_outgoing_baseline…` only tests `regression_reasons`, so the "first baseline passes" Done-when item isn't really covered.
- **Fix:** either have the writer record `replaces: None, passed: True` explicitly and let `check_regression` accept that (only when `reasons == []`), or refuse when there is no outgoing baseline. Add an end-to-end test: `adopt(...)` with `outgoing={}`, then `check_regression` returns `[]`.

**3. Pointing `replaces` at the new study itself hides any flip or mean drop, and the docstring doesn't cover this.** `gate.py:440-447`
- `probe_gate.py` case 3 returns `[]` for `replaces.from_study_agent_hash == baseline.from_study_agent_hash`.
- The docstring only admits that it can't prove *which* earlier baseline was in force. A self-reference is trivially detectable.
- **Fix:**
  - Reject `old["from_study_agent_hash"] == baseline["from_study_agent_hash"]`.
  - Better: CI already checks out with `fetch-depth: 0`, so when `baseline.json` changed, compare `replaces` with `git show origin/main:evals/baseline.json`.

**4. The `PRE_A8_BASELINE` exemption is keyed on a hash anyone can type in, and `verify` never recomputes `agent_hash`.** `gate.py:370-388`, `:437`
- This hole predates U0, but the exemption depends on it. `check_receipt` checks `inputs_hash`, but the receipt's `agent_hash` is only a claim.
- So someone could change `src/`, keep the v1 receipt, baseline and runs (all `51acd051…`, no `regression_check`), bump `inputs_hash`, and `verify` passes.
- **Fix:** in `check_receipt`, add `if result.get("agent_hash") != agent_hash(): problems.append(...)`. That pins the exemption to the v1 agent tree only. I checked: the current tree's agent hash is `51acd051a15f`, the same as the receipt, so this stays green today.

**5. The E2 test only catches verbatim copies.** `web/tests/test_imports_not_copies.py:10-27`
- Using its own matching (`e2.py`), these are all MISSED:
  - a Python copy of the URL regex with a tiny variation (e.g. `pid=(\d{8})\d\d`). Neither the full pattern nor `"statcan.gc.ca"` is a substring, because the regex writes `statcan\.gc\.ca`;
  - `def _foreign_links(`;
  - `foreign_links = lambda …`.
- It also scans only `web/src`, not all of `web/`.
- **Fix:**
  - Match `re.search(r"statcan", text, re.I)`.
  - Match names with `r"\b_?(run_events|foreign_links|check_answer|check_grounded|untrusted_text|series_values|contains_canary)\s*[=(]"` plus `def\s+_?<name>`.
  - Scan all of `web/` except `tests/`, `.venv/` and `node_modules/`.
  - Add a self-test that feeds it known copies.

**6. Several `validate_stream` rules are never exercised.** `web/tests/test_events.py:87-107`
- Untested: "started twice", "finished twice", "series for step … which never finished", and a duplicate `run_started` in mid-stream.
- Deleting any of those checks leaves the suite green, which misses the U0.3 Done-when ("each rule broken once").
- **Fix:** add four parametrize rows.

**7. The interval level in the docs contradicts the code.**
- `perf/bench.py:147` uses Bonferroni 98.75%.
- ADR 0011 (in this same diff, "a change counts only if its bootstrap 95% interval excludes zero"), A8 §6.3 and PLAN U0.4/P1/P2 acceptance all say 95%. The deviation is recorded only in PR #30's body.
- It is defensible, but it makes P1/P2 acceptance stricter.
- **Fix:** amend the ADR 0011 bullet and add a deviation note in PLAN-A8 U0.4.

**8. Cleanup in `perf/bench.py:152-171` can leave stray worktrees.**
- Both `git worktree add` calls run *before* the `try`. If the second fails (e.g. a bad `HEAD_REF`), the base worktree stays registered after TemporaryDirectory deletes it.
- In `finally`, a failing `remove` raises, which skips the second removal and hides the original error.
- **Fix:** add each worktree inside the `try`, appending it to a `created` list. In `finally`, remove each one in its own `try`, then run `git worktree prune`.

### Nits
- `tests/test_gate.py`: `test_the_cost_cap_does_not_apply_to_a_study` is identical to `test_a_steady_study_does_not_regress` and can't fail. Monkeypatch `MAX_USD=-1` to give it meaning, or delete it.
- `bench.py:79`: `int(0.00625*4000)` is 24, not 25, so the tails are asymmetric by one sample. Use `round()`.
- `gate.py:444`:
  - `int(old.get("k") or 0)` crashes on a non-numeric `k` and allocates without limit on a huge one; bound it to 1..20.
  - A whitespace-only `accepted_reason` satisfies `verify`; use `.strip()`.
- `events.py`:
  - `validate_stream` doesn't tie a `series` to a step whose tool is `get_series` with `ok=True`.
  - `ok` and `error_code` consistency is not enforced (`ok=True` with a code, or `ok=False` with null).
  - `refusal` runs aren't tied to `answer.refused`.
  - Spec-level: `category` in `run_started` can't be known at the start of a live run. Worth noting before U2.
- `bench.py:96`: `safe(...).splitlines()[0]` raises IndexError if `pmset` prints nothing. On Linux, `sysctl` returns "unknown", so the `or platform.machine()` fallback never fires.
- The A/A run is commit 9f0b8d9 against itself, not "REF=main against main" as PLAN says. That is fine as an A/A, but say so in the `.md`.
- `probe.handshake` times start until `list_tools` answers, not until the `initialize` reply as PLAN says. This is disclosed in the PR; align the PLAN wording.

### Checked and fine
- **`judge` reuse:** `regression_reasons` reuses `judge` with `usd=0`, so the leak and invalid rules apply and there is no cost cap.
- **Forgery tests:** forged `reasons`, `passed` and `replaces` are caught by re-deriving from runs, and the tests would fail if those checks were removed.
- **`PRE_A8_BASELINE`** matches the committed baseline, and the receipt refresh changed only `inputs_hash`.
- **No defaults:** every field is required with no defaults, and the test walks every `$defs` entry. `extra="forbid"` is set and models are frozen.
- **Field shapes:** `product_id` is 8 digits and `Tool` is derived from `canada_agent.ask.TOOLS`.
- **`run_started.attack`:** the deviation is recorded and enforced (present only on `attack_resisted` runs).
- **Content ordering:** `validate_stream` correctly rejects a series or answer before any step event, and a failed run that shows content. Terminal uniqueness and dangling steps also follow §9.
- **Schema freshness** is checked both in CI (`schema --check`) and in pytest.
- **`web/` project:** it is not a workspace member, has its own lock, uses an editable path source, sits outside `INPUTS`, and leaves the root pyproject and lock untouched.
- **CI web job:** SHA-pinned checkout and setup-uv, the same pins as the other jobs, the workflow-level `contents: read`, and no secrets.
- **Ruff** config is identical between root and `web/`.
- **ADRs 0010/0011:** numbering matches A8 and the PLAN §7 register, both are in the README index, and the §6 numbers match apart from finding 7.
- **Bench design:** interleaving and the fresh-worktree design are sound. The Bonferroni maths (1 − 0.05/4) and the 19% figure (1 − 0.95⁴) are correct.
- **Probe timing** excludes the probe's own imports and the warm-up search, and the offline env sets an empty Voyage key and `POISON`.
