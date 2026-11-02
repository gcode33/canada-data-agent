"""The MCP server: one stdio front door to the data tools, for `canada-ask` and Claude Code.

Step 1.3 exposes the two series tools so the slice runs end to end; step 3.1 adds
`search_tables`, the final descriptions, the 4k result cap and the schema snapshot test.
Expected failures become `ToolError("CODE: detail")`, so the model sees an `is_error`
result with a machine-readable code (SPEC §8) instead of a crash.
"""

import json
from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from canada_agent.config import Settings
from canada_agent.series import service
from canada_agent.series.backend import DataBackend, LiveBackend
from canada_agent.wds.cache import PostgresCache
from canada_agent.wds.client import WdsClient, WdsError

SERVER_NAME = "canada"

ProductId = Annotated[int, Field(ge=10_000_000, le=99_999_999, description="8-digit table id")]


def _call(fn: Callable[[], dict[str, Any]]) -> str:
    try:
        return json.dumps(fn(), ensure_ascii=False)
    except WdsError as exc:
        raise ToolError(str(exc)) from exc
    except ValueError as exc:
        raise ToolError(f"BAD_ARGUMENTS: {exc}") from exc


def build_server(backend: DataBackend) -> MCPServer:
    server = MCPServer(SERVER_NAME)

    @server.tool()
    def get_table_dimensions(
        product_id: ProductId,
        filters: Annotated[
            dict[str, str] | None,
            Field(description='Optional {dimension position: text} filter, e.g. {"2": "rent"}'),
        ] = None,
    ) -> str:
        """List a StatCan table's dimensions and member ids. Call this before get_series
        to find the member id for each dimension; filter large dimensions by name."""
        return _call(lambda: service.get_table_dimensions(backend, product_id, filters))

    @server.tool()
    def get_series(
        product_id: ProductId,
        members: Annotated[
            dict[str, int],
            Field(description='{dimension position: member id}, e.g. {"1": 14, "2": 81}'),
        ],
        start: Annotated[str, Field(description="First month, YYYY-MM")],
        end: Annotated[str, Field(description="Last month, YYYY-MM")],
    ) -> str:
        """Fetch one series (one member per dimension) between two months. Values are
        as published; null means suppressed, never zero. Cite source_url."""
        return _call(lambda: service.get_series(backend, product_id, members, start, end))

    return server


def main() -> None:
    settings = Settings()
    client = WdsClient(cache=PostgresCache(settings.database_url), max_rps=settings.statcan_max_rps)
    build_server(LiveBackend(client)).run("stdio")


if __name__ == "__main__":
    main()
