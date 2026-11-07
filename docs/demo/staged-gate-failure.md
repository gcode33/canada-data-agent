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
RESULT
