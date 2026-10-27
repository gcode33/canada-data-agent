"""The happy path against a real recorded WDS response (vcr cassette, replayed offline).

Re-record with `VCR_RECORD=once` after deleting the cassette; CI only ever replays it.
"""

import os
from pathlib import Path

import vcr

from canada_agent.wds.client import WdsClient

CASSETTES = Path(__file__).with_name("cassettes")
recorder = vcr.VCR(
    cassette_library_dir=str(CASSETTES),
    record_mode=os.environ.get("VCR_RECORD", "none"),
    filter_headers=["authorization", "x-api-key", "cookie", "set-cookie"],
    match_on=["method", "uri", "body"],
)


def test_ontario_rent_series_from_a_real_recorded_response():
    with recorder.use_cassette("wds_ontario_rent.yaml"):
        body = WdsClient().post(
            "getDataFromCubePidCoordAndLatestNPeriods",
            [{"productId": 18100004, "coordinate": "14.81.0.0.0.0.0.0.0.0", "latestN": 13}],
            kind="data",
        )
    obj = body[0]["object"]
    points = {p["refPer"]: p["value"] for p in obj["vectorDataPoint"]}
    assert obj["vectorId"] == 41691954
    assert points["2025-09-01"] == 161.2
    assert points["2026-09-01"] == 164.4


def test_cassette_contains_no_credentials():
    text = (CASSETTES / "wds_ontario_rent.yaml").read_text().lower()
    for header in ("authorization", "x-api-key", "set-cookie"):
        assert f"{header}:" not in text
