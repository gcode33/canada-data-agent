"""`canada-ask`: answer a question about Canadian data with cited StatCan numbers.

The model runs through `claude -p` on George's Claude subscription (ADR 0009), with our
MCP server as its only tools: no built-in tools, no other MCP servers, no saved session.
Events stream as they happen, so our code enforces the budget (tool calls, time) itself
and stops the run; `run_events` is pure, which lets a stub model test it. The final answer
is structured output, checked here before anyone sees it.
"""

import argparse
import contextlib
import hashlib
import json
import logging
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from importlib import resources
from pathlib import Path
from typing import Any

from canada_agent.config import Settings
from canada_agent.errors import ErrorCode
from canada_agent.logs import configure_logging, trace_id
from canada_agent.mcp_server import SERVER_NAME

TOOLS = ("search_tables", "get_table_dimensions", "get_series")
TOOL_PREFIX = f"mcp__{SERVER_NAME}__"
LOG_FILE = Path("logs/ask.jsonl")
PROMPT_TEMPLATE = (
    resources.files("canada_agent").joinpath("prompts/system_v1.md").read_text(encoding="utf-8")
)
PROMPT_VERSION = f"v1-{hashlib.sha256(PROMPT_TEMPLATE.encode()).hexdigest()[:8]}"

log = logging.getLogger("canada_agent.ask")

CITABLE_URL = re.compile(r"https://www150\.statcan\.gc\.ca/t1/tbl1/en/tv\.action\?pid=\d+")
VECTOR_ID = re.compile(r"vector_id\W+(\d+)")
ANY_URL = re.compile(r"https?://[^\s)\]>\"']+")

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
    return PROMPT_TEMPLATE.replace("{canary}", canary)


def mcp_config(settings: Settings) -> dict[str, Any]:
    return {
        "mcpServers": {
            SERVER_NAME: {
                "command": sys.executable,
                "args": ["-m", "canada_agent.mcp_server"],
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
        "--max-budget-usd",
        str(settings.max_question_usd),
    ]


def parse_output(out: dict[str, Any]) -> AskResult:
    if out.get("is_error") or out.get("subtype") != "success":
        text = str(out.get("result"))[:300]
        if out.get("subtype") == "error_max_budget_usd":
            raise AskError("over the cost budget", ErrorCode.BUDGET_EXCEEDED)
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


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def contains_canary(text: str, canary: str) -> bool:
    """Catches case and spacing tricks. Encoded forms (base64) still get through: a canary
    is a tripwire, not a guarantee, and the README says so."""
    return _squash(canary) in _squash(text)


def check_answer(answer: dict[str, Any], canary: str) -> None:
    """The rules a model can't be trusted to keep: checked in code on every answer."""
    if contains_canary(json.dumps(answer), canary):
        raise AskError("the answer contains the prompt canary: possible prompt leak")
    values, urls = answer.get("answer_values"), answer.get("source_urls") or []
    for url in [*urls, *ANY_URL.findall(answer.get("answer", ""))]:
        if not CITABLE_URL.fullmatch(url.rstrip(".,;")):
            raise AskError(f"citation is not a StatCan URL: {url[:100]!r}")
    if answer.get("refused"):
        if values:
            raise AskError("a refusal must have empty answer_values")
        return
    if not values:
        raise AskError("an answer with no values must be a refusal")
    if not urls:
        raise AskError("an answer must cite a source")


def check_grounded(
    answer: dict[str, Any], calls: list[ToolCall], urls: set[str], vectors: set[int]
) -> None:
    """Tie the answer to what the tools actually returned in this run."""
    if answer.get("refused"):
        if calls and all(c.is_error for c in calls):  # an outage isn't a refusal
            raise AskError("every tool call failed", ErrorCode.UPSTREAM_UNAVAILABLE)
        return
    if not any(
        c.name == "get_series" and c.latency_s is not None and not c.is_error for c in calls
    ):
        raise AskError("an answer needs at least one successful get_series")
    for url in answer["source_urls"]:
        if url not in urls:
            raise AskError(f"cited a URL no tool returned: {url[:100]!r}")
    for value in answer["answer_values"]:
        vector = value.get("vector_id", 0)
        if vector and vector not in vectors:
            raise AskError(f"cited vector {vector}, which no tool returned")


def run_events(
    events: Iterable[dict[str, Any]],
    *,
    max_tool_calls: int,
    deadline_s: float,
    canary: str,
    clock: Callable[[], float] = time.monotonic,
    on_event: Callable[[str], None] = lambda _: None,
    calls: dict[str, ToolCall] | None = None,
) -> AskResult:
    """Consume `claude -p` stream events, enforcing the budget as they arrive."""
    start = clock()
    calls = {} if calls is None else calls  # the caller's dict survives a raise, for the log
    started: dict[str, float] = {}
    urls: set[str] = set()
    vectors: set[int] = set()
    for event in events:
        if clock() - start > deadline_s:
            raise AskError(f"over the {deadline_s:.0f}s budget", ErrorCode.BUDGET_EXCEEDED)
        if event.get("subtype") == "init":
            servers = {s.get("name"): s.get("status") for s in event.get("mcp_servers") or []}
            if servers.get(SERVER_NAME) != "connected":
                # With no tools the model would "refuse", and an outage would look like a pass.
                raise AskError(
                    f"MCP server status: {servers.get(SERVER_NAME)}",
                    ErrorCode.UPSTREAM_UNAVAILABLE,
                )
        message = event.get("message")
        blocks = message.get("content") if isinstance(message, dict) else None
        for block in blocks if isinstance(blocks, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name", "").startswith(TOOL_PREFIX):
                arguments = block.get("input") or {}
                if contains_canary(json.dumps(arguments), canary):
                    raise AskError("a tool call contains the prompt canary: possible prompt leak")
                if len(calls) >= max_tool_calls:
                    raise AskError(
                        f"over the budget of {max_tool_calls} tool calls",
                        ErrorCode.BUDGET_EXCEEDED,
                    )
                name = block["name"].removeprefix(TOOL_PREFIX)
                calls[block["id"]] = ToolCall(name, arguments)
                started[block["id"]] = clock()
                on_event(f"→ {name} {json.dumps(arguments)}")
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in calls:
                key = block["tool_use_id"]
                call = calls[key]
                latency = round(clock() - started[key], 3)
                failed = bool(block.get("is_error"))
                calls[key] = ToolCall(call.name, call.arguments, latency, failed)
                if not failed:
                    text = str(block.get("content"))
                    urls.update(CITABLE_URL.findall(text))
                    vectors.update(int(v) for v in VECTOR_ID.findall(text))
                on_event(f"← {call.name} {'ERROR' if failed else 'ok'} {latency}s")
        if event.get("type") == "result":
            result = parse_output(event)
            check_answer(result.answer, canary)
            check_grounded(result.answer, list(calls.values()), urls, vectors)
            return AskResult(
                result.answer,
                result.model_usage,
                result.num_turns,
                result.duration_ms,
                result.api_equivalent_usd,
                list(calls.values()),
            )
    raise AskError("claude -p ended without a result")


def _stream(
    command: list[str], timeout: float, env: dict[str, str] | None = None
) -> Iterator[dict[str, Any]]:
    proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        command,
        stdin=subprocess.DEVNULL,  # an inherited open stdin makes `claude -p` wait for input
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,  # its own process group, so the MCP server dies with it
    )

    def kill_group() -> None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)

    errors: list[str] = []

    def drain_stderr() -> None:  # an unread pipe would block a noisy child until the timeout
        for line in proc.stderr or []:
            if sum(map(len, errors)) < 2000:
                errors.append(line)

    drain = threading.Thread(target=drain_stderr, daemon=True)
    drain.start()
    timed_out = threading.Event()

    def expire() -> None:  # a silent hang produces no event for run_events to notice
        timed_out.set()
        kill_group()

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
        if proc.wait() != 0:
            drain.join(1)
            raise AskError(f"claude -p exited {proc.returncode}: {''.join(errors)[:300]}")
    finally:
        timer.cancel()
        kill_group()  # stopping early (over budget) must stop the agent and its tools
        proc.wait()


def _tee(
    events: Iterable[dict[str, Any]], capture: list[dict[str, Any]] | None
) -> Iterator[dict[str, Any]]:
    for event in events:
        if capture is not None:
            capture.append(event)
        yield event


def ask(
    question: str,
    *,
    model: str,
    settings: Settings,
    table: int | None = None,
    on_event: Callable[[str], None] = lambda _: None,
    capture: list[dict[str, Any]] | None = None,
) -> AskResult:
    canary = f"CANARY-{secrets.token_hex(8)}"
    run_id = secrets.token_hex(6)
    command = build_command(question, model, settings, table, canary)
    # By environment, not argv: `ps` shows argv.
    env = {
        **os.environ,
        "DATABASE_URL": settings.database_url,
        "DATA_BACKEND": settings.data_backend,
        "POISON": settings.poison,
    }
    calls: dict[str, ToolCall] = {}
    outcome: dict[str, Any] = {"outcome": "error"}
    with trace_id(run_id):
        try:
            # closing(): a raising `for` doesn't close its generator, so without this the
            # agent keeps running for as long as anything holds the exception.
            with contextlib.closing(_stream(command, settings.question_timeout_s, env)) as events:
                result = run_events(
                    _tee(events, capture),
                    max_tool_calls=settings.max_tool_calls,
                    deadline_s=settings.question_timeout_s,
                    canary=canary,
                    on_event=on_event,
                    calls=calls,
                )
            outcome = {
                "outcome": "refused" if result.answer["refused"] else "answered",
                "num_turns": result.num_turns,
                "duration_ms": result.duration_ms,
                "api_equivalent_usd": str(result.api_equivalent_usd),
                "usage": result.model_usage,
            }
            return result
        except AskError as exc:
            outcome["error_code"] = str(exc.code) if exc.code else type(exc).__name__
            outcome["error"] = str(exc)[:300]
            raise
        finally:
            log.info(
                "question finished",
                extra={
                    "model": model,
                    "prompt_version": PROMPT_VERSION,
                    **outcome,
                    "tools": [
                        {
                            "name": c.name,
                            "arguments": c.arguments,
                            "latency_s": c.latency_s,
                            "is_error": c.is_error,
                        }
                        for c in calls.values()
                    ],
                },
            )


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
    else:  # every run leaves a record, including failed ones
        LOG_FILE.parent.mkdir(exist_ok=True)
        configure_logging(stream=LOG_FILE.open("a", encoding="utf-8"))

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
