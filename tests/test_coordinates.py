import pytest
from hypothesis import given
from hypothesis import strategies as st

from canada_agent.series.coordinates import CoordinateError, build_coordinate


def test_ontario_rent_is_the_verified_coordinate():
    # Verified live 2026-10-26: Ontario (14) x Rent (81) in table 18-10-0004
    assert build_coordinate({1: 14, 2: 81}, n_dimensions=2) == "14.81.0.0.0.0.0.0.0.0"


def test_positions_are_ordered_not_insertion_ordered():
    assert build_coordinate({2: 81, 1: 14}, n_dimensions=2) == "14.81.0.0.0.0.0.0.0.0"


def test_ten_dimensions_fill_every_slot():
    members = {p: p * 10 for p in range(1, 11)}
    assert build_coordinate(members, n_dimensions=10) == "10.20.30.40.50.60.70.80.90.100"


@pytest.mark.parametrize(
    ("members", "n", "message"),
    [
        ({1: 14}, 2, "missing dimension 2"),
        ({1: 14, 2: 81, 3: 5}, 2, "unknown dimension 3"),
        ({1: 14, 2: 0}, 2, "member id must be positive"),
        ({0: 14, 1: 81}, 2, "unknown dimension 0"),
        ({p: 1 for p in range(1, 12)}, 11, "at most 10 dimensions"),
    ],
)
def test_invalid_selections_are_rejected(members, n, message):
    with pytest.raises(CoordinateError, match=message):
        build_coordinate(members, n_dimensions=n)


@given(
    st.integers(1, 10).flatmap(
        lambda n: st.tuples(st.just(n), st.lists(st.integers(1, 10_000), min_size=n, max_size=n))
    )
)
def test_always_ten_positions_and_round_trips(case):
    n, ids = case
    coord = build_coordinate({i + 1: m for i, m in enumerate(ids)}, n_dimensions=n)
    parts = [int(p) for p in coord.split(".")]
    assert len(parts) == 10
    assert parts[:n] == ids
    assert parts[n:] == [0] * (10 - n)
