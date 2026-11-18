"""The event contract (A8 §9): shapes, the ordering rules, and the committed schema."""

import pytest
from canada_agent.errors import ErrorCode
from pydantic import ValidationError

from canada_web import cli
from canada_web.events import (
    EVENT,
    EVENT_TYPES,
    FailureCode,
    ToolErrorCode,
    json_schema,
    validate_stream,
)

PROVENANCE = {"source": "recording", "case": "multi-04", "model": "claude-sonnet-5-5",
              "commit": "9e183c1", "commit_date": "2026-11-07", "recorded_at": None,
              "timing": "approximate"}  # fmt: skip


def ev(**fields):
    return EVENT.validate_python(fields)


def started(**over):
    base = {"type": "run_started", "mode": "replay", "category": "answer",
            "question": "How much did rent rise in Ontario?", "model": "claude-sonnet-5-5",
            "prompt_version": "v1-c8c974c0", "provenance": PROVENANCE, "attack": None}  # fmt: skip
    return ev(**(base | over))


def step(i, tool="get_series"):
    return [
        ev(type="step_started", step_id=f"s{i}", tool=tool, arguments_text="{}"),
        ev(type="step_finished", step_id=f"s{i}", ok=True, latency_ms=None, error_code=None,
           summary="13 points, 2025-09 to 2026-09"),
    ]  # fmt: skip


def series(i=1):
    return ev(type="series", step_id=f"s{i}", product_id=18100004, vector_id=41691116,
              scalar_factor="units", truncated=False, label=None,
              points=[{"ref_period": "2025-09", "value": 161.2, "status_symbol": None},
                      {"ref_period": "2025-10", "value": None, "status_symbol": ".."}])  # fmt: skip


ANSWER = {"type": "answer", "answer": "Rent rose 2.0%.", "answer_values": [], "links": [
    {"url": "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810000401",
     "linkable": True}], "refused": False}  # fmt: skip


def answer():
    return ev(**ANSWER)


def finished(billed="none"):
    return ev(type="run_finished", num_turns=6, duration_ms=9000, api_equivalent_usd=None,
              billed=billed)  # fmt: skip


def failed(code="ANSWER_REJECTED"):
    return ev(type="run_failed", code=code, message="The checks refused this answer.")


def good():
    return [started(), *step(1, "search_tables"), *step(2), series(2), answer(), finished()]


def test_a_successful_replay_is_valid():
    assert validate_stream(good()) == []


def test_a_rejected_replay_is_valid():
    stream = [started(category="rejected"), *step(1), failed()]
    assert validate_stream(stream) == []


def test_parallel_and_dangling_steps_are_allowed():
    a, b = step(1), step(2)
    stream = [started(category="rejected"), a[0], b[0], b[1], a[1],
              ev(type="step_started", step_id="s3", tool="get_series", arguments_text=""),
              failed("BUDGET_EXCEEDED")]  # fmt: skip
    assert validate_stream(stream) == []


@pytest.mark.parametrize(
    ("break_it", "message"),
    [
        (lambda s: s[1:], "first event must be run_started"),
        (lambda s: s[:-1], "exactly one terminal"),
        (lambda s: [*s, finished()], "exactly one terminal"),
        (lambda s: [s[0], series(2), *s[1:5], *s[6:]], "before the steps ended"),
        (lambda s: [s[0], answer(), *s[1:6], s[7]], "before the steps ended"),
        (lambda s: [*s[:5], answer(), series(2), s[7]], "series after the answer"),
        (lambda s: [*s[:-2], s[-1]], "exactly one answer"),
        (lambda s: [*s[:-1], failed()], "showed a series or an answer"),
        (lambda s: [s[0], s[2], *s[1:2], *s[3:]], "finished before it started"),
        (lambda s: [*s[:-1], finished("subscription")], "a replay bills nothing"),
        (lambda s: [started(category="attack_resisted"), *s[1:]], "attack details"),
        (lambda s: [started(category="rejected"), *s[1:]], "must end with run_failed"),
        (lambda s: [started(mode="live"), *s[1:]], "replay mode needs recording"),
    ],
)
def test_each_ordering_rule_is_enforced(break_it, message):
    problems = validate_stream(break_it(good()))
    assert any(message in p for p in problems), problems


def test_unknown_fields_and_bad_values_are_refused():
    with pytest.raises(ValidationError):
        ev(**ANSWER, html="<b>x</b>")
    with pytest.raises(ValidationError):
        ev(type="series", step_id="s1", product_id=123, vector_id=1, scalar_factor="units",
           truncated=False, label=None, points=[])  # fmt: skip
    with pytest.raises(ValidationError):
        ev(type="step_started", step_id="s1", tool="run_shell", arguments_text="")
    with pytest.raises(ValidationError):
        ev(type="step_started", step_id="s1", tool="get_series", arguments_text="x" * 201)


def test_every_event_has_a_required_type_and_no_defaults():
    """A default makes the TypeScript field optional (A8 §8): every property is required."""
    defs = json_schema()["$defs"]
    events = {name: d for name, d in defs.items() if "type" in d.get("properties", {})}
    assert sorted(d["properties"]["type"]["const"] for d in events.values()) == sorted(EVENT_TYPES)
    for name, d in defs.items():
        props = d.get("properties", {})
        assert sorted(d.get("required", [])) == sorted(props), f"{name} has an optional field"
        assert not any("default" in p for p in props.values()), f"{name} has a default"


def test_failure_codes_cover_every_agent_error_code():
    assert {c.value for c in ErrorCode} <= {c.value for c in FailureCode}


def test_tool_error_codes_cover_what_tools_return():
    runtime_only = {ErrorCode.BUDGET_EXCEEDED, ErrorCode.ANSWER_REJECTED}
    assert {c.value for c in ErrorCode} - runtime_only <= {c.value for c in ToolErrorCode}


def test_the_committed_schema_is_fresh():
    assert cli.SCHEMA.read_text() == cli.schema_text(), "run `canada-web schema` and commit it"
