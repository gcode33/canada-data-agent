import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from test_series_service import FakeBackend, rent_points

from canada_agent.errors import ErrorCode
from canada_agent.mcp_server import build_server
from canada_agent.series.backend import SeriesData
from canada_agent.wds.client import WdsError


def call(server, name, args):
    result = asyncio.run(server.call_tool(name, args))
    return json.loads(result.content[0].text)


def test_lists_exactly_the_two_series_tools():
    tools = asyncio.run(build_server(FakeBackend()).list_tools())
    assert sorted(t.name for t in tools) == ["get_series", "get_table_dimensions"]


def test_get_series_round_trips_through_mcp():
    server = build_server(FakeBackend(series=SeriesData(41691954, rent_points())))
    args = {
        "product_id": 18100004,
        "members": {"1": 14, "2": 81},
        "start": "2025-09",
        "end": "2026-09",
    }
    out = call(server, "get_series", args)
    assert out["coordinate"] == "14.81.0.0.0.0.0.0.0.0"
    assert out["source_url"].endswith("pid=1810000401")


def test_get_table_dimensions_filters_through_mcp():
    out = call(
        build_server(FakeBackend()),
        "get_table_dimensions",
        {"product_id": 18100004, "filters": {"2": "rent"}},
    )
    assert [m["id"] for m in out["dimensions"][1]["members"]] == [80, 81]


def test_wds_errors_reach_the_model_with_their_code():
    server = build_server(
        FakeBackend(error=WdsError(ErrorCode.NOT_FOUND, "table 1 does not exist"))
    )
    with pytest.raises(ToolError, match="NOT_FOUND: table 1") as err:
        asyncio.run(server.call_tool("get_table_dimensions", {"product_id": 18100004}))
    assert not isinstance(err.value, UnexpectedToolError)  # anticipated, so the text is kept


def test_bad_periods_become_bad_arguments_not_crashes():
    server = build_server(FakeBackend())
    args = {
        "product_id": 18100004,
        "members": {"1": 14, "2": 81},
        "start": "2025",
        "end": "2026-09",
    }
    with pytest.raises(ToolError, match="BAD_ARGUMENTS: start period") as err:
        asyncio.run(server.call_tool("get_series", args))
    assert not isinstance(err.value, UnexpectedToolError)


def test_product_id_outside_8_digits_is_rejected_by_the_schema():
    with pytest.raises(ToolError):
        asyncio.run(
            build_server(FakeBackend()).call_tool("get_table_dimensions", {"product_id": 42})
        )
