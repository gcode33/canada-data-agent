"""Build a WDS coordinate from one member per dimension.

A coordinate is the member ids in dimension-position order, joined by dots and padded with
zeros to exactly 10 positions: Ontario (14) x Rent (81) -> "14.81.0.0.0.0.0.0.0.0".
The server builds it; the model only names members. One position out of place would
silently fetch a different series, so every selection is checked first.
"""

MAX_DIMENSIONS = 10


class CoordinateError(ValueError):
    pass


def build_coordinate(members: dict[int, int], n_dimensions: int) -> str:
    if n_dimensions > MAX_DIMENSIONS:
        raise CoordinateError(f"WDS tables have at most 10 dimensions, got {n_dimensions}")
    for position in sorted(members):
        if not 1 <= position <= n_dimensions:
            raise CoordinateError(f"unknown dimension {position} (table has {n_dimensions})")
        if members[position] < 1:
            raise CoordinateError(f"member id must be positive (dimension {position})")
    for position in range(1, n_dimensions + 1):
        if position not in members:
            raise CoordinateError(f"missing dimension {position}: choose one member for it")
    ids = [members[p] for p in range(1, n_dimensions + 1)]
    return ".".join(str(i) for i in ids + [0] * (MAX_DIMENSIONS - n_dimensions))
