import json
from decimal import Decimal

import pytest

from canada_agent.ask import AskError, build_command, parse_result
from canada_agent.config import Settings

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
        flag(cmd, "--allowedTools") == "mcp__canada__get_table_dimensions,mcp__canada__get_series"
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
