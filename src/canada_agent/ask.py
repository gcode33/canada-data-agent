"""`canada-ask`: answer a question about Canadian data with cited StatCan numbers.

The model runs through `claude -p` on George's Claude subscription (ADR 0009), with our
MCP server as its only tools: no built-in tools, no other MCP servers, no saved session.
Events stream as they happen, so our code enforces the budget (tool calls, time) itself
and stops the run; `run_events` is pure, which lets a stub model test it. The final answer
is structured output, checked here before anyone sees it.
"""

import argparse
import hashlib
import json
import logging
import secrets
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from canada_agent.config import Settings
from canada_agent.errors import ErrorCode
from canada_agent.logs import configure_logging, trace_id
from canada_agent.mcp_server import SERVER_NAME
from canada_agent.wds.client import ALLOWED_HOST

TOOLS = ("search_tables", "get_table_dimensions", "get_series")
TOOL_PREFIX = f"mcp__{SERVER_NAME}__"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "system_v1.md"
PROMPT_TEMPLATE = PROMPT_PATH.read_text()
PROMPT_VERSION = f"v1-{hashlib.sha256(PROMPT_TEMPLATE.encode()).hexdigest()[:8]}"

log = logging.getLogger("canada_agent.ask")

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "answer_values": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"enum": ["level", "change_abs", "change_pct", "ratio"]},
                    "description": {"type": "string"},
                    "value": {"type": "number"},
                    "unit": {"type": "string"},
                    "vector_id": {"type": "integer"},
                    "ref_period": {"type": "string"},
                },
                "required": ["label", "description", "value", "unit", "vector_id", "ref_period"],
                "additionalProperties": False,
            },
        },
        "source_urls": {"type": "array", "items": {"type": "string"}},
        "refused": {"type": "boolean"},
    },
    "required": ["answer", "answer_values", "source_urls", "refused"],
    "additionalProperties": False,
}


class AskError(Exception):
    """`claude -p` failed, went over budget, or returned an unacceptable answer."""

    def __init__(self, message: str, code: ErrorCode | None = None) -> None:
        super().__init__(message)
        self.code = code


class UsageLimitError(AskError):
    """The subscription's usage limit was hit: retry after it resets, don't count a failure."""


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    latency_s: float | None = None
    is_error: bool = False


@dataclass(frozen=True)
class AskResult:
    answer: dict[str, Any]
    model_usage: dict[str, Any]
    num_turns: int
    duration_ms: int
    api_equivalent_usd: Decimal  # what the run would cost on the API; the subscription pays
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_version: str = PROMPT_VERSION


def system_prompt(canary: str) -> str:
    return PROMPT_TEMPLATE.format(canary=canary)


def mcp_config(settings: Settings) -> dict[str, Any]:
    return {
        "mcpServers": {
            SERVER_NAME: {
                "command": sys.executable,
                "args": ["-m", "canada_agent.mcp_server"],
                "env": {"DATABASE_URL": settings.database_url},
            }
        }
    }


def build_command(
    question: str, model: str, settings: Settings, table: int | None, canary: str = "unset"
) -> list[str]:
    prompt = question if table is None else f"{question}\n\n(Use StatCan table {table}.)"
    return [
        "claude",
        "-p",
        prompt,
        "--model",
        model,
        "--output-format",
        "stream-json",
        "--verbose",  # stream-json requires it; it is what exposes each tool call
        "--json-schema",
        json.dumps(ANSWER_SCHEMA),
        "--system-prompt",
        system_prompt(canary),
        "--tools",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        json.dumps(mcp_config(settings)),
        "--allowedTools",
        ",".join(f"{TOOL_PREFIX}{t}" for t in TOOLS),
        "--setting-sources",
        "",
        "--no-session-persistence",
    ]


def parse_output(out: dict[str, Any]) -> AskResult:
    if out.get("is_error") or out.get("subtype") != "success":
        text = str(out.get("result"))[:300]
        if "limit" in text.casefold() and "hit" in text.casefold():
            raise UsageLimitError(f"Claude usage limit: {text}")
        raise AskError(f"claude -p failed: {out.get('subtype')}: {text}")
    answer = out.get("structured_output")
    if not isinstance(answer, dict):
        raise AskError("claude -p returned no structured_output")
    return AskResult(
        answer=answer,
        model_usage=out.get("modelUsage") or {},
        num_turns=int(out.get("num_turns") or 0),
        duration_ms=int(out.get("duration_ms") or 0),
        api_equivalent_usd=Decimal(str(out.get("total_cost_usd") or 0)),
    )


def parse_result(stdout: str) -> AskResult:
    try:
        out = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AskError(f"claude -p did not return JSON: {stdout[:200]!r}") from exc
    return parse_output(out)


def check_answer(answer: dict[str, Any], canary: str) -> None:
    """The rules a model can't be trusted to keep: checked in code on every answer."""
    if canary in json.dumps(answer):
        raise AskError("the answer contains the prompt canary: possible prompt leak")
    values, urls = answer.get("answer_values"), answer.get("source_urls")
    if answer.get("refused"):
        if values:
            raise AskError("a refusal must have empty answer_values")
        return
    if not values:
        raise AskError("an answer with no values must be a refusal")
    if not urls:
        raise AskError("an answer must cite a source")
    for url in urls:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname != ALLOWED_HOST:
            raise AskError(f"citation is not a StatCan URL: {url[:100]!r}")


def run_events(
    events: Iterable[dict[str, Any]],
    *,
    max_tool_calls: int,
    deadline_s: float,
    canary: str,
    clock: Callable[[], float] = time.monotonic,
    on_event: Callable[[str], None] = lambda _: None,
) -> AskResult:
    """Consume `claude -p` stream events, enforcing the budget as they arrive."""
    start = clock()
    calls: dict[str, ToolCall] = {}
    started: dict[str, float] = {}
    for event in events:
        if clock() - start > deadline_s:
            raise AskError(f"over the {deadline_s:.0f}s budget", ErrorCode.BUDGET_EXCEEDED)
        message = event.get("message")
        blocks = message.get("content") if isinstance(message, dict) else None
        for block in blocks if isinstance(blocks, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name", "").startswith(TOOL_PREFIX):
                if len(calls) >= max_tool_calls:
                    raise AskError(
                        f"over the budget of {max_tool_calls} tool calls",
                        ErrorCode.BUDGET_EXCEEDED,
                    )
                name = block["name"].removeprefix(TOOL_PREFIX)
                calls[block["id"]] = ToolCall(name, block.get("input") or {})
                started[block["id"]] = clock()
                on_event(f"→ {name} {json.dumps(block.get('input') or {})}")
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in calls:
                key = block["tool_use_id"]
                call = calls[key]
                latency = round(clock() - started[key], 3)
                failed = bool(block.get("is_error"))
                calls[key] = ToolCall(call.name, call.arguments, latency, failed)
                on_event(f"← {call.name} {'ERROR' if failed else 'ok'} {latency}s")
        if event.get("type") == "result":
            result = parse_output(event)
            check_answer(result.answer, canary)
            return AskResult(
                result.answer,
                result.model_usage,
                result.num_turns,
                result.duration_ms,
                result.api_equivalent_usd,
                list(calls.values()),
            )
    raise AskError("claude -p ended without a result")


def _stream(command: list[str], timeout: float) -> Iterator[dict[str, Any]]:
    proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        command,
        stdin=subprocess.DEVNULL,  # an inherited open stdin makes `claude -p` wait for input
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    timed_out = threading.Event()

    def expire() -> None:  # a silent hang produces no event for run_events to notice
        timed_out.set()
        proc.kill()

    timer = threading.Timer(timeout, expire)
    timer.start()
    try:
        for line in proc.stdout or []:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                yield event
        if timed_out.is_set():
            raise AskError(f"over the {timeout:.0f}s budget", ErrorCode.BUDGET_EXCEEDED)
        stderr = proc.stderr.read()[:300] if proc.stderr else ""
        if proc.wait() != 0:
            raise AskError(f"claude -p exited {proc.returncode}: {stderr}")
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()  # stopping early (over budget) must stop the agent too
        proc.wait()


def ask(
    question: str,
    *,
    model: str,
    settings: Settings,
    table: int | None = None,
    on_event: Callable[[str], None] = lambda _: None,
) -> AskResult:
    canary = f"CANARY-{secrets.token_hex(8)}"
    run_id = secrets.token_hex(6)
    command = build_command(question, model, settings, table, canary)
    with trace_id(run_id):
        result = run_events(
            _stream(command, settings.question_timeout_s),
            max_tool_calls=settings.max_tool_calls,
            deadline_s=settings.question_timeout_s,
            canary=canary,
            on_event=on_event,
        )
        log.info(
            "question answered",
            extra={
                "model": model,
                "prompt_version": result.prompt_version,
                "refused": result.answer["refused"],
                "num_turns": result.num_turns,
                "duration_ms": result.duration_ms,
                "api_equivalent_usd": str(result.api_equivalent_usd),
                "usage": result.model_usage,
                "tools": [
                    {"name": c.name, "latency_s": c.latency_s, "is_error": c.is_error}
                    for c in result.tool_calls
                ],
            },
        )
    return result


def render(result: AskResult) -> str:
    a = result.answer
    lines = [a["answer"], ""]
    lines += [
        f"  {v['description']}: {v['value']} {v['unit']} ({v['ref_period']})"
        for v in a["answer_values"]
    ]
    lines += [f"Source: {url}" for url in a["source_urls"]]
    lines.append(
        f"[{result.num_turns} turns, {len(result.tool_calls)} tool calls, "
        f"{result.duration_ms / 1000:.1f}s, API-equivalent ${result.api_equivalent_usd:.4f}; "
        "billed to subscription]"
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(prog="canada-ask", description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--table", type=int, help="8-digit StatCan table id to use")
    parser.add_argument("--model", help="defaults to AGENT_MODEL")
    parser.add_argument("--json", action="store_true", help="print the structured answer")
    parser.add_argument("--trace", action="store_true", help="show each tool call and the log")
    args = parser.parse_args()
    settings = Settings()
    if args.trace:
        configure_logging(stream=sys.stderr)

    def show(line: str) -> None:
        if args.trace:
            print(line[:200], file=sys.stderr, flush=True)

    try:
        result = ask(
            args.question,
            model=args.model or settings.agent_model,
            settings=settings,
            table=args.table,
            on_event=show,
        )
    except AskError as exc:
        prefix = f"{exc.code}: " if exc.code else ""
        sys.exit(f"canada-ask: {prefix}{exc}")
    print(json.dumps(result.answer, indent=2) if args.json else render(result))
