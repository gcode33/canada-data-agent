import io
import json
import logging
from decimal import Decimal

import pytest

from canada_agent.config import Settings
from canada_agent.costs import Usage, load_prices, usd_cost
from canada_agent.errors import ErrorCode
from canada_agent.logs import configure_logging, redact, trace_id

SECRET = "sk-ant-api03-THIS_MUST_NEVER_BE_LOGGED"  # noqa: S105 - fake key the tests hunt for


def capture() -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    configure_logging(stream=stream)
    return logging.getLogger("canada_agent.test"), stream


def lines(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_log_lines_are_json_with_trace_id():
    log, stream = capture()
    with trace_id("abc123"):
        log.info("tool called", extra={"tool": "get_series", "latency_ms": 12})
    [record] = lines(stream)
    assert record["message"] == "tool called"
    assert record["trace_id"] == "abc123"
    assert record["tool"] == "get_series"
    assert record["latency_ms"] == 12


@pytest.mark.parametrize("header", ["Authorization", "x-api-key", "X-Api-Key", "authorization"])
def test_secret_headers_are_redacted(header):
    log, stream = capture()
    log.info("request", extra={"headers": {header: SECRET, "Content-Type": "application/json"}})
    out = stream.getvalue()
    assert SECRET not in out
    assert lines(stream)[0]["headers"]["Content-Type"] == "application/json"


def test_keys_inside_messages_and_nested_values_are_redacted():
    log, stream = capture()
    log.info("calling with Bearer %s", SECRET, extra={"ctx": {"api_key": SECRET, "n": [SECRET]}})
    out = stream.getvalue()
    assert SECRET not in out
    assert "[REDACTED]" in out


@pytest.mark.parametrize("key", ["token", "access_token", "x-auth-token", "Cookie"])
def test_token_like_keys_are_redacted(key):
    assert redact({key: "v"}) == {key: "[REDACTED]"}


def test_token_counts_are_not_redacted():
    usage = {"input_tokens": 12, "output_tokens": 34, "max_tokens": 1024}
    assert redact({"usage": usage}) == {"usage": usage}


def test_settings_never_show_secrets(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    settings = Settings()
    assert SECRET not in repr(settings)
    assert SECRET not in str(settings.model_dump())
    assert settings.anthropic_api_key.get_secret_value() == SECRET


def test_error_codes_match_the_spec():
    assert {c.value for c in ErrorCode} == {
        "BAD_MEMBERS",
        "NOT_FOUND",
        "UPSTREAM_LOCKED_409",
        "UPSTREAM_UNAVAILABLE",
        "RATE_LIMITED",
        "SNAPSHOT_MISS",
        "BUDGET_EXCEEDED",
    }


def test_cost_from_a_fixed_usage_object():
    prices = load_prices()
    usage = Usage(input_tokens=1_000_000, output_tokens=100_000, cache_read_input_tokens=500_000)
    # Sonnet 5.5: $2/M input, $10/M output, cache read 0.1 x input = $0.20/M
    assert usd_cost("claude-sonnet-5-5", usage, prices) == Decimal("3.10")


def test_haiku_long_prompt_tier():
    prices = load_prices()
    short = Usage(input_tokens=100_000, output_tokens=0)
    long = Usage(input_tokens=100_001, output_tokens=0)
    assert usd_cost("claude-haiku-5-5", short, prices) == Decimal("0.01")
    # above 100K prompt tokens Haiku 5.5 bills $0.50/M input
    assert usd_cost("claude-haiku-5-5", long, prices) == Decimal("0.0500005")


def test_unknown_model_is_an_error_not_free():
    with pytest.raises(KeyError):
        usd_cost("claude-made-up", Usage(input_tokens=1, output_tokens=1), load_prices())
