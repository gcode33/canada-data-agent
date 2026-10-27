"""Against the real API. Run with `make live`; excluded from CI by the default `-m 'not live'`."""

import time

import httpx
import pytest

from canada_agent.series.backend import LiveBackend
from canada_agent.series.service import get_series, get_table_dimensions
from canada_agent.wds.client import WdsClient

pytestmark = pytest.mark.live


def test_ontario_rent_september_to_september():
    out = get_series(LiveBackend(WdsClient()), 18100004, {1: 14, 2: 81}, "2025-09", "2026-09")
    values = {p["ref_period"]: p["value"] for p in out["points"]}
    assert values["2025-09"] == 161.2
    assert values["2026-09"] == 164.4
    assert round(100 * (164.4 / 161.2 - 1), 1) == 2.0


def test_rent_is_found_by_filter_three_levels_deep():
    out = get_table_dimensions(LiveBackend(WdsClient()), 18100004, {"2": "rent"})
    names = {m["name"]: m["id"] for m in out["dimensions"][1]["members"]}
    assert names["Rent"] == 81


def test_the_source_url_we_build_resolves():
    url = get_series(LiveBackend(WdsClient()), 18100004, {1: 14, 2: 81}, "2026-09", "2026-09")[
        "source_url"
    ]
    # The StatCan website (not the data API) intermittently stalls; retry like the client does.
    for attempt in range(3):
        try:
            assert httpx.get(url, follow_redirects=True, timeout=15).status_code == 200
            return
        except httpx.TransportError:
            if attempt == 2:
                raise
            time.sleep(2**attempt)
