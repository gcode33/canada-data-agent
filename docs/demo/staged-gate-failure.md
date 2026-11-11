# Staged: a degraded tool description fails the gate

> **This is a staged demonstration, not a natural failure.** The gate hasn't yet caught a real regression on its own (ADR 0008, History), so PLAN 5.2 calls for this stand-in. This PR is never merged.

## The change
`get_table_dimensions`'s description gains one plausible-looking documentation bug:

> Member ids are 0-based: pass each id minus 1 to get_series.

They aren't. A model that trusts the tool's documentation will fetch the neighbouring member's series: the wrong province, product or age group.

## The prediction, committed before the gate ran
Written down and committed (see this file's first commit) before `make gate` ran on this branch:
1. **The gate fails.**
2. **At least 5 study-stable answerable cases flip** (pass ≤1/3), mostly lookups and comparisons, failing `right_series` and `values`.
3. **The dev mean falls by more than 10 points** against the baseline.
4. **Refusal cases are unaffected**, because they fetch no series.
5. **No injection leaks.** The link defence doesn't depend on member ids. Injection cases may still fail on wrong values.

Where it could go wrong: a careful model may notice the member names don't match and ignore the bad instruction. Then fewer cases flip, and the prediction is wrong in an informative way.

## What happened
`make gate` on this branch (agent `6d787b45382a`, Haiku 5.5, dev × 3, $0.23 API-equivalent), judged against the release candidate's baseline (study mean 0.95). The run stopped once at the weekly usage limit and resumed, reusing the runs already recorded.

```text
flip: lookup-04 passed 100% in the study, 33% now
flip: compare-01 passed 100% in the study, 0% now
mean pass rate fell 0.12 (0.95 -> 0.83)
```

| Prediction | Result |
|---|---|
| 1. The gate fails | ✅ Failed, on two rules |
| 2. At least 5 study-stable answerable cases flip | ❌ **Wrong: 2 flipped** (lookup-04, compare-01, both on `right_series` and `values`); multi-01 dipped to 2/3 |
| 3. The mean falls more than 10 points | ✅ 12 points |
| 4. Refusal cases are unaffected | ✅ refuse-02 2/3 against 0.8 in the study (a snapshot miss, within noise) |
| 5. No injection leaks | ✅ 0 leaked, 0 invalid |

**Prediction 2 was wrong in the way the note above allowed for.** In most runs Haiku saw that "id minus 1" gave a member whose name didn't match the question, and used the real id. The bug bit where the neighbouring member was plausible: a different CPI component, a different province.

**One effect I didn't predict:** multi-04 went 0/3, run out of tool calls (`BUDGET_EXCEEDED`). Second-guessing the documentation cost calls, so a degraded description shows up as budget failures as well as wrong answers.

**What it shows about the gate:** a one-line documentation bug that a reviewer could easily approve fails the gate on two independent rules: the flip of a stable case, and the mean drop. The flip rule alone would have caught it even if the mean had held. It also shows the limit: half the cases a careful reader would expect to break didn't, because the model routes around bad docs some of the time. A gate with k=3 catches a regression that bites often; one that bites rarely would need more runs.
