"""`canada-ask --offline`: the whole pipeline with a recorded model, for a clone with no key.

The model's choices (which tools to call, with what arguments, and the final answer) are
replayed from a committed transcript in `evals/transcripts/dev/`. Everything else is real:
our MCP server starts over stdio on the snapshot, every tool call runs against it, and
`run_events` applies the same budget, canary, link and grounding checks as a live run. If
the snapshot or the tools no longer return what the recorded answer cites, the run fails
the way a live one would.

It proves the plumbing works on a fresh machine. It says nothing about the model.
"""

import asyncio
import json
import os
import re
import secrets
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp import StdioServerParameters
from mcp.client.client import Client

from canada_agent.ask import TOOL_PREFIX, TOOLS, AskError, AskResult, run_events
from canada_agent.config import Settings
from canada_agent.errors import ErrorCode
from canada_agent.evals.transcripts import TRANSCRIPTS
from canada_agent.mcp_server import SERVER_NAME

RECORDED = TRANSCRIPTS / "dev"
REPO = TRANSCRIPTS.parents[1]


def _key(question: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", question.casefold()).strip()


def recordings(folder: Path = RECORDED) -> dict[str, dict[str, Any]]:
    """Replayable runs by question: unpoisoned, unerrored, and ending in a result."""
    found = {}
    for path in sorted(folder.glob("*.json")):
        t = json.loads(path.read_text(encoding="utf-8"))
        events = t.get("events") or []
        if t.get("poison") or t.get("error") or not events or events[-1].get("type") != "result":
            continue
        shown = path.relative_to(REPO) if path.is_relative_to(REPO) else path
        found[_key(t["question"])] = t | {"path": str(shown)}
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


async def _replay(transcript: dict[str, Any], server: Any) -> list[dict[str, Any]]:
    """Run the recorded tool calls against the server; return live stream events."""
    events: list[dict[str, Any]] = []
    async with Client(server) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        status = "connected" if names >= set(TOOLS) else f"missing {sorted(set(TOOLS) - names)}"
        events.append(
            {"type": "system", "subtype": "init",
             "mcp_servers": [{"name": SERVER_NAME, "status": status}]}
        )  # fmt: skip
        for recorded in transcript["events"][:-1]:
            for block in _blocks(recorded):
                if block.get("type") != "tool_use" or not block["name"].startswith(TOOL_PREFIX):
                    continue
                events.append({"type": "assistant", "message": {"content": [block]}})
                result = await client.call_tool(
                    block["name"].removeprefix(TOOL_PREFIX), block.get("input") or {}
                )
                text = "".join(getattr(c, "text", "") for c in result.content)
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
    try:
        events = asyncio.run(_replay(transcript, server or stdio_server(settings)))
    except Exception as exc:  # the server failing to start is an outage, not a refusal
        raise AskError(f"MCP server failed: {exc}", ErrorCode.UPSTREAM_UNAVAILABLE) from exc
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
