# 0009. The agent runs on the Claude subscription via `claude -p`, not the API

Date: 2026-10-27 · Status: Accepted (George, 2026-10-27)

## Context
SPEC §8 and ADR 0001 assumed the agent calls the Anthropic API with `ANTHROPIC_API_KEY`, using the SDK tool runner and `async_mcp_tool`. API usage is billed per token, separately from a Claude subscription. George already pays for a subscription and will not add API billing. His other project (`jobright-local`) already runs Claude through `claude -p` on that subscription.

## Decision
- **`canada-ask` runs `claude -p`** (Claude Code headless) with our stdio MCP server as its only tools:
  - `--tools ""`: no built-in tools, so no Bash, files or web access.
  - `--strict-mcp-config --mcp-config <ours>`: no other MCP servers.
  - `--allowedTools mcp__canada__…`, `--setting-sources ""` (no user hooks or settings), `--no-session-persistence`.
  - `--system-prompt <ours>` and `--json-schema <answer schema>`, so the answer comes back as `structured_output`.
- **ADR 0001's core decision stands:** one tool implementation, reached over MCP stdio. Only the client changes, from the SDK tool runner to Claude Code. That makes "works with a real MCP client" part of the demo instead of a separate quickstart.
- **Cost reporting:** `claude -p` reports token usage and `total_cost_usd`. We record the latter as `api_equivalent_usd`, what the run would cost on the API. The SPEC's $ caps become caps on this number, so the cost discipline is unchanged even though the subscription pays.
- **No model runs in GitHub CI.** A subscription can't be used from CI, so:
  - every-PR CI keeps running all offline tests and the offline graders over committed transcripts (4.3/4.4);
  - **the eval gate (5.2) runs locally** as `make gate`. It writes `evals/gate-result.json` stamped with a hash of everything the evals depend on (prompt, tool descriptions, `src/`, `evals/`, snapshot);
  - CI recomputes that hash and fails the PR if the result is missing, stale or failing.

  The gate still blocks merges; only where the model runs moves.
- `ANTHROPIC_API_KEY` stays optional in `Settings`. A later API client could be added behind the same `ask()` signature without touching the tools.

## Consequences
- Each question pays a few seconds for Claude Code to start up. The first live run took 95 s and 6 turns; a warm-cache rerun took 9 s.
- Heavy eval runs count against subscription usage limits. The eval runner must pause and resume on a limit, as `jobright-local`'s `enrich` does.
- **Lost:** the stub-model `BUDGET_EXCEEDED` test at the SDK-loop level (3.2). It becomes a test of our own turn and cost checks on `claude -p`'s result, plus `--max-budget-usd`.
- **Lost:** the 6.1 fresh-clone job runs `canada-ask --offline` against a stub. That's unchanged in spirit, since it never needed a key.

## Why not
- **Buy API credits:** George declined. It's an extra bill for the same model he already pays for.
- **Ollama for the agent:** it would turn this into a small-model project and break the "Claude" framing that the target roles ask for. Voyage embeddings are unaffected; that key is free tier and works.
- **The Agent SDK with subscription login:** same runtime as `claude -p`, but more code for no gain at this stage.
