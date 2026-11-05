import json
import sys
from decimal import Decimal

import pytest

from canada_agent.ask import (
    PROMPT_VERSION,
    AskError,
    UsageLimitError,
    _stream,
    build_command,
    check_answer,
    parse_result,
    run_events,
    system_prompt,
)
from canada_agent.config import Settings
from canada_agent.errors import ErrorCode

SETTINGS = Settings(database_url="postgresql://x@localhost/db")


def flag(cmd, name):
    return cmd[cmd.index(name) + 1]


def test_command_gives_the_model_only_our_mcp_tools():
    cmd = build_command("q?", "claude-haiku-5-5", SETTINGS, table=None)
    assert cmd[:3] == ["claude", "-p", "q?"]
    assert flag(cmd, "--tools") == ""  # no built-in tools (Bash, Read, WebFetch...)
    assert "--strict-mcp-config" in cmd  # ignore any user-level MCP servers
    assert flag(cmd, "--setting-sources") == ""  # ignore user hooks and settings
    assert "--no-session-persistence" in cmd
    assert (
        flag(cmd, "--allowedTools")
        == "mcp__canada__search_tables,mcp__canada__get_table_dimensions,mcp__canada__get_series"
    )
    server = json.loads(flag(cmd, "--mcp-config"))["mcpServers"]["canada"]
    assert server["args"] == ["-m", "canada_agent.mcp_server"]
    assert server["env"] == {"DATABASE_URL": "postgresql://x@localhost/db"}


def test_table_hint_is_appended_to_the_question():
    cmd = build_command("q?", "m", SETTINGS, table=18100004)
    assert cmd[2].endswith("(Use StatCan table 18100004.)")


def test_answer_schema_is_strict():
    schema = json.loads(flag(build_command("q", "m", SETTINGS, None), "--json-schema"))
    assert schema["additionalProperties"] is False
    assert (
        schema["items" if "items" in schema else "properties"]["answer_values"]["items"][
            "additionalProperties"
        ]
        is False
    )


def success(**over):
    out = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "num_turns": 6,
        "duration_ms": 94700,
        "total_cost_usd": 0.0167,
        "modelUsage": {"claude-sonnet-5-5": {"inputTokens": 10, "outputTokens": 20}},
        "structured_output": {
            "answer": "a",
            "answer_values": [],
            "source_urls": [],
            "refused": False,
        },
    }
    return json.dumps(out | over)


def test_parse_success_keeps_answer_and_usage():
    r = parse_result(success())
    assert r.answer["answer"] == "a"
    assert r.num_turns == 6
    assert r.api_equivalent_usd == Decimal("0.0167")
    assert "claude-sonnet-5-5" in r.model_usage


@pytest.mark.parametrize(
    "stdout, message",
    [
        ("not json", "did not return JSON"),
        (success(is_error=True, subtype="error_max_turns"), "error_max_turns"),
        (success(structured_output=None), "no structured_output"),
    ],
)
def test_parse_failures_raise_ask_error(stdout, message):
    with pytest.raises(AskError, match=message):
        parse_result(stdout)


# --- the stub model: run_events consumes scripted stream events, no Claude involved ---

URL = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810000401"
VALUE = {
    "label": "change_pct",
    "description": "rent",
    "value": 2.0,
    "unit": "percent",
    "vector_id": 41691954,
    "ref_period": "2025-09/2026-09",
}
GOOD = {"answer": "+2.0%", "answer_values": [VALUE], "source_urls": [URL], "refused": False}


def tool_use(i, name="get_series"):
    return {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "id": f"t{i}", "name": f"mcp__canada__{name}", "input": {}}
            ]
        },
    }


def tool_result(i, is_error=False):
    return {
        "type": "user",
        "message": {
            "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "is_error": is_error}]
        },
    }


def final(answer=GOOD):
    return json.loads(success(structured_output=answer))


def run(events, **kw):
    args = {"max_tool_calls": 8, "deadline_s": 120, "canary": "CANARY-x"} | kw
    return run_events(events, **args)


def test_a_full_run_records_each_tool_call_and_its_latency():
    ticks = iter([0.0, 0.0, 0.0, 0.0, 2.5, 2.5])
    result = run([tool_use(1), tool_result(1), final()], clock=lambda: next(ticks))
    assert result.answer == GOOD
    assert [(c.name, c.latency_s, c.is_error) for c in result.tool_calls] == [
        ("get_series", 2.5, False)
    ]
    assert result.prompt_version == PROMPT_VERSION


def test_tool_errors_are_recorded():
    result = run([tool_use(1), tool_result(1, is_error=True), final()])
    assert result.tool_calls[0].is_error is True


def test_the_ninth_tool_call_is_budget_exceeded_and_stops_consuming():
    seen = []

    def events():
        for i in range(20):
            seen.append(i)
            yield tool_use(i)

    with pytest.raises(AskError) as err:
        run(events())
    assert err.value.code is ErrorCode.BUDGET_EXCEEDED
    assert seen[-1] == 8  # the ninth call (index 8) stopped the run


def test_going_past_the_deadline_is_budget_exceeded():
    ticks = iter([0.0, 121.0])
    with pytest.raises(AskError) as err:
        run([tool_use(1)], clock=lambda: next(ticks))
    assert err.value.code is ErrorCode.BUDGET_EXCEEDED


def test_a_silent_hang_is_killed_and_budget_exceeded():
    hang = [sys.executable, "-c", "import time; time.sleep(30)"]
    with pytest.raises(AskError) as err:
        list(_stream(hang, timeout=0.2))
    assert err.value.code is ErrorCode.BUDGET_EXCEEDED


def test_stopping_early_kills_the_agent_process():
    chatty = [sys.executable, "-u", "-c", "import time\nprint('{}')\ntime.sleep(30)"]
    stream = _stream(chatty, timeout=25)
    next(stream)
    stream.close()  # what run_events raising does; must not wait out the sleep


def test_a_stream_without_a_result_is_an_error():
    with pytest.raises(AskError, match="without a result"):
        run([tool_use(1)])


def test_a_usage_limit_is_its_own_error():
    out = json.loads(success(is_error=True, result="You've hit your 5-hour limit"))
    with pytest.raises(UsageLimitError):
        run([out])


def test_only_our_tools_count_toward_the_budget():
    other = tool_use(1)
    other["message"]["content"][0]["name"] = "StructuredOutput"
    assert run([other, final()]).tool_calls == []


# --- check_answer: rules enforced in code, not trusted to the model ---


def test_a_good_answer_passes():
    check_answer(GOOD, "CANARY-x")


def test_a_leaked_canary_fails_even_inside_a_refusal():
    with pytest.raises(AskError, match="canary"):
        check_answer(GOOD | {"answer": "my token is CANARY-x"}, "CANARY-x")
    with pytest.raises(AskError, match="canary"):
        check_answer(
            {"answer": "CANARY-x", "answer_values": [], "source_urls": [], "refused": True},
            "CANARY-x",
        )


def test_a_clean_refusal_passes_and_needs_no_citation():
    check_answer(
        {"answer": "I can't forecast.", "answer_values": [], "source_urls": [], "refused": True},
        "CANARY-x",
    )


def test_a_refusal_with_numbers_fails():
    with pytest.raises(AskError, match="empty answer_values"):
        check_answer(GOOD | {"refused": True}, "CANARY-x")


def test_an_answer_without_values_or_citation_fails():
    with pytest.raises(AskError, match="must be a refusal"):
        check_answer(GOOD | {"answer_values": []}, "CANARY-x")
    with pytest.raises(AskError, match="cite"):
        check_answer(GOOD | {"source_urls": []}, "CANARY-x")


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/x",
        "http://www150.statcan.gc.ca/x",
        "https://www150.statcan.gc.ca.evil.com/x",
        "https://www150.statcan.gc.ca@evil.com/x",
    ],
)
def test_a_citation_outside_statcan_fails(url):
    with pytest.raises(AskError, match="not a StatCan URL"):
        check_answer(GOOD | {"source_urls": [url]}, "CANARY-x")


def test_the_canary_is_in_the_prompt_and_differs_per_run():
    assert "CANARY-abc" in system_prompt("CANARY-abc")
    cmd = build_command("q", "m", SETTINGS, None, canary="CANARY-abc")
    assert "CANARY-abc" in flag(cmd, "--system-prompt")
