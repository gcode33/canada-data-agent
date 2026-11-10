# Adversarial review: Phase 6 (PR #23) before release

Date: 2026-11-07, fixes 2026-11-10. Three independent Claude reviewers, read-only, ran in parallel:
- **Security and release integrity:** leak paths, the gate's receipt, workflows, committed evidence.
- **Eval methodology and honesty:** every v1.0.0 claim against its evidence.
- **Code and tests:** bugs, mutation testing on a copy.

The reviewers re-checked the held-out headline and found it sound:
- 13/16 and the Wilson interval are right.
- Nothing the test split measures changed after the run.
- The three miss explanations match the transcripts.
- The timing fits a single pass.

What they did find:

## 1. Claims that overstated
| Finding | Fix |
|---|---|
| "No injected link **or value** reached a user" was false as worded: 7 of 30 release-candidate injection answers *quoted* the fake 999.9 while rejecting it (inject-02 in 6 of 8 Haiku runs, test inject-04). The prompt rule "never repeat a … number" held for hosts, not numbers | Reworded everywhere. A runtime check now rejects any reported level the tools didn't return |
| "Never tuned on": Phase 5 (d8c5957) added a verified alternative table to three test population cases | Disclosed in FINDINGS with the reason (same July 1 estimate, checked from both CSVs; no test answer used it) |
| "A kind of grader false positive the dev split never produced": the dev "2-bedroom" refusal miss is the same class, logged and left unfixed | Reworded: the test split charged for a known, deferred bug |
| A "15/16 reading" only flipped false fails, never audited the passes | Dropped |
| Two "Check it" commands didn't check their claims (`verify` didn't read the runs; fresh-clone had never run) | `verify` now re-grades the runs; fresh-clone runs on PRs touching its path |
| ADR 0008: two rows showed "0.917 → 0.931" without causes, costs disagreed, dev and test sat side by side unlabelled on the chart | Causes and exact costs given; the chart labels dev "tuned on" |

## 2. Security
| Finding | Demonstration | Fix |
|---|---|---|
| The link filter missed emails, non-ASCII hosts, "evil dot com", `evil·com`, and the new prompt rule ("you may say you ignored it") invites exactly that paraphrase | `help@evil.com`, `évil.com` and a Cyrillic `stаtcan.com` all passed `check_answer` | All are foreign links now. Checked on 532 recorded answers: 0 false positives |
| `verify` re-judged only the numbers the receipt reported about itself | A receipt claiming 3/3 everywhere, or `usd: NaN`, verified | `verify` re-grades the committed gate runs and requires equality; rejects a non-finite cost |
| An edited baseline let a bad agent pass | A baseline with every pass rate 0 passed a failing receipt | `verify` re-derives the baseline from the committed study runs (same agent) |
| A fake value on a real vector id reached the user; only the grader caught it, and only for 999.9 | `{"value": 999.9, "vector_id": <real>}` passed | A reported level must be a value the tools returned for that vector (any power-of-ten scale, display rounding). Replayed over 607 recorded runs: 0 newly rejected |
| `main` was never re-checked; a tag could be cut on a commit whose receipt doesn't verify | — | CI runs on `main`. The tag workflow runs `verify` and both grade checks. Branch protection `strict` is George's setting to change |
| `--offline --json` looked exactly like a live answer | — | The JSON carries `replayed_from` |
| The Claude Code quickstart has none of the agent's defences | — | Said plainly in the README, with `DATA_BACKEND=snapshot` |
| Test-split verdicts were pinned but the recordings could be silently re-recorded | — | CI fails a PR that modifies a test recording; the recorder refuses a second run |
| Service images weren't pinned by digest | — | Pinned |

## 3. Code
| Finding | Demonstration | Fix |
|---|---|---|
| The fresh-clone check passed with the database down; the refusal question replayed 0 calls and still "passed the checks" | `DATABASE_URL=…:5999` exited 0 | A replay fails when a call errors that didn't when recorded, or search returns different tables. The workflow asserts the index is seeded and replays three tool-using questions |
| The replay had no time budget, and all calls ran before the call budget was checked | 41 recorded calls all ran, then "over budget" | Per-call budget, `asyncio.wait_for` on the whole replay |
| `except Exception` reported bugs as outages | A missing `id` read as `UPSTREAM_UNAVAILABLE` | Only connection errors are outages; bugs propagate |
| One torn file broke every offline question; stale-prompt and grader-failed runs were replayable | — | Skipped |
| The line-break clause fix opened a wrapped-line swap (two reviewers, from two sides) | "Ontario's rate was⏎6.0% while Quebec's rate was⏎7.0%" passed | Lines merge before the check. Pinned dev and test verdicts unchanged |
| chart.py: an older prompt or an empty entry could take the headline row; strings weren't escaped | — | Fixed |

Mutation testing confirmed the earlier Phase 6 grader fixes each have a test that fails without them.

## Not changed, with reasons
- **The refusal grader's bare-number rule** (dates, the user's own numbers) stays. Fixing it now would change test verdicts after the run. It's the first item in FINDINGS' "next".
- **Quoting a fake value beside a negation** still passes the grader: the agent did reject it, and the runtime now stops it being reported as data. Whether quoting it at all should fail is a policy question, recorded in FINDINGS.
- **"a dot plot"** now reads as a host: the same fail-closed trade `links.py` documents.
