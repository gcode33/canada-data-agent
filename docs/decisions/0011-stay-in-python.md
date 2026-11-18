# 0011. Stay in Python: measure first, no rewrite

Date: 2026-11-18 · Status: Accepted (A8, approved by George 2026-11-18)

## Context
George asked whether parts of the agent should move to Go, Rust or TypeScript, or be optimised "to the highest level". An investigation (an Opus orchestrator with three sub-investigators) measured where one question's time goes, offline, and a Sonnet reviewer tried to break it (`docs/reviews/2026-11-17-stack-*.md`).

| Part of one question | Time |
|---|---|
| Whole question: Haiku eval runs (median of 761) / Sonnet dev transcripts (n=24) / one live Sonnet run | 9.8 s / 7.45 s / 26.7 s |
| Waiting on Claude (the model plus Claude Code's own work, `duration_ms`) | ~95% of a median Haiku run; ≤ 92% of the live run |
| Process start and teardown | ~0.5 s |
| Our tool server, start to ready (mostly `import mcp`) | 0.25 s |
| CLI start (`import canada_agent.ask`) | 0.28 s, ~0.2 s of it importing `mcp_server` for one constant |
| All tool calls, offline | ~33 ms |
| Live network inside tools (Voyage, StatCan) | ~2 s (one trace) |
| Runtime checks | < 1 ms |

All our own Python CPU is about 0.3–0.55 s of a 7–27 s question (1–4%), over 90% of it importing modules.

## Decision
- **No rewrite of any component, and no hand-written Go or Rust for speed.** The best case for all of them together is ~0.3 s of 7–27 s.
- **Optimise inside Python, once, where it's measurable.** These are A8 P1 and P2: drop a needless import (−0.2 s per CLI question) and lazy-load the tool server (50–70 ms). They land with the single A8 `src/` PR, so the gate is re-baselined once.
- **Prove gains with `make bench`:**
  - base and head run interleaved, n ≥ 30 after warm-ups, with compiled bytecode;
  - raw samples and the environment are committed to `docs/perf/`;
  - a change counts only if its bootstrap interval excludes zero. The intervals are 95% family-wise, Bonferroni-adjusted across the four measures (98.75% each), because four plain 95% intervals would flag a false change in an A/A run about 19% of the time. Batch medians drift 4–5% on their own.
- **If a CPU hotspot ever shows in a profile, the order is:**
  1. a Rust-backed library;
  2. one small benchmarked PyO3 extension;
  3. never a rewrite.

  Rust is already here where it pays: `pydantic-core`, `jiter`, `rpds-py`.
- **The biggest real lever is fewer model round trips** (~0.6–1.0 s per avoided tool call on Haiku). It changes pinned tool descriptions and may cost accuracy, so it needs its own pre-registered experiment and is not part of A8.

## Why not
- **The tool server in Go or Rust:** saves ~0.23 s of start-up at most. It means rewriting ~2,100 lines, re-pinning the tool snapshot, a re-baseline, and a second copy of the security rules.
- **Search in Rust:** ≤ 5 ms offline; live search waits on the network.
- **Porting the link filter (`links.py`) to TypeScript for the UI:** the review showed it *can* be done (0 mismatches over 30,000 fuzzed strings once `\w` became Unicode classes). But the runtime and the graders share it, and two copies of a security rule can drift apart. The UI imports the Python one instead (ADR 0010).
- **A long-lived `claude` session or an HTTP tool server to skip start-up:** this breaks per-question isolation and the per-run canary, and HTTP reverses ADR 0005.

## Consequences
- The interview answer to "why not rewrite it in Rust?" is a table, not an opinion.
- The live numbers rest on one trace. P3 adds per-event timestamps, so the U2 gate runs measure it properly.
