# 0007. Deterministic graders over recorded transcripts; no LLM judge in v1.0

Date: 2026-11-05, revised 2026-11-06 after the Phase 4 review · Status: Accepted

## Context
The golden set needs grading that's cheap enough for every PR and that can't be argued with. SPEC 10.3 lists the checks; the LLM judge moved to v1.1. The first version of these graders passed 24/24, and an adversarial review then got wrong answers past them in 17 different ways. This version closes each one, and each is a test that must fail (`tests/test_graders.py::BAD`).

## Decision
Ten graders in `src/canada_agent/evals/graders.py`, pure functions of a transcript and its golden case:

| Grader | Fails when |
|---|---|
| `completed` | the run errored or went over budget, or there's no structured answer |
| `harness` | any tool returned `SNAPSHOT_MISS` (SPEC 10.6) |
| `refusal` | an unanswerable case wasn't refused with no values, a refusal states figures, or an answerable case was refused |
| `trajectory` | more than 8 tool calls, or any invalid-argument or schema-validation error |
| `links` | any link or domain anywhere in the answer (any case, any field) isn't an exact StatCan table URL |
| `right_series` | an expected series (table **and coordinate**) was never fetched |
| `values` | no answer value has the expected label, **the golden series' vector id, the golden periods**, and the expected number **at stored scale** within tolerance; or that number isn't stated in the prose |
| `grounded` | any answer value doesn't follow from points `get_series` returned in the run (recomputed at stored scale), or a level cites no series |
| `citations` | an expected table isn't cited |
| `conclusion` | (multi-step) the first sentence doesn't lead with the right entity, or a number is given for the wrong entity |

- **Rescaling is allowed only in prose, only with a scale word,** matched to the precision written ("5.71 million" ≈ 5,710,598). The answer block must use StatCan's stored scale, so "650%" for 6.5 fails.
- **Signs may be carried by words** ("fell by 0.6 points" for −0.6).
- **A missing or stale transcript fails.** Stale means the question or prompt version changed since recording.
- **Injection cases count only once their run was poisoned** (PLAN 5.3). Until then they report n/a.
- **CI runs `canada-grade --check`,** which exits 1 if any verdict differs from the pinned `evals/grades/dev.json`. A grader change, a stale transcript or a new failure therefore needs a reviewed manifest update.

## Known limits (accepted, in the README)
- `conclusion` is strict: a correct "Quebec was lower than Ontario" fails because it leads with the other entity. It errs toward failing a good answer.
- The prose check confirms the number is stated, not every claim around it. A wrong adjective ("rose" for a fall) next to the right magnitude isn't caught.
- `vector_id: 0` is still allowed for an *extra* cross-series change (a gap between two entities). Every *expected* value must bind to its golden series.

## Why not
- **An LLM judge:** non-deterministic, costs a model call per case, and needs its own validation set (v1.1).
- **Exact string matching:** brittle to harmless wording.
