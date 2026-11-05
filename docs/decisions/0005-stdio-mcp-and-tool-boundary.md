# 0005. Stdio-only MCP server, and what the tool boundary enforces

Date: 2026-11-03 · Status: Accepted

## Context
Step 3.1 finishes the MCP server: three read-only tools used by `canada-ask` (through `claude -p`, ADR 0009) and by anyone's Claude Code. The tool boundary is where an agent's mistakes, or instructions planted in third-party data, meet our code.

## Decision
- **Stdio only.** The client starts the server as a local subprocess. No port, no auth to build, no remote attack surface.
- **Unknown arguments are refused at call time.** The input schemas say `additionalProperties: false`, but the SDK's argument model silently drops unknown keys and runs the tool anyway. A test caught this. `StrictServer.call_tool` now rejects them with `BAD_ARGUMENTS`.
- **Tool descriptions are pinned.** `tests/snapshots/mcp_tools.json` holds each tool's description and schema, and a test fails if they differ. A description is a prompt, so any change shows up as a reviewable diff in the PR. This is our version of Uber's "diff, then approve" (`docs/ideas/0001-uber-mcp-gateway.md`).
- **`get_series` is projected at the boundary.** The scalar factor is given once per series, `decimals` is dropped because values are already rounded, and `status_symbol` appears only when StatCan flagged a value. Measured on the real rent series: 13 points 1,852 → 812 chars (−56%); 120 points 15,227 → 5,413 chars (−64%). The service layer still returns the full SPEC shape.
- **Every result is capped at 16,000 chars (about 4k tokens) by trimming, not failing.** Oldest points go first, then lowest-ranked tables, then the widest dimension is halved, and `truncated` says so. Only a result that can't shrink is an error (`RESULT_TOO_LARGE`).

## Deviations from SPEC §8
- **`search_tables` returns JSON text, not `search_result` blocks.** Those blocks are an Anthropic API content type with no MCP equivalent, and our client is Claude Code (ADR 0009). Citation safety comes from server-built `source_url`s, which a later grader checks.
- **`get_series` points omit `decimals`, and omit `status_symbol` when it's 0**, as above.

## Why not
- **Streamable HTTP:** it adds hosting, auth and an attack surface for no demo gain, as the SPEC already says.
- **A gateway in front of the server:** with one server it adds complexity and does nothing. It's a v1.1 question, when Open Canada and Bank of Canada arrive (the idea doc).
- **Failing oversized results:** the model would have to guess how to narrow the request. A trimmed result that says `truncated` is more useful.
