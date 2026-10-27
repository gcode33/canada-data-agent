"""The logic of the `get_table_dimensions` and `get_series` tools (SPEC §8).

Outputs are plain dicts ready to serialise as tool results. Source URLs are built here
from validated ids; nothing from the data is ever passed through as a link.
"""

import re
from typing import Any

from canada_agent.errors import ErrorCode
from canada_agent.series.backend import DataBackend, Point
from canada_agent.series.coordinates import CoordinateError, build_coordinate
from canada_agent.untrusted import untrusted_text
from canada_agent.wds.client import WdsError

MAX_MEMBERS_PER_DIMENSION = 50
MAX_POINTS = 120
NAME_LIMIT = 120
PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
SCALAR_FACTORS = {
    0: "units",
    1: "tens",
    2: "hundreds",
    3: "thousands",
    6: "millions",
    9: "billions",
}


def table_url(product_id: int) -> str:
    return f"https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid={product_id}01"


def get_table_dimensions(
    backend: DataBackend, product_id: int, filters: dict[Any, str] | None = None
) -> dict[str, Any]:
    meta = backend.metadata(product_id)
    wanted = {int(k): v.casefold() for k, v in (filters or {}).items()}
    dimensions = []
    for dim in meta.dimensions:
        members = dim.members
        if dim.position in wanted:
            members = [m for m in members if wanted[dim.position] in m.name.casefold()]
        dimensions.append(
            {
                "position": dim.position,
                "name": untrusted_text(dim.name, NAME_LIMIT),
                "member_count": len(dim.members),
                "members": [
                    {
                        "id": m.id,
                        "name": untrusted_text(m.name, NAME_LIMIT),
                        "parent_id": m.parent_id,
                        "terminated": m.terminated,
                    }
                    for m in members[:MAX_MEMBERS_PER_DIMENSION]
                ],
                "truncated": len(members) > MAX_MEMBERS_PER_DIMENSION,
            }
        )
    return {
        "product_id": product_id,
        "title": untrusted_text(meta.title, 300),
        "source_url": table_url(product_id),
        "dimensions": dimensions,
    }


def _period(value: str, label: str) -> str:
    if not PERIOD.match(value):
        raise ValueError(f"{label} period must be YYYY-MM, got {value!r}")
    return value


def _point(p: Point) -> dict[str, Any]:
    return {
        "ref_period": p.ref_period[:7],
        "value": p.value,
        "decimals": p.decimals,
        "scalar_factor": SCALAR_FACTORS.get(p.scalar_factor_code, str(p.scalar_factor_code)),
        "status_symbol": p.symbol_code,
        "suppressed": p.value is None,
    }


def get_series(
    backend: DataBackend, product_id: int, members: dict[Any, int], start: str, end: str
) -> dict[str, Any]:
    start, end = _period(start, "start"), _period(end, "end")
    if start > end:
        raise ValueError(f"start period {start} is after end period {end}")

    meta = backend.metadata(product_id)
    chosen = {int(k): int(v) for k, v in members.items()}
    for dim in meta.dimensions:
        member_id = chosen.get(dim.position)
        if member_id is not None and member_id not in {m.id for m in dim.members}:
            raise WdsError(
                ErrorCode.BAD_MEMBERS,
                f"member {member_id} is not in dimension {dim.position} "
                f"({dim.name}); use get_table_dimensions to find valid ids",
            )
    try:
        coordinate = build_coordinate(chosen, n_dimensions=len(meta.dimensions))
    except CoordinateError as exc:
        raise WdsError(ErrorCode.BAD_MEMBERS, str(exc)) from exc

    data = backend.series_data(product_id, coordinate, start, end)
    points = [_point(p) for p in data.points]
    return {
        "product_id": product_id,
        "vector_id": data.vector_id,
        "coordinate": coordinate,
        "points": points[-MAX_POINTS:],
        "truncated": len(points) > MAX_POINTS,
        "no_data_in_range": not points,
        "source_url": table_url(product_id),
    }
