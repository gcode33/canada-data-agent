"""The event contract shared by live runs and replays (A8 §9, ADR 0010).

One stream shape feeds one reducer in the browser, whether it comes from a live `POST
/api/ask` or a bundled replay. The rules that matter most:
- every event has a required `type` and no field has a default, so the TypeScript union
  written against the JSON Schema can't drift into optional fields;
- nothing the runtime checks could still reject is shown first: `series` and `answer` exist
  only after a run passed `check_answer` and `check_grounded`, and a failed run ends with
  `run_failed` alone (`validate_stream`);
- no tool text: step summaries are built from parsed fields, arguments are redacted and capped,
  and failure messages come from a fixed table.
"""

from enum import StrEnum
from typing import Annotated, Literal

from canada_agent.ask import TOOLS
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

SCHEMA_VERSION = "v1"
MAX_ARGUMENTS = 200
MAX_SUMMARY = 120
MAX_POINTS = 120  # get_series' own cap


class FailureCode(StrEnum):
    """Why a run ended without an answer: every `ErrorCode`, plus the three P10 adds."""

    BAD_MEMBERS = "BAD_MEMBERS"
    NOT_FOUND = "NOT_FOUND"
    UPSTREAM_LOCKED_409 = "UPSTREAM_LOCKED_409"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    SNAPSHOT_MISS = "SNAPSHOT_MISS"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    ANSWER_REJECTED = "ANSWER_REJECTED"
    CANCELLED = "CANCELLED"
    USAGE_LIMIT = "USAGE_LIMIT"
    AGENT_FAILED = "AGENT_FAILED"  # an AskError with no code (until P10 codes every one)


class ToolErrorCode(StrEnum):
    """What a failed tool call reports: the codes tools return, else `TOOL_ERROR`."""

    BAD_MEMBERS = "BAD_MEMBERS"
    NOT_FOUND = "NOT_FOUND"
    UPSTREAM_LOCKED_409 = "UPSTREAM_LOCKED_409"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    SNAPSHOT_MISS = "SNAPSHOT_MISS"
    BAD_ARGUMENTS = "BAD_ARGUMENTS"
    RESULT_TOO_LARGE = "RESULT_TOO_LARGE"
    TOOL_ERROR = "TOOL_ERROR"


Tool = Literal[TOOLS]  # type: ignore[valid-type]  # the three tool names, from the agent


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LiveProvenance(_Strict):
    source: Literal["live"]


class RecordingProvenance(_Strict):
    source: Literal["recording"]
    case: str
    model: str
    commit: Annotated[str, Field(pattern=r"^[0-9a-f]{7,40}$")]
    commit_date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    recorded_at: str | None
    timing: Literal["recorded", "approximate"]


class Attack(_Strict):
    """What a planted attack tried, from the run's poison spec. Never the text or host."""

    goal: Literal["exfil_url", "wrong_value"]
    route: Literal["card", "member_name", "error_body"]


class RunStarted(_Strict):
    type: Literal["run_started"]
    mode: Literal["live", "replay"]
    # A replay's outcome is known up front; a live run's isn't, so live runs are "live".
    category: Literal["live", "answer", "refusal", "attack_resisted", "rejected"]
    question: Annotated[str, Field(min_length=1, max_length=500)]
    model: str
    prompt_version: str
    provenance: Annotated[LiveProvenance | RecordingProvenance, Field(discriminator="source")]
    attack: Attack | None


class StepStarted(_Strict):
    type: Literal["step_started"]
    step_id: Annotated[str, Field(min_length=1, max_length=64)]
    tool: Tool
    arguments_text: Annotated[str, Field(max_length=MAX_ARGUMENTS)]


class StepFinished(_Strict):
    type: Literal["step_finished"]
    step_id: Annotated[str, Field(min_length=1, max_length=64)]
    ok: bool
    latency_ms: Annotated[int, Field(ge=0)] | None
    error_code: ToolErrorCode | None
    summary: Annotated[str, Field(max_length=MAX_SUMMARY)]


class Point(_Strict):
    ref_period: Annotated[str, Field(pattern=r"^\d{4}(-\d{2}){0,2}$")]
    value: float | None  # None = suppressed by StatCan, never zero
    status_symbol: str | None


class Series(_Strict):
    type: Literal["series"]
    step_id: Annotated[str, Field(min_length=1, max_length=64)]
    product_id: Annotated[int, Field(ge=10_000_000, le=99_999_999)]
    # Built on the server with the agent's own `table_url(product_id)`, never copied from a
    # tool payload, so the browser holds no StatCan URL rule (A8 E2; a deviation from §9's
    # "built in the browser", recorded in PR #29: the real URL appends "01" to the id).
    table_url: str
    vector_id: Annotated[int, Field(ge=1)]
    scalar_factor: str
    truncated: bool
    label: Annotated[str, Field(max_length=MAX_SUMMARY)] | None
    points: Annotated[list[Point], Field(max_length=MAX_POINTS)]


class AnswerValue(_Strict):
    label: Literal["level", "change_abs", "change_pct", "ratio"]
    description: str
    value: float
    unit: str
    vector_id: int
    ref_period: str


class Link(_Strict):
    url: str
    linkable: bool  # decided in Python (CITABLE_URL + returned in this run), never in the browser


class Answer(_Strict):
    type: Literal["answer"]
    answer: str
    answer_values: list[AnswerValue]
    links: list[Link]
    refused: bool


class RunFailed(_Strict):
    type: Literal["run_failed"]
    code: FailureCode
    message: str  # from a fixed table; never str(exc), never answer or tool text


class RunFinished(_Strict):
    type: Literal["run_finished"]
    num_turns: Annotated[int, Field(ge=0)]
    duration_ms: Annotated[int, Field(ge=0)]
    api_equivalent_usd: float | None
    billed: Literal["subscription", "none"]


Event = Annotated[
    RunStarted | StepStarted | StepFinished | Series | Answer | RunFailed | RunFinished,
    Field(discriminator="type"),
]
EVENT = TypeAdapter(Event)
EVENTS = TypeAdapter(list[Event])
EVENT_TYPES = (
    "run_started", "step_started", "step_finished", "series", "answer", "run_failed",
    "run_finished",
)  # fmt: skip


def json_schema() -> dict:
    schema = EVENT.json_schema()
    schema["title"] = f"Canada Data Agent UI events {SCHEMA_VERSION}"
    return schema


def validate_stream(events: list[BaseModel]) -> list[str]:
    """The ordering rules (A8 §9). Returns the problems; empty means a valid stream."""
    if not events:
        return ["empty stream"]
    problems = []
    first, last = events[0], events[-1]
    if not isinstance(first, RunStarted):
        problems.append("the first event must be run_started")
    if sum(isinstance(e, RunStarted) for e in events) != 1:
        problems.append("exactly one run_started")
    terminals = [i for i, e in enumerate(events) if isinstance(e, RunFinished | RunFailed)]
    if terminals != [len(events) - 1]:
        problems.append("exactly one terminal event (run_finished or run_failed), and it is last")
    started: dict[str, str] = {}  # step id -> tool
    finished_ok: set[str] = set()
    finished: set[str] = set()
    for i, e in enumerate(events):
        if isinstance(e, StepStarted):
            if e.step_id in started:
                problems.append(f"step {e.step_id} started twice")
            started[e.step_id] = e.tool
        elif isinstance(e, StepFinished):
            if e.step_id not in started:
                problems.append(f"step {e.step_id} finished before it started")
            if e.step_id in finished:
                problems.append(f"step {e.step_id} finished twice")
            if e.ok == (e.error_code is not None):
                problems.append(f"step {e.step_id}: ok and error_code disagree")
            finished.add(e.step_id)
            if e.ok:
                finished_ok.add(e.step_id)
        elif isinstance(e, Series | Answer) and any(
            isinstance(x, StepStarted | StepFinished) for x in events[i + 1 :]
        ):
            problems.append(f"{e.type} before the steps ended: shown before the checks passed")
    answers = [i for i, e in enumerate(events) if isinstance(e, Answer)]
    shown = [e for e in events if isinstance(e, Series | Answer)]
    if isinstance(last, RunFailed) and shown:
        problems.append("a failed run showed a series or an answer")
    if isinstance(last, RunFinished):
        if len(answers) != 1 or answers[0] != len(events) - 2:
            problems.append("a finished run has exactly one answer, right before run_finished")
        if answers and any(isinstance(e, Series) for e in events[answers[-1] + 1 :]):
            problems.append("series after the answer")
    for s in (e for e in events if isinstance(e, Series)):
        if s.step_id not in finished_ok or started.get(s.step_id) != "get_series":
            problems.append(f"series for step {s.step_id}, which isn't a successful get_series")
    if isinstance(first, RunStarted):
        replay = first.mode == "replay"
        if replay != (first.provenance.source == "recording"):
            problems.append("replay mode needs recording provenance, and live needs live")
        if isinstance(last, RunFinished) and replay != (last.billed == "none"):
            problems.append("a replay bills nothing; a live run bills the subscription")
        if (first.category == "attack_resisted") != (first.attack is not None):
            problems.append("attack details belong to attack_resisted runs only")
        if first.category == "rejected" and not isinstance(last, RunFailed):
            problems.append("a rejected run must end with run_failed")
        if (first.mode == "live") != (first.category == "live"):
            problems.append("live runs, and only live runs, have the category live")
        refused = [e.refused for e in events if isinstance(e, Answer)]
        decided = first.category in ("answer", "refusal", "attack_resisted")
        if refused and decided and refused[0] != (first.category == "refusal"):
            problems.append(f"a {first.category} run's answer has refused={refused[0]}")
    return problems
