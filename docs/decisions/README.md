# Architecture decision records

Each record states the context, the decision, and why the alternatives lost. A decision that changed is revised in place, with the reason (0008 was rewritten after the Phase 5 review).

| # | Decision | In one line |
|---|---|---|
| [0001](0001-spikes-and-agent-mcp-adapter.md) | Phase 0 spikes | WDS behaviour, mcp 2.x, and one MCP tool implementation shared by Claude Code and `canada-ask` over stdio |
| [0002](0002-migrations-without-an-orm.md) | Migrations without an ORM | Numbered SQL files and about 80 lines of runner; applied files are checksummed and edits refused |
| [0003](0003-exact-vector-scan-no-hnsw.md) | Exact vector scan | 584 cards scan in about a millisecond, and exact search keeps recall at 1.0, so evals measure the embeddings |
| [0004](0004-rerank-enabled.md) | Rerank enabled | Voyage `rerank-2.5` lifted MRR 0.41 → 0.63 untuned, on the retrieval set committed before search code |
| [0005](0005-stdio-mcp-and-tool-boundary.md) | Stdio MCP, strict tool boundary | No network listener; unknown arguments rejected in code, not just in the schema |
| [0006](0006-snapshot-not-cassettes.md) | Whole-table snapshot for evals | Answers can't change between runs; a run that leaves the snapshot fails (`SNAPSHOT_MISS`), never skips |
| [0007](0007-deterministic-graders.md) | Deterministic graders | Rules tied to the golden series, period and scale; no LLM judge in v1.0 |
| [0008](0008-gate-statistics.md) | The eval gate | Local dev × 3, baseline from a separate k=5 study, re-judged receipt in CI |
| [0009](0009-agent-runs-on-the-claude-subscription.md) | Agent on the Claude subscription | `claude -p` with our MCP server as its only tools; no API billing, and no model in CI |
| [0010](0010-web-ui-and-replay-only-demo.md) | Web UI, replay-only demo | One page in two modes: a static replay demo on Pages (no model calls) and a live mode on 127.0.0.1; `web/` imports every rule and sits outside the gate |
| [0011](0011-stay-in-python.md) | Stay in Python | Waiting on Claude is ~92–95% of a question and our CPU is 1–4%; optimise in Python where `make bench` proves it, never rewrite |
