"""The MCP server: one stdio front door to the data tools, for `canada-ask` and Claude Code.

Three read-only tools (SPEC §8): `search_tables` finds tables, `get_table_dimensions` finds
member ids, `get_series` fetches values. At this boundary the server also:
- rejects unknown arguments (`additionalProperties: false` on every input schema);
- turns expected failures into `ToolError("CODE: detail")`, so the model sees an
  `is_error` result with a machine-readable code instead of a crash;
- projects `get_series` down to the fields an answer needs, and caps every result at
  about 4k tokens (`RESULT_CHAR_CAP`), trimming rather than failing.
Tool descriptions are prompts: `tests/snapshots/mcp_tools.json` pins them, and CI fails
if one changes without that snapshot changing in the same PR (ADR 0005).
"""

import json
import sys
from collections.abc import Callable
from typing import Annotated, Any

import psycopg
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from canada_agent.config import Settings
from canada_agent.embed.voyage import EmbedError, VoyageClient
from canada_agent.evals import poison
from canada_agent.search import tables
from canada_agent.series import service
from canada_agent.series.backend import DataBackend, LiveBackend
from canada_agent.series.snapshot import SnapshotBackend
from canada_agent.untrusted import untrusted_text
from canada_agent.wds.cache import PostgresCache
from canada_agent.wds.client import WdsClient, WdsError

SERVER_NAME = "canada"
RESULT_CHAR_CAP = 16_000  # ~4k tokens at ~4 chars/token (SPEC §8)

ProductId = Annotated[int, Field(ge=10_000_000, le=99_999_999, description="8-digit table id")]


def project_series(full: dict[str, Any]) -> dict[str, Any]:
    """Keep what an answer needs. Scalar factor is per series; decimals are already applied
    to the values; a status symbol is kept only where StatCan flagged the value."""
    points = full["points"]
    scalars = {p["scalar_factor"] for p in points}
    out = {k: full[k] for k in ("product_id", "vector_id", "coordinate", "source_url")}
    out["scalar_factor"] = scalars.pop() if len(scalars) == 1 else "varies"
    out["points"] = [
        {"ref_period": p["ref_period"], "value": p["value"]}
        | ({"status_symbol": p["status_symbol"]} if p["status_symbol"] else {})
        | ({"scalar_factor": p["scalar_factor"]} if out["scalar_factor"] == "varies" else {})
        for p in points
    ]
    out["first_period_returned"] = points[0]["ref_period"] if points else None
    out["truncated"] = full["truncated"]
    out["no_data_in_range"] = full["no_data_in_range"]
    return out


def cap(result: dict[str, Any]) -> str:
    """Serialise, trimming the result's longest list until it fits RESULT_CHAR_CAP."""
    text = json.dumps(result, ensure_ascii=False)
    while len(text) > RESULT_CHAR_CAP:
        if not _trim(result):
            raise ToolError("RESULT_TOO_LARGE: narrow the request (fewer members or months)")
        text = json.dumps(result, ensure_ascii=False)
    return text


def _trim(result: dict[str, Any]) -> bool:
    if result.get("points"):
        result["points"] = result["points"][len(result["points"]) // 4 + 1 :]  # oldest first
        result["truncated"] = True
        result["first_period_returned"] = result["points"][0]["ref_period"]
        return True
    if result.get("results") and len(result["results"]) > 1:
        result["results"].pop()  # lowest-ranked table first
        result["truncated"] = True
        return True
    dims = [d for d in result.get("dimensions", []) if len(d["members"]) > 1]
    if dims:
        widest = max(dims, key=lambda d: len(d["members"]))
        widest["members"] = widest["members"][: len(widest["members"]) // 2]
        widest["truncated"] = True
        return True
    return False


def _call(fn: Callable[[], dict[str, Any]]) -> str:
    try:
        return cap(fn())
    except (WdsError, EmbedError) as exc:
        if isinstance(exc, WdsError):
            message = f"{exc.code}: {exc.detail}"
            if exc.untrusted:  # SPEC 8: upstream bodies reach the model only escaped, labelled
                message += (
                    f" | upstream text (untrusted data): {untrusted_text(exc.untrusted, 500)}"
                )
            raise ToolError(message) from exc
        raise ToolError(f"UPSTREAM_UNAVAILABLE: {exc}") from exc
    except ValueError as exc:
        raise ToolError(f"BAD_ARGUMENTS: {exc}") from exc
    except psycopg.Error as exc:
        raise ToolError(f"UPSTREAM_UNAVAILABLE: database: {type(exc).__name__}") from exc


class StrictServer(MCPServer):
    """Enforces `additionalProperties: false` at call time. The SDK's argument model
    silently drops unknown keys, so the schema alone would only be a promise."""

    async def call_tool(self, name: str, arguments: dict[str, Any], context: Any = None) -> Any:
        tool = self._tool_manager.get_tool(name)
        if tool is not None:
            unknown = sorted(set(arguments) - set(tool.parameters.get("properties", {})))
            if unknown:
                raise ToolError(f"BAD_ARGUMENTS: unknown argument(s) {unknown} for {name}")
        return await super().call_tool(name, arguments, context)


def build_server(backend: DataBackend, index: tables.TableIndex | None = None) -> MCPServer:
    server = StrictServer(SERVER_NAME)

    @server.tool()
    def search_tables(
        query: Annotated[
            str,
            Field(min_length=1, max_length=tables.MAX_QUERY_CHARS, description="The question"),
        ],
        k: Annotated[int, Field(ge=1, le=tables.MAX_K, description="Tables to return")] = 5,
    ) -> str:
        """Find the Statistics Canada tables most likely to answer a question. Call this
        first. Returns up to k tables, best first, each with a short card (title,
        frequency, date range, dimensions with member counts) and its source_url.
        Pick a table, then call get_table_dimensions on its product_id."""
        if index is None:
            raise ToolError("UPSTREAM_UNAVAILABLE: the table index is not configured")
        return _call(lambda: tables.search_tables(index, query, k))

    @server.tool()
    def get_table_dimensions(
        product_id: ProductId,
        filters: Annotated[
            dict[str, str] | None,
            Field(description='Optional {dimension position: text} filter, e.g. {"2": "rent"}'),
        ] = None,
    ) -> str:
        """List a table's dimensions and their member ids (at most 50 per dimension).
        Call this before get_series to find one member id per dimension. Filter a large
        dimension by name, e.g. {"1": "ontario", "2": "rent"}."""
        return _call(lambda: service.get_table_dimensions(backend, product_id, filters))

    @server.tool()
    def get_series(
        product_id: ProductId,
        members: Annotated[
            dict[str, int],
            Field(description='{dimension position: member id}, e.g. {"1": 14, "2": 81}'),
        ],
        start: Annotated[str, Field(pattern=r"^\d{4}-\d{2}$", description="First month, YYYY-MM")],
        end: Annotated[str, Field(pattern=r"^\d{4}-\d{2}$", description="Last month, YYYY-MM")],
    ) -> str:
        """Fetch one series (one member per dimension) between two months, at most 120
        points. Values are as published; null means suppressed, never zero. Multiply by
        scalar_factor. Compute changes yourself from the values, and cite source_url."""
        return _call(
            lambda: project_series(service.get_series(backend, product_id, members, start, end))
        )

    # FastMCP-style decorators don't emit additionalProperties: false, and strict tool use
    # needs it (ADR 0001). Set it on every tool's top-level input schema.
    for tool in server._tool_manager.list_tools():
        tool.parameters["additionalProperties"] = False
    return server


def components(settings: Settings) -> tuple[DataBackend, VoyageClient | None]:
    """The data backend and Voyage client a server would use. Snapshot runs get neither a
    StatCan nor a Voyage client, so Claude is the only outside service they reach; search
    then uses full-text plus recorded query vectors and says when it is degraded."""
    if settings.data_backend == "snapshot":
        backend: DataBackend = SnapshotBackend()
        if settings.poison:  # injection fixtures exist only on top of the snapshot
            backend = poison.PoisonedBackend(backend, poison.parse(settings.poison))
        return backend, None
    backend = LiveBackend(
        WdsClient(cache=PostgresCache(settings.database_url), max_rps=settings.statcan_max_rps)
    )
    key = settings.voyage_api_key.get_secret_value()
    try:
        # One attempt: an agent is waiting, so a rate limit degrades search (flagged) rather
        # than stalling 60 s. The batch indexer keeps the patient default.
        return backend, VoyageClient(key, max_attempts=1) if key else None
    except EmbedError as exc:
        print(f"canada-mcp: {exc}; search falls back to recorded queries", file=sys.stderr)
        return backend, None


def main() -> None:
    settings = Settings()
    backend, voyage = components(settings)
    index: tables.TableIndex = tables.PostgresTableIndex(settings.database_url, voyage)
    if settings.data_backend == "snapshot" and settings.poison:
        index = poison.PoisonedIndex(index, poison.parse(settings.poison))
    build_server(backend, index).run("stdio")


if __name__ == "__main__":
    main()
