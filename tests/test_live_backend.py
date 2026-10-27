"""LiveBackend's mapping of real WDS response shapes, using shapes verified live 2026-10-27."""

import httpx
import pytest

from canada_agent.errors import ErrorCode
from canada_agent.series.backend import LiveBackend
from canada_agent.wds.client import WdsClient, WdsError


def backend_returning(*bodies) -> LiveBackend:
    queue = list(bodies)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=queue.pop(0)))
    return LiveBackend(WdsClient(transport=transport, max_rps=1000))


def test_missing_table_comes_back_as_200_failed_and_maps_to_not_found():
    body = [
        {
            "status": "FAILED",
            "object": (
                "The cube product ID 99999999 does not exist. Error code = CUBE_NOT_AVAILABLE"
            ),
        }
    ]
    with pytest.raises(WdsError) as err:
        backend_returning(body).metadata(99999999)
    assert err.value.code is ErrorCode.NOT_FOUND


def test_invalid_coordinate_is_success_with_status_2_and_vector_0():
    body = [
        {
            "status": "SUCCESS",
            "object": {
                "responseStatusCode": 2,
                "productId": 18100004,
                "coordinate": "99999.1.0.0.0.0.0.0.0.0",
                "vectorId": 0,
            },
        }
    ]
    with pytest.raises(WdsError) as err:
        backend_returning(body).series_data(
            18100004, "99999.1.0.0.0.0.0.0.0.0", "2025-09", "2026-09"
        )
    assert err.value.code is ErrorCode.BAD_MEMBERS


def test_series_data_resolves_vector_then_fetches_the_exact_range():
    latest = [
        {
            "status": "SUCCESS",
            "object": {"responseStatusCode": 0, "vectorId": 41691954, "vectorDataPoint": [{}]},
        }
    ]
    rng = [
        {
            "status": "SUCCESS",
            "object": {
                "responseStatusCode": 0,
                "vectorId": 41691954,
                "vectorDataPoint": [
                    {
                        "refPer": "2025-09-01",
                        "value": 161.2,
                        "decimals": 1,
                        "scalarFactorCode": 0,
                        "symbolCode": 0,
                        "statusCode": 0,
                    },
                    {
                        "refPer": "2026-09-01",
                        "value": 164.4,
                        "decimals": 1,
                        "scalarFactorCode": 0,
                        "symbolCode": 0,
                        "statusCode": 0,
                    },
                ],
            },
        }
    ]
    data = backend_returning(latest, rng).series_data(
        18100004, "14.81.0.0.0.0.0.0.0.0", "2025-09", "2026-09"
    )
    assert data.vector_id == 41691954
    assert [(p.ref_period, p.value) for p in data.points] == [
        ("2025-09-01", 161.2),
        ("2026-09-01", 164.4),
    ]
