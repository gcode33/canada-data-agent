"""The only text a failed run shows (A8 §9, U6): fixed per code, never `str(exc)`, never answer or
tool text. Each says what happened and what to do next. For a rejected answer, the internal error
text only *selects* one of the fixed reasons below, so the page says which check fired (the U1
honesty review: the generic text implied a made-up number where the real reason was different).
"""

from canada_agent.config import Settings

from canada_web.events import FailureCode

_BUDGET = (
    f"{Settings.model_fields['max_tool_calls'].default} tool calls or "
    f"{Settings.model_fields['question_timeout_s'].default:.0f} seconds"
)

FAILURE_MESSAGES: dict[FailureCode, str] = {
    FailureCode.ANSWER_REJECTED: (
        "The agent's runtime checks refused this answer, so it isn't shown."
    ),
    FailureCode.BUDGET_EXCEEDED: (
        f"The run went over its budget ({_BUDGET}) and was stopped. Try a narrower question."
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

# Which runtime check refused the answer, matched on the start of the agent's internal error
# text (src/canada_agent/ask.py: check_answer, check_grounded, run_events). Fixed sentences only.
REJECTIONS: tuple[tuple[str, str], ...] = (
    ("an answer with no values must be a refusal",
     "It gave no values but didn't mark the answer as a refusal, so the checks treated it as "
     "malformed."),
    ("a refusal must have empty answer_values",
     "It marked the answer as a refusal but still reported values."),
    ("an answer must cite a source", "It cited no source."),
    ("citation is not a StatCan URL", "It cited a link that isn't a Statistics Canada table."),
    ("cited a URL no tool returned", "It cited a table link no tool returned in this run."),
    ("cited vector", "It cited a data series no tool returned in this run."),
    ("reported level",
     "It reported a level that doesn't match any value the tools returned for that series."),
    ("an answer needs at least one successful get_series",
     "It reported values without fetching any data series."),
    ("every tool call failed", "Every tool call failed, so there was nothing to answer from."),
    ("the answer contains the prompt canary",
     "The answer contained a hidden marker from the agent's instructions (a possible leak)."),
    ("a tool call contains the prompt canary",
     "A tool call contained a hidden marker from the agent's instructions (a possible leak)."),
)  # fmt: skip


def failure_message(code: FailureCode, detail: str = "") -> str:
    base = FAILURE_MESSAGES[code]
    if code != FailureCode.ANSWER_REJECTED:
        return base
    reason = next((text for start, text in REJECTIONS if detail.startswith(start)), None)
    return f"{base} Reason: {reason}" if reason else base
