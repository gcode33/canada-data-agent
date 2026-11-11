"""A committed copy of the golden tables, so evals give the same data every run (SPEC 10.6).

`canada-snapshot` (`make snapshot`) writes `snapshots/<product_id>/`:
- `metadata.json`: every dimension and member, from live StatCan (WDS);
- `series.json.gz`: **every series in the table** from 2024 on, from StatCan's full-table
  CSV download (about 1 MB compressed for all nine tables).

Whole tables matter. The first snapshot held only the golden series, so any other real
series looked like "not a series": the agent found the expected answer by elimination
(Phase 4 review). Now an invalid coordinate is BAD_MEMBERS exactly as live, and the only
honest gaps are tables or periods outside the snapshot, which raise SNAPSHOT_MISS and fail
the case (graders.harness).
"""

import csv
import gzip
import io
import json
import urllib.request
import zipfile
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
CSV_CACHE = ROOT / "data" / "csv"
CSV_URL = "https://www150.statcan.gc.ca/n1/tbl/csv/{table}-eng.zip"
WINDOW_START = "2024-01"  # earlier requests are SNAPSHOT_MISS, never silently truncated


class SnapshotBackend:
    def __init__(self, directory: Path = SNAPSHOTS) -> None:
        self.directory = directory
        self._series: dict[int, dict[str, Any]] = {}

    def _path(self, product_id: int, name: str) -> Path:
        path = self.directory / str(product_id) / name
        if not path.exists():
            raise WdsError(ErrorCode.SNAPSHOT_MISS, f"table {product_id} is not in the snapshot")
        return path

    def metadata(self, product_id: int) -> TableMetadata:
        raw = json.loads(self._path(product_id, "metadata.json").read_text(encoding="utf-8"))
        dimensions = [
            Dimension(d["position"], d["name"], [Member(**m) for m in d["members"]])
            for d in raw.pop("dimensions")
        ]
        return TableMetadata(dimensions=dimensions, **raw)

    def series_data(self, product_id: int, coordinate: str, start: str, end: str) -> SeriesData:
        if product_id not in self._series:
            with gzip.open(self._path(product_id, "series.json.gz"), "rt", encoding="utf-8") as f:
                self._series[product_id] = json.load(f)
        if start < WINDOW_START:
            raise WdsError(
                ErrorCode.SNAPSHOT_MISS,
                f"the snapshot starts at {WINDOW_START}; {start} is outside it",
            )
        series = self._series[product_id].get(coordinate)
        if series is None:  # the whole table is here, so this really isn't a series
            raise WdsError(
                ErrorCode.BAD_MEMBERS,
                f"coordinate {coordinate} is not a series in table {product_id}",
            )
        points = [
            Point(ref, value, decimals, scalar, 0, 0)
            for ref, value, decimals, scalar in series["points"]
            if start <= ref[:7] <= end
        ]
        return SeriesData(series["vector_id"], points)


def _csv_rows(table: int) -> Any:
    path = CSV_CACHE / f"{table}.zip"
    if not path.exists():
        CSV_CACHE.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(  # noqa: S310 - fixed https StatCan URL
            CSV_URL.format(table=table), headers={"User-Agent": "canada-data-agent-evals"}
        )
        with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310
            path.write_bytes(response.read())
    with zipfile.ZipFile(path) as archive, archive.open(f"{table}.csv") as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig"))


def _ref(ref_date: str) -> str:
    """CSV dates (2026-09, 2026-07-01, 2025) in WDS's YYYY-MM-DD form."""
    if len(ref_date) == 4:
        return f"{ref_date}-01-01"
    return ref_date if len(ref_date) == 10 else f"{ref_date}-01"


def table_series(table: int, n_dimensions: int) -> dict[str, Any]:
    series: dict[str, Any] = {}
    for row in _csv_rows(table):
        ref = _ref(row["REF_DATE"])
        if ref[:7] < WINDOW_START:
            continue
        members = {i + 1: int(m) for i, m in enumerate(row["COORDINATE"].split("."))}
        coord = build_coordinate(members, n_dimensions=n_dimensions)
        entry = series.setdefault(
            coord, {"vector_id": int(row["VECTOR"].lstrip("v")), "points": []}
        )
        value = float(row["VALUE"]) if row["VALUE"] else None  # x and .. are suppressed: null
        entry["points"].append([ref, value, int(row["DECIMALS"] or 0), int(row["SCALAR_ID"] or 0)])
    return series


def golden_tables(path: Path = GOLDEN) -> set[int]:
    return {
        value["table"]
        for case in yaml.safe_load(path.read_text(encoding="utf-8"))
        for value in case["expected"].get("values", [])
    }


def main() -> None:
    settings = Settings()
    client = WdsClient(cache=PostgresCache(settings.database_url), max_rps=settings.statcan_max_rps)
    live = LiveBackend(client)
    for table in sorted(golden_tables()):
        folder = SNAPSHOTS / str(table)
        folder.mkdir(parents=True, exist_ok=True)
        meta = live.metadata(table)
        (folder / "metadata.json").write_text(
            json.dumps(asdict(meta), ensure_ascii=False, indent=0) + "\n", encoding="utf-8"
        )
        series = table_series(table, len(meta.dimensions))
        payload = json.dumps(series, ensure_ascii=False, sort_keys=True).encode()
        # mtime=0: the same data always compresses to the same bytes, so git diffs stay quiet.
        (folder / "series.json.gz").write_bytes(gzip.compress(payload, mtime=0))
        (folder / "series.json").unlink(missing_ok=True)
        print(f"{table}: {len(series)} series")
