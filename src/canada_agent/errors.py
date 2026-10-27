"""Machine-readable error codes returned to the model as `is_error` tool results (SPEC §8)."""

from enum import StrEnum


class ErrorCode(StrEnum):
    BAD_MEMBERS = "BAD_MEMBERS"
    NOT_FOUND = "NOT_FOUND"
    UPSTREAM_LOCKED_409 = "UPSTREAM_LOCKED_409"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    SNAPSHOT_MISS = "SNAPSHOT_MISS"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
