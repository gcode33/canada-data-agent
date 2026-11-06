# 0007. Deterministic graders over recorded transcripts; no LLM judge in v1.0

Date: 2026-11-05 · Status: Accepted

## Context
The golden set needs grading that's cheap enough for every PR and that can't be argued with. SPEC 10.3 lists the checks; the LLM judge moved to v1.1.

## Decision
Seven graders in `src/canada_agent/evals/graders.py`, pure functions of a transcript and its golden case:

| Grader | Fails when |
|---|---|
| `completed` | the run errored or went over budget, or there's no structured answer |
| `refusal` | an unanswerable case wasn't refused (with no values), or an answerable one was |
| `trajectory` | more than 8 tool calls, or any `BAD_ARGUMENTS` error |
| `right_table` | an expected table was never fetched with `get_series` |
| `values` | an expected value isn't in `answer_values` (same label, within tolerance), or that number isn't in the prose |
| `grounded` | a value's vector id or periods don't match points `get_series` returned in the run, or a change doesn't recompute from those points |
| `citations` | any URL, in `source_urls` or the prose, isn't on `www150.statcan.gc.ca`, or the expected table isn't cited |

- **Presentation scale is allowed:** "5.71 million" for 5,710,598 persons, or dollars for cents. A value matches if some power-of-ten rescaling is within tolerance.
- **A missing transcript is a failure**, never a skip.
- Search recall@5 inside the run is reported as a metric, not a pass/fail check: the agent may still pick the right table from a weaker ranking.
- **Tests:** 12 corruptions of a real transcript, each caught by exactly the grader it targets, plus the real recorded runs.

## Consequences
- `grounded` and `values` overlap on purpose. A wrong number usually fails both, and a right number from the wrong series fails only `grounded`.
- The scale allowance could pass a value that's off by exactly a power of ten *and* consistently written that way in the prose. Accepted: `grounded` still checks it against the points.

## Why not
- **An LLM judge:** non-deterministic, costs a model call per case, and needs its own validation set (v1.1).
- **Exact string matching of answers:** brittle to harmless wording changes.
