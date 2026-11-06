from pathlib import Path

import pytest
import yaml

from canada_agent.errors import ErrorCode
from canada_agent.series.service import get_series, get_table_dimensions
from canada_agent.series.snapshot import GOLDEN, SNAPSHOTS, SnapshotBackend, golden_coordinates
from canada_agent.wds.client import WdsError

backend = SnapshotBackend()
RENT = "14.81.0.0.0.0.0.0.0.0"


def test_ontario_rent_comes_back_through_the_real_service():
    out = get_series(backend, 18100004, {1: 14, 2: 81}, "2025-09", "2026-09")
    assert out["vector_id"] == 41691954
    assert out["points"][0]["value"] == 161.2
    assert out["points"][-1]["value"] == 164.4
    assert len(out["points"]) == 13


def test_members_are_all_there():
    out = get_table_dimensions(backend, 18100004, {"2": "rent"})
    assert any(m["id"] == 81 for m in out["dimensions"][1]["members"])


def test_a_table_not_in_the_snapshot_is_snapshot_miss():
    with pytest.raises(WdsError) as err:
        backend.metadata(99999999)
    assert err.value.code is ErrorCode.SNAPSHOT_MISS


def test_an_uncovered_coordinate_is_bad_members_like_live():
    with pytest.raises(WdsError) as err:
        backend.series_data(18100004, "99.99.0.0.0.0.0.0.0.0", "2025-09", "2026-09")
    assert err.value.code is ErrorCode.BAD_MEMBERS


def test_an_empty_range_is_no_points_like_live():
    assert backend.series_data(18100004, RENT, "1900-01", "1900-12").points == []


def test_every_golden_value_is_answerable_from_the_snapshot():
    for case in yaml.safe_load(Path(GOLDEN).read_text(encoding="utf-8")):
        for value in case["expected"].get("values", []):
            members = {int(k): v for k, v in value["members"].items()}
            meta = backend.metadata(value["table"])
            assert len(meta.dimensions) == len(members), case["id"]
            for period in value["ref_periods"]:
                start, end = (
                    (f"{period}-01", f"{period}-12") if len(period) == 4 else (period, period)
                )
                out = get_series(backend, value["table"], members, start, end)
                assert out["points"], (case["id"], period)
                assert out["points"][0]["value"] is not None, (case["id"], period)


def test_snapshot_covers_exactly_the_golden_tables():
    assert {int(p.name) for p in SNAPSHOTS.iterdir() if p.is_dir()} == set(golden_coordinates())
