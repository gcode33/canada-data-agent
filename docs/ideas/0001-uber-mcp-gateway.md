# Idea: borrow from Uber's MCP Gateway

**Source:** [Designing MCP Gateway: Uber's MCP Management Platform](https://www.uber.com/blog/designing-mcp-gateway/) (Uber Engineering), checked 2026-11-03.

Uber runs a control plane (MCP Registry) and a data plane (Proxy Gateway) over 800+ MCP servers and 5,000+ tools. AutoCrawler discovers services and uses an LLM to write tool descriptions from their schemas; every tool starts disabled until its owning team enables it; description changes create a diff the owners approve; and the gateway handles authorization and redacts sensitive data.

**This project doesn't need a gateway.** It has one server. A gateway pays off only with many backends, so the question comes back in v1.1 with Open Canada and Bank of Canada. Borrow the ideas, not the infrastructure.

## How the ideas map here

| Uber | This repo | Status |
|---|---|---|
| Owner approval; tools start disabled | `config/scope.toml`: only approved subjects are indexed | Done |
| The registry catalogues tools | Table cards in Postgres | Done |
| Runtime discovery avoids context bloat | `search_tables`: the agent finds 5 tables, not 584 | Done (3.1) |
| Description diff, then approve | Snapshot test of tool definitions, reviewed in the PR | Done (3.1) |
| Trim tool responses | `get_series` projection (−56% to −64% on real data) and the result cap | Done (3.1) |
| Governance at the boundary | Host allowlist, rate limit, strict arguments, escaped text | Done |

## Still open
- **LLM-written cards (AutoCrawler-style), after Phase 4.** Generate each card from StatCan metadata with Claude, review the diff, re-run the retrieval eval, and keep the cards only if recall rises. It would be a new ablation row.
- **A source registry, v1.1.** StatCan, Open Canada and Bank of Canada, each with a host allowlist, rate limit, enabled flag and owner, behind the one server. `search_tables` searches all sources, and the eval also asks whether the agent picked the right source.
