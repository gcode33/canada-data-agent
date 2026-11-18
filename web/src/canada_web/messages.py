"""The only text a failed run shows (A8 §9, U6): fixed per code, never `str(exc)`, never answer or
tool text. Each says what happened and what to do next."""

from canada_web.events import FailureCode

FAILURE_MESSAGES: dict[FailureCode, str] = {
    FailureCode.ANSWER_REJECTED: (
        "The agent's runtime checks refused this answer, so it isn't shown. An answer must "
        "cite only numbers and links the tools returned in this run."
    ),
    FailureCode.BUDGET_EXCEEDED: (
        "The run went over its budget (8 tool calls or 120 seconds) and was stopped. "
        "Try a narrower question."
    ),
    FailureCode.CANCELLED: "You stopped this run. Nothing was answered.",
    FailureCode.USAGE_LIMIT: (
        "The Claude subscription's usage limit was reached. Try again after it resets."
    ),
    FailureCode.AGENT_FAILED: "The agent failed before it could answer. Try again.",
    FailureCode.BAD_MEMBERS: "The agent asked for a combination the table doesn't have.",
    FailureCode.NOT_FOUND: "The agent asked for a table or series that doesn't exist.",
    FailureCode.UPSTREAM_LOCKED_409: (
        "Statistics Canada is updating its data (usually between midnight and 08:30 ET). "
        "Try again later."
    ),
    FailureCode.UPSTREAM_UNAVAILABLE: "Statistics Canada or the table index didn't respond.",
    FailureCode.RATE_LIMITED: "Statistics Canada asked us to slow down. Try again shortly.",
    FailureCode.SNAPSHOT_MISS: "That table isn't in the offline snapshot.",
}
