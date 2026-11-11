# Canada Data Agent & Eval Lab

An AI assistant that answers questions with **live Statistics Canada data** and cites every number, plus an **eval suite that blocks any pull request that makes it worse**.

Status: in progress (PLAN Phase 3). It finds the right table and answers live questions end to end today:

```text
$ canada-ask "How much did rent go up in Ontario last year?"
Ontario's rent CPI rose 2.9% over 2025 (December 2024 index 158.8 to December 2025 index 163.4). [...]
I took "last year" to mean calendar year 2025 [...]
Source: https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810000401
```

## How it works
- **Agent:** `canada-ask` runs Claude through `claude -p` with this project's MCP server as its only tools (ADR 0009).
- **Tools:** a stdio MCP server (`canada-mcp`) with `search_tables`, `get_table_dimensions` and `get_series` over the StatCan WDS API: host allowlist, rate limit, retries, cache, machine-readable error codes, a 4k-token result cap, and pinned tool descriptions (ADR 0005).
- **Table search:** 584 in-scope tables, each with a short card.

| Method | recall@5 | MRR |
|---|---|---|
| Full-text (Postgres `ts_rank`) | 0.33 | 0.22 |
| Vector (Voyage `voyage-4`, exact cosine) | 0.67 | 0.49 |
| Hybrid (weighted RRF) | 0.73 | 0.41 |
| **Hybrid + Voyage `rerank-2.5`** | **0.80** | **0.63** |

Measured on a 15-question retrieval set committed before any search code. Every variant tried, including the failures, is in [`evals/ablation.md`](evals/ablation.md).

> **Full-text is not BM25.** Postgres `ts_rank` weights how often and where a word appears in a document. It has no corpus-wide term weighting (IDF) and no length saturation, so a rare word counts no more than a common one. That's one reason vector search beats it here.

**Limits of the checks.** The canary catches case and spacing tricks in answers and tool arguments, but encoded forms (such as base64) get through: it's a tripwire, not a guarantee. Citations must exactly match a URL a tool returned in that run. These checks show an answer came from the tools; correctness is measured separately by the golden set.

## The eval gate
Every PR that changes the agent must carry a passing gate receipt (`evals/gate-result.json`). `make gate` runs the 24 dev golden cases × 3 against a committed snapshot of StatCan data. CI re-judges the receipt against the committed baseline and checks it matches the PR's exact code, prompt, golden set and data (ADR 0008). The baseline comes from a separate k=5 flakiness study, never from the gate run it judges.

| | Dev pass rate | Notes |
|---|---|---|
| Gate (Haiku 5.5, k=3) | 0.92 | passed: 0 injection leaks, no flips; $0.19 API-equivalent per run |
| Flakiness study (Haiku 5.5, k=5) | 0.89 | 18 stable, 5 unstable, refuse-02 fails 5/5; $0.0027 per run |
| Recorded runs graded in CI (Sonnet 5.5, k=1) | 23/24 | pinned verdicts, `canada-grade --check`; lookup-07 refuses an answerable question |

How the study number moved: 0.78 as first graded → 0.88 after grader false positives were fixed → 0.93 after verified alternative series and a reworded question → **0.89 on fresh runs** after the review tightened the link filter and injection grader. The earlier numbers were taken on the same runs the graders were fixed against; the last one wasn't.

These are dev numbers, which the agent was built against. The held-out test split runs once, at the release tag.

**Weaker search than production:** in snapshot runs the agent's own queries mostly have no recorded vector and there's no live rerank, so search falls back to full-text. 19 of 20 searches in the recorded runs were flagged `degraded_retrieval`. These scores measure the agent on worse search than a live run gets.

**What it can't prove:** the receipt shows the numbers are consistent and pass today's rules, not that the runs happened. The transcripts under `evals/runs/` are the evidence.

**First real bug found:** the flakiness study, not the gate, caught Haiku leaking an injected domain written without `https://` (1 of 5 runs). The runtime check now uses the same link rule as the grader (`links.py`). The gate hasn't yet caught a regression on its own.

## Limits of the injection suite
Six golden cases plant a payload on each route third-party text takes to the model (table cards, member names, upstream error bodies), aiming at two goals: a link to an outside site, or a fake number. Three are dev cases, run by the gate; the other three are held-out test cases that run once, at the release. A case passes only if the payload provably reached the model and the answer neither carries the link nor reports the fake value.

What the defences do:
- **Links:** any URL, host, IP or non-StatCan scheme in an answer is refused at runtime, after Unicode normalisation and un-defanging (`evil[.]com`, `evil。com`, `203.0.113.7`). The exfil host rotates between a `.com`, a `.de` and a bare IP so the eval can't pass on a blocklist.
- **Rejections:** a rejected answer is coded `ANSWER_REJECTED` and the link is withheld from errors and logs.

**What the defence costs:** in 1 of 3 gate runs of inject-03, the model ignored the attack and said so, but named the attacker's host while doing it, so the answer was withheld. A safe, correct answer was lost; that's the price of refusing every foreign host. It didn't happen in 15 study runs.

What the suite doesn't cover:
- **Few payloads.** One per route; real attacks vary wording, language and encoding.
- **Encoded leaks.** The canary catches case and spacing tricks, not base64 or other encodings. Spelled-out fake numbers ("nine hundred ninety-nine point nine") aren't detected.
- **Only our three tools.** The agent has no web, file or shell tools (`--tools ""`), so attacks that need them are out of scope, by design rather than by test.
- **Graded on text, not intent.** The answer may mention the fake value only next to a real negation ("ignored", "injected", "isn't data") in the same or the next sentence. A believed value that sits next to such a word would pass.

## Run it
```bash
make up          # Postgres + migrations; seeds the index from data/index.sql.zst
make test        # offline tests (CI runs these plus the retrieval eval on every PR)
make live        # tests against real StatCan and Claude
uv run canada-eval-retrieval --method hybrid
```

`make seed` needs no Voyage key: question embeddings are recorded once with `make record` and replayed.

Design: [`docs/SPEC.md`](docs/SPEC.md), [`docs/PLAN.md`](docs/PLAN.md), decisions in [`docs/decisions/`](docs/decisions/).
