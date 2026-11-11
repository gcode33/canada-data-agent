"""`canada-ask --offline`: the whole pipeline with a recorded model, for a clone with no key.

The model's choices (which tools to call, with what arguments, and the final answer) are
replayed from a committed transcript in `evals/transcripts/dev/`. Everything else is real:
our MCP server starts over stdio on the snapshot, every tool call runs against it, and
`run_events` applies the same budget, link and grounding checks as a live run.

The replay fails, as a live run would, if:
- a call errors that didn't when recorded (e.g. the database is down);
- search returns different tables than it did then (an empty or broken index);
- the recorded answer cites something the tools no longer return.

Its limits: the canary is a fresh token the recording never saw, so that check can't fire
here; and only runs the graders passed are replayed. It proves the plumbing works on a
fresh machine. It says nothing about the model.
"""

import asyncio
import json
import os
import re
import secrets
import sys
import time
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp import StdioServerParameters
from mcp.client.client import Client
from mcp.shared.exceptions import MCPError

from canada_agent.ask import (
    PROMPT_VERSION,
    TOOL_PREFIX,
    TOOLS,
    AskError,
    AskResult,
    _payloads,
    run_events,
)
from canada_agent.config import Settings
from canada_agent.errors import ErrorCode
from canada_agent.evals.transcripts import TRANSCRIPTS
from canada_agent.mcp_server import SERVER_NAME

RECORDED = TRANSCRIPTS / "dev"
REPO = TRANSCRIPTS.parents[1]


def _key(question: str) -> str:
    """Case, accents and punctuation don't matter; digits and decimal points do."""
    text = unicodedata.normalize("NFKD", question.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w.%]+|(?<!\d)\.|\.(?!\d)", " ", text).split())


def _passed(folder: Path) -> dict[str, bool] | None:
    """The pinned grader verdicts for this folder's split, if there are any."""
    manifest = folder.parents[1] / "grades" / f"{folder.name}.json"
    try:
        return {k: v["passed"] for k, v in json.loads(manifest.read_text()).items()}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def recordings(folder: Path = RECORDED) -> dict[str, dict[str, Any]]:
    """Replayable runs by question: readable, unpoisoned, unerrored, recorded under today's
    prompt, ending in a result, and passed by the graders (when verdicts are pinned)."""
    verdicts = _passed(folder)
    found: dict[str, dict[str, Any]] = {}
    for path in sorted(folder.glob("*.json")):
        try:
            t = json.loads(path.read_text(encoding="utf-8"))
            question, events = t["question"], t.get("events") or []
        except (OSError, ValueError, KeyError, TypeError):
            continue  # one torn file mustn't break every question
        if (
            t.get("poison")
            or t.get("error")
            or t.get("prompt_version") != PROMPT_VERSION
            or not events
            or events[-1].get("type") != "result"
            or (verdicts is not None and not verdicts.get(path.stem))
        ):
            continue
        key = _key(question)
        if key in found:
            raise AskError(f"two recordings answer the same question: {path.name}")
        shown = path.relative_to(REPO) if path.is_relative_to(REPO) else path
        found[key] = t | {"path": str(shown)}
    return found


def find(question: str, folder: Path = RECORDED) -> dict[str, Any]:
    runs = recordings(folder)
    if _key(question) not in runs:
        listed = "\n".join(f"  {t['question']}" for t in runs.values())
        raise AskError(f"no recorded run for that question; --offline can replay:\n{listed}")
    return runs[_key(question)]


def _blocks(event: dict[str, Any]) -> list[dict[str, Any]]:
    content = event.get("content") or (event.get("message") or {}).get("content") or []
    return [b for b in content if isinstance(b, dict)]


def _tables(content: Any) -> list[int]:
    return [
        r.get("product_id")
        for p in _payloads(content)
        for r in p.get("results") or []
        if isinstance(r, dict)
    ]


async def _replay(
    transcript: dict[str, Any], server: Any, max_tool_calls: int
) -> list[dict[str, Any]]:
    """Run the recorded tool calls against the server; return live stream events."""
    recorded = {
        b.get("tool_use_id"): b
        for e in transcript["events"]
        for b in _blocks(e)
        if b.get("type") == "tool_result"
    }
    events: list[dict[str, Any]] = []
    calls = 0
    async with Client(server) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        status = "connected" if names >= set(TOOLS) else f"missing {sorted(set(TOOLS) - names)}"
        events.append(
            {"type": "system", "subtype": "init",
             "mcp_servers": [{"name": SERVER_NAME, "status": status}]}
        )  # fmt: skip
        for event in transcript["events"][:-1]:
            for block in _blocks(event):
                if block.get("type") != "tool_use" or not block["name"].startswith(TOOL_PREFIX):
                    continue
                calls += 1
                if calls > max_tool_calls:  # before the call runs, as a live run would
                    raise AskError(
                        f"over the budget of {max_tool_calls} tool calls",
                        ErrorCode.BUDGET_EXCEEDED,
                    )
                name = block["name"].removeprefix(TOOL_PREFIX)
                events.append({"type": "assistant", "message": {"content": [block]}})
                result = await client.call_tool(name, block.get("input") or {})
                text = "".join(getattr(c, "text", "") for c in result.content)
                then = recorded.get(block["id"], {})
                if result.is_error and not then.get("is_error"):
                    raise AskError(
                        f"{name} failed on replay but not when recorded: {text[:200]}",
                        ErrorCode.UPSTREAM_UNAVAILABLE,
                    )
                if name == "search_tables" and _tables(text) != _tables(then.get("content")):
                    raise AskError(
                        "search_tables returned different tables than when recorded: "
                        f"{_tables(text)[:5]} vs {_tables(then.get('content'))[:5]}; "
                        "is the index seeded (`make seed`)?",
                        ErrorCode.UPSTREAM_UNAVAILABLE,
                    )
                events.append(
                    {"type": "user", "message": {"content": [
                        {"type": "tool_result", "tool_use_id": block["id"], "content": text,
                         "is_error": bool(result.is_error)}
                    ]}}
                )  # fmt: skip
    return events


def stdio_server(settings: Settings) -> StdioServerParameters:
    """Our MCP server as `claude -p` starts it, pinned to the snapshot."""
    env = {
        **os.environ,
        "DATABASE_URL": settings.database_url,
        "DATA_BACKEND": "snapshot",  # never StatCan or Voyage: a fresh clone has no keys
        "POISON": "",
    }
    return StdioServerParameters(
        command=sys.executable, args=["-m", "canada_agent.mcp_server"], env=env
    )


def _leaf(exc: BaseException) -> BaseException:
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


async def _timed(coro: Any, timeout_s: float) -> Any:
    return await asyncio.wait_for(coro, timeout_s)


def ask_offline(
    question: str,
    *,
    settings: Settings,
    folder: Path = RECORDED,
    server: Any = None,
    on_event: Callable[[str], None] = lambda _: None,
) -> tuple[AskResult, str]:
    """Replay a recorded run through the real tools and checks. Returns (result, source).

    `server` is anything `mcp.Client` accepts; tests pass an in-process server."""
    transcript = find(question, folder)
    start = time.monotonic()
    replay = _replay(transcript, server or stdio_server(settings), settings.max_tool_calls)
    try:
        events = asyncio.run(_timed(replay, settings.question_timeout_s))
    except BaseException as exc:  # noqa: BLE001 - classified below, never swallowed
        leaf = _leaf(exc)
        if isinstance(leaf, AskError):
            raise leaf from exc
        if isinstance(leaf, TimeoutError):
            raise AskError(
                f"over the {settings.question_timeout_s:.0f}s budget", ErrorCode.BUDGET_EXCEEDED
            ) from exc
        if isinstance(leaf, OSError | MCPError | EOFError):  # the server couldn't run
            raise AskError(f"MCP server failed: {leaf!r}", ErrorCode.UPSTREAM_UNAVAILABLE) from exc
        raise leaf from exc  # a bug (a malformed recording, say) stays a bug
    final = dict(transcript["events"][-1])
    final |= {
        "total_cost_usd": 0,
        "modelUsage": {},
        "duration_ms": int((time.monotonic() - start) * 1000),
    }
    result = run_events(
        [*events, final],
        max_tool_calls=settings.max_tool_calls,
        deadline_s=settings.question_timeout_s,
        canary=f"CANARY-{secrets.token_hex(8)}",
        on_event=on_event,
    )
    return result, transcript["path"]
