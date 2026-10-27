"""Where table metadata and series data come from.

`DataBackend` has two implementations: `LiveBackend` (StatCan WDS, here) and a snapshot
backend for CI (PLAN step 4.2). Both must raise the same `WdsError` codes for the same
problems, so evals behave identically offline.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from canada_agent.errors import ErrorCode
from canada_agent.untrusted import untrusted_text
from canada_agent.wds.client import WdsClient, WdsError


@dataclass(frozen=True)
class Member:
    id: int
    name: str
    parent_id: int | None
    terminated: bool = False


@dataclass(frozen=True)
class Dimension:
    position: int
    name: str
    members: list[Member] = field(default_factory=list)


@dataclass(frozen=True)
class TableMetadata:
    product_id: int
    title: str
    frequency_code: int
    dimensions: list[Dimension]
    start_date: str = ""  # e.g. "1914-01-01"
    end_date: str = ""
    footnotes: list[str] = field(default_factory=list)  # third-party text: untrusted


@dataclass(frozen=True)
class Point:
    ref_period: str  # as WDS sends it, e.g. "2025-09-01"
    value: float | None  # None = suppressed or not available, never 0
    decimals: int
    scalar_factor_code: int
    symbol_code: int
    status_code: int


@dataclass(frozen=True)
class SeriesData:
    vector_id: int
    points: list[Point]


class DataBackend(Protocol):
    def metadata(self, product_id: int) -> TableMetadata: ...
    def series_data(self, product_id: int, coordinate: str, start: str, end: str) -> SeriesData: ...


def _first(body: Any) -> dict[str, Any]:
    if not isinstance(body, list) or not body or not isinstance(body[0], dict):
        raise WdsError(ErrorCode.UPSTREAM_UNAVAILABLE, "unexpected response shape")
    return body[0]


def _points(raw: list[dict[str, Any]]) -> list[Point]:
    return [
        Point(
            ref_period=p["refPer"],
            value=p.get("value"),
            decimals=p.get("decimals") or 0,
            scalar_factor_code=p.get("scalarFactorCode") or 0,
            symbol_code=p.get("symbolCode") or 0,
            status_code=p.get("statusCode") or 0,
        )
        for p in raw
    ]


class LiveBackend:
    def __init__(self, client: WdsClient) -> None:
        self.client = client

    def metadata(self, product_id: int) -> TableMetadata:
        item = _first(
            self.client.post("getCubeMetadata", [{"productId": product_id}], kind="metadata")
        )
        # A missing table is HTTP 200 with status FAILED and a text message (verified live).
        if item.get("status") != "SUCCESS" or not isinstance(item.get("object"), dict):
            raise WdsError(
                ErrorCode.NOT_FOUND,
                f"table {product_id} does not exist",
                untrusted_text(str(item.get("object"))),
            )
        obj = item["object"]
        return TableMetadata(
            product_id=product_id,
            title=obj.get("cubeTitleEn", ""),
            frequency_code=obj.get("frequencyCode") or 0,
            dimensions=[
                Dimension(
                    position=d["dimensionPositionId"],
                    name=d.get("dimensionNameEn", ""),
                    members=[
                        Member(
                            m["memberId"],
                            m.get("memberNameEn", ""),
                            m.get("parentMemberId"),
                            bool(m.get("terminated")),
                        )
                        for m in d.get("member", [])
                    ],
                )
                for d in obj.get("dimension", [])
            ],
            start_date=obj.get("cubeStartDate") or "",
            end_date=obj.get("cubeEndDate") or "",
            footnotes=[f.get("footnotesEn", "") for f in obj.get("footnote") or []],
        )

    def series_data(self, product_id: int, coordinate: str, start: str, end: str) -> SeriesData:
        # Step 1: resolve the vector with one cheap point. This endpoint was 40/40 reliable
        # while getSeriesInfoFromCubePidCoord failed 4/4 (ADR 0001).
        item = _first(
            self.client.post(
                "getDataFromCubePidCoordAndLatestNPeriods",
                [{"productId": product_id, "coordinate": coordinate, "latestN": 1}],
                kind="data",
            )
        )
        obj = item.get("object") if isinstance(item.get("object"), dict) else {}
        # An invalid coordinate is status SUCCESS with responseStatusCode 2 and vectorId 0.
        if (
            item.get("status") != "SUCCESS"
            or obj.get("responseStatusCode") != 0
            or not obj.get("vectorId")
        ):
            raise WdsError(
                ErrorCode.BAD_MEMBERS,
                f"coordinate {coordinate} is not a series in table {product_id}",
            )
        vector_id = int(obj["vectorId"])

        # Step 2: the exact reference-period range.
        ranged = _first(
            self.client.get(
                "getDataFromVectorByReferencePeriodRange",
                {
                    "vectorIds": f'"{vector_id}"',
                    "startRefPeriod": f"{start}-01",
                    "endReferencePeriod": f"{end}-01",
                },
                kind="data",
            )
        )
        robj = ranged.get("object") if isinstance(ranged.get("object"), dict) else {}
        if ranged.get("status") != "SUCCESS":
            raise WdsError(
                ErrorCode.UPSTREAM_UNAVAILABLE,
                "range request failed",
                untrusted_text(str(ranged.get("object"))),
            )
        return SeriesData(vector_id, _points(robj.get("vectorDataPoint", [])))
