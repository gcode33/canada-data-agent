# Adversarial review: Phase 4 (PRs #19–#21) before merge

Date: 2026-11-06. Three independent Claude reviewers, read-only, ran in parallel with separate briefs:
- **Code correctness:** probes and bug hunting.
- **Eval integrity:** try to get wrong answers past the graders, and test the golden set and our claims.
- **Plan conformance and test quality:** done-when items, plus mutation testing on a copy of the repo.

**Verdict:** the first 24/24 showed the answers agreed with the snapshot, not that they were right. About 30 findings, with heavy overlap; all are fixed below or accepted with a reason. Fixes are in the last commits of #21.

## The three root causes
1. **The snapshot leaked the answer key.** It held only the golden series, so other real series answered "not a series", and the agent found the expected one by elimination in 3 of 20 runs.
   - Fix: whole tables from 2024 (15,410 series, 1.3 MB). `SNAPSHOT_MISS` now fails a case (`harness` grader), and requests before the window are a miss, not silent truncation.
2. **The graders were too loose.** 17 bypasses were demonstrated, among them:
   - `vector_id: 0` skipped grounding;
   - a coincidence in another month passed;
   - "650%" passed for 6.5 via the power-of-ten allowance, and "2025" satisfied a prose check for 1.985;
   - a refusal could state figures;
   - swapped multi-step answers passed;
   - uppercase-scheme URLs, bare domains, and links inside `description` passed.

   Fix: the graders were rebuilt (ADR 0007). Every expected value binds to its golden coordinate and periods at stored scale. Rescaling is allowed only in prose, with a scale word. There are new `conclusion`, `links` and `harness` graders. Each bypass is a test that must fail.
3. **CI couldn't fail.**
   - `canada-grade` always exited 0.
   - Transcripts weren't tied to the current question or prompt.
   - The "good runs" test was a tautology: mutants that broke `refusal` or the change maths survived.

   Fix: `--check` against a pinned manifest, a stale-transcript failure, provenance (git sha, dirty flag, prompt) stamped at record time, and history taken from the transcripts.

## Data and honesty fixes
- **Split leakage:**
  - Injection cases duplicated lookups, and one test case asked a dev value. Each injection case now has its own series.
  - Two series appeared in both dev and test. They were replaced, and the linter now refuses any series in both splits.
- **Ambiguous questions reworded:** CPI rent vs rental market rent; "groceries" vs the CPI food index; "typical" vs average earnings; the population source; CMHC average rent.
- **Injection** reported 1.0 with no poison applied. It's now n/a until 5.3.
- **The verifier** accepted values within the grading tolerance. It now requires an exact match up to stored precision.
- **"Offline except Claude"** wasn't true, because Voyage was still called. Snapshot mode now builds no StatCan or Voyage client.
- **Latency** came from `claude -p`'s internal timer (7.4 s). It's now wall-clock per run.
- **Degraded searches** weren't recorded; they are now in every history line. In-run recall is labelled agent search recall and never compared with the ablation rows.

## Accepted, not fixed (documented in ADR 0006/0007 and the README)
- **The retrieval set** shares tables with the golden test split. It was committed before search code and can't be changed without invalidating the ablation, so this is disclosed instead.
- **The verifier** shares judgement with the case author: the cases were built from the same CSVs. It guards transcription and maths, and that CSV and API agree. It can't tell whether a question maps to the right series; that's what the ambiguity pass is for.
- **`conclusion` is strict:** a correct answer that leads with the other entity fails.

## New tests that kill the surviving mutants
`tests/test_eval_pipeline.py` covers:
- `_tee` capture and `DATA_BACKEND` propagation;
- snapshot-mode isolation;
- `slim` keeping usage and dropping thinking;
- atomic writes and retrying failed recordings;
- stale and missing transcripts;
- `--check` exiting 1;
- every linter rule;
- every golden value recomputed from the snapshot;
- the window guard.
