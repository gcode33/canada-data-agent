"""A committed copy of the golden tables, so evals give the same data every run (SPEC 10.6).

`canada-snapshot` (`make snapshot`) builds `snapshots/<product_id>/` from live StatCan:
`metadata.json` has every member, `series.json` the series each golden case can use, over
a pinned window. A request-matched cassette would miss whenever the agent phrased a call
differently; this answers any call. Errors mirror live: an uncovered coordinate is
BAD_MEMBERS, and an uncovered table is SNAPSHOT_MISS, which a run counts as a failure.
"""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from canada_agent.config import Settings
from canada_agent.errors import ErrorCode
from canada_agent.series.backend import (
    Dimension,
    LiveBackend,
    Member,
    Point,
    SeriesData,
    TableMetadata,
)
from canada_agent.series.coordinates import build_coordinate
from canada_agent.wds.cache import PostgresCache
from canada_agent.wds.client import WdsClient, WdsError

ROOT = Path(__file__).resolve().parents[3]
SNAPSHOTS = ROOT / "snapshots"
GOLDEN = ROOT / "evals" / "golden" / "cases.yaml"
WINDOW = ("2024-01", "2026-09")  # wide enough for "a year earlier" around the golden periods


class SnapshotBackend:
    def __init__(self, directory: Path = SNAPSHOTS) -> None:
        self.directory = directory

    def _load(self, product_id: int, name: str) -> Any:
        path = self.directory / str(product_id) / name
        if not path.exists():
            raise WdsError(ErrorCode.SNAPSHOT_MISS, f"table {product_id} is not in the snapshot")
        return json.loads(path.read_text(encoding="utf-8"))

    def metadata(self, product_id: int) -> TableMetadata:
        raw = self._load(product_id, "metadata.json")
        dimensions = [
            Dimension(d["position"], d["name"], [Member(**m) for m in d["members"]])
            for d in raw.pop("dimensions")
        ]
        return TableMetadata(dimensions=dimensions, **raw)

    def series_data(self, product_id: int, coordinate: str, start: str, end: str) -> SeriesData:
        series = self._load(product_id, "series.json").get(coordinate)
        if series is None:
            raise WdsError(
                ErrorCode.BAD_MEMBERS,
                f"coordinate {coordinate} is not a series in table {product_id}",
            )
        points = [Point(**p) for p in series["points"] if start <= p["ref_period"][:7] <= end]
        return SeriesData(series["vector_id"], points)


def golden_coordinates(path: Path = GOLDEN) -> dict[int, set[str]]:
    wanted: dict[int, set[str]] = {}
    for case in yaml.safe_load(path.read_text(encoding="utf-8")):
        for value in case["expected"].get("values", []):
            members = {int(k): v for k, v in value["members"].items()}
            coord = build_coordinate(members, n_dimensions=len(members))
            wanted.setdefault(value["table"], set()).add(coord)
    return wanted


def main() -> None:
    settings = Settings()
    client = WdsClient(cache=PostgresCache(settings.database_url), max_rps=settings.statcan_max_rps)
    live = LiveBackend(client)
    for table, coordinates in sorted(golden_coordinates().items()):
        folder = SNAPSHOTS / str(table)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "metadata.json").write_text(
            json.dumps(asdict(live.metadata(table)), ensure_ascii=False, indent=0) + "\n",
            encoding="utf-8",
        )
        series = {}
        for coord in sorted(coordinates):
            data = live.series_data(table, coord, *WINDOW)
            series[coord] = asdict(data)
        (folder / "series.json").write_text(
            json.dumps(series, ensure_ascii=False, indent=0) + "\n", encoding="utf-8"
        )
        print(f"{table}: {len(series)} series")
