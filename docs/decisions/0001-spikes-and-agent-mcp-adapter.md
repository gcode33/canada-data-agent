# 0001. Phase 0 spikes: WDS reliability, mcp 2.x, and how the agent reaches MCP tools

Date: 2026-10-27 · Status: Accepted

## Context
Three unknowns could have forced a spec change, so they were tested with throwaway code (`spikes/`, deleted after this ADR) before any real code. Versions: `anthropic` 2.3.0, `mcp` 2.3.0, `httpx` 0.28.1, Python 3.13.16.

## Findings
1. **WDS reliability.** 20 calls each to `getDataFromCubePidCoordAndLatestNPeriods` (POST) and `getDataFromVectorByReferencePeriodRange` (GET), about 3 requests per second: **40/40 succeeded on the first try.** On 2026-10-26 a different endpoint, `getSeriesInfoFromCubePidCoord`, failed 4/4 times with connection resets. So the primary path chosen in SPEC §8 is the reliable one, and the 3-retry policy stays because reliability varies from day to day.
2. **`mcp` 2.x renamed `FastMCP` to `MCPServer`.** `from mcp.server.fastmcp import FastMCP` now raises `ModuleNotFoundError` with a pointer to the migration guide. Use `from mcp.server.mcpserver import MCPServer`, the `@server.tool()` decorator and `server.run("stdio")`. Most tutorials still show v1.
3. **The agent can use a local stdio MCP server directly.** `anthropic.lib.tools.mcp.async_mcp_tool(tool, session, strict=True)` converted a tool listed over stdio from an `mcp` 2.x server, and calling it returned the right result (`percent_change(161.2, 164.4)` → `"2.0"`). The helper handles both v1 and v2 field names internally.
4. **Gap found:** the converted `input_schema` has `required` but **no `additionalProperties: false`**, even with `strict=True`. Strict tool use needs it, and SPEC §8 requires it.

## Decision
- **The agent connects to our MCP server over stdio** through `async_mcp_tool` and the SDK tool runner. There's one tool implementation, used by both Claude Code and `canada-ask`. The fallback (calling the Python tool functions in-process) isn't needed.
- **The MCP server sets `additionalProperties: false` on every tool's input schema itself**, and a test asserts it on the converted tool params (step 3.1).
- **Deferred, needing keys or later steps:**
  - Registering the server with `claude mcp add` happens in step 3.1, with the real server.
  - The cost of one 3-tool round trip on Sonnet 5.5 and Haiku 5.5, plus the docs check of model IDs and `fallbacks`, happen in the Learn step of 3.2, once `ANTHROPIC_API_KEY` is available.

## Why not
- **The API's MCP connector (`mcp_servers` + `mcp_toolset`):** it reaches *remote* HTTP servers only, so it would mean hosting ours. That adds an HTTP attack surface, which the spec rejected.
- **Two front doors** (in-process functions for the agent, MCP for Claude Code): workable, but then the agent never exercises the MCP layer that the evals are supposed to measure.
