"""Raw `claude -p` stream events → the UI's events (A8 §9, ADR 0010). One converter for replays
and live runs, so both show exactly the same thing for the same run.

What reaches the browser, and how:
- **step summaries** are built from parsed integers and validated periods ("13 points, 2025-09
  to 2026-09"), never from tool text, which may carry injected instructions;
- **arguments** are the model's own, cleaned with `untrusted_text`, with any outside link
  replaced by "[outside link withheld]" and length-capped;
- **series** and the **answer** are emitted only by `finish`, which the caller invokes after the
  production `run_events` checks passed; a failed run gets `fail` and a fixed message only;
- **links** are marked `linkable` here, in Python, with the agent's own `CITABLE_URL` and the
  URLs the tools returned in this run. The browser never decides.
"""

import json
import re
from typing import Any

from canada_agent.ask import TOOL_PREFIX, TOOLS, _payloads
from canada_agent.links import CITABLE_URL, foreign_links
from canada_agent.series.service import table_url
from canada_agent.untrusted import untrusted_text

from canada_web.events import (
    MAX_ARGUMENTS,
    MAX_SUMMARY,
    Answer,
    FailureCode,
    RunFailed,
    RunFinished,
    Series,
    StepFinished,
    StepStarted,
    ToolErrorCode,
)
from canada_web.messages import FAILURE_MESSAGES

WITHHELD = "[outside link withheld]"
TOOL_CODE = re.compile(r"\b([A-Z][A-Z0-9_]{3,}):")
PERIOD = re.compile(r"^\d{4}(-\d{2}){0,2}$")
SCALAR = re.compile(r"^[a-z ]{1,24}$")
STATUS = re.compile(r"^[A-Za-z.]{1,3}$")
# A series' name is taken from the checked answer's description of one of its values, which
# usually ends with that value's period ("Ontario Rent CPI Sep 2026"); a chart spans many.
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
PERIOD_SUFFIX = re.compile(
    rf"[\s,(-]*(({_MONTH}\s+)?\d{{4}}(-\d{{2}})?|{_MONTH}\s+\d{{1,2}},?\s+\d{{4}}|\b{_MONTH})\)?\s*$",
    re.I,
)


def redact(text: str, limit: int) -> str:
    """Model or third-party text, safe to show: cleaned, outside links withheld, capped."""
    text = untrusted_text(text, limit=4 * limit)
    for hit in sorted(set(foreign_links({"t": text})), key=len, reverse=True):
        text = text.replace(hit, WITHHELD)
    if foreign_links({"t": text}):  # a hit found only after normalising: withhold it all
        return WITHHELD
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _blocks(event: dict[str, Any]) -> list[dict[str, Any]]:
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else event.get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def tool_error_code(content: Any) -> ToolErrorCode:
    for m in TOOL_CODE.finditer(str(content)):
        if m.group(1) in ToolErrorCode.__members__:
            return ToolErrorCode(m.group(1))
    return ToolErrorCode.TOOL_ERROR


def _periods(points: list[Any]) -> list[str]:
    return [
        p["ref_period"]
        for p in points
        if isinstance(p, dict)
        and isinstance(p.get("ref_period"), str)
        and PERIOD.match(p["ref_period"])
    ]


def summary(tool: str, payload: dict[str, Any]) -> str:
    """What a successful call returned, from integers and validated periods only."""
    if tool == "search_tables":
        ids = [r.get("product_id") for r in payload.get("results") or [] if isinstance(r, dict)]
        ids = [i for i in ids if isinstance(i, int) and not isinstance(i, bool)]
        listed = f": {', '.join(map(str, ids[:5]))}" if ids else ""
        return f"{len(ids)} tables{listed}"[:MAX_SUMMARY]
    if tool == "get_table_dimensions":
        dims = [d for d in payload.get("dimensions") or [] if isinstance(d, dict)]
        members = sum(len(d.get("members") or []) for d in dims)
        return f"{len(dims)} dimensions, {members} members shown"
    points = payload.get("points") or []
    periods = _periods(points)
    span = f", {periods[0]} to {periods[-1]}" if periods else ""
    return f"{len(points)} points{span}"


def series_label(description: str) -> str:
    """A chart name from a value's description, without that one value's period."""
    name, before = description, None
    while name != before:  # peel "Sep 2025 to Sep 2026", "on July 1, 2026", "(2026-08)"
        before = name
        name = PERIOD_SUFFIX.sub("", name).strip(" ,-–(")
        name = re.sub(r"\s+(on|in|for|at|as of|of|to|from|between|and)$", "", name, flags=re.I)
    return redact(name or description, MAX_SUMMARY)


def series(step_id: str, payload: dict[str, Any], label: str | None) -> Series | None:
    """A chartable series from a `get_series` result, every field validated; None if unusable."""
    pid, vid = payload.get("product_id"), payload.get("vector_id")
    if not (isinstance(pid, int) and isinstance(vid, int)) or isinstance(pid, bool):
        return None
    points = []
    for p in payload.get("points") or []:
        if not isinstance(p, dict) or not (
            isinstance(p.get("ref_period"), str) and PERIOD.match(p["ref_period"])
        ):
            continue
        value = p.get("value")
        status = p.get("status_symbol")
        points.append(
            {
                "ref_period": p["ref_period"],
                "value": float(value)
                if isinstance(value, int | float) and not isinstance(value, bool)
                else None,
                "status_symbol": status
                if isinstance(status, str) and STATUS.match(status)
                else None,
            }
        )
    scalar = payload.get("scalar_factor")
    try:
        return Series(
            type="series",
            step_id=step_id,
            product_id=pid,
            table_url=table_url(pid),
            vector_id=vid,
            scalar_factor=scalar if isinstance(scalar, str) and SCALAR.match(scalar) else "unknown",
            truncated=bool(payload.get("truncated")),
            label=label,
            points=points,
        )
    except ValueError:  # pydantic: out-of-range id, too many points
        return None


class Converter:
    """Feed raw stream events in order; then `finish` (checks passed) or `fail`."""

    def __init__(self) -> None:
        self.tools: dict[str, str] = {}  # step id -> tool name
        self.started_ms: dict[str, int] = {}
        self.series_payloads: list[tuple[str, dict[str, Any]]] = []
        self.returned_urls: set[str] = set()

    def feed(self, event: dict[str, Any]) -> list[StepStarted | StepFinished]:
        out: list[StepStarted | StepFinished] = []
        t_ms = event.get("t_ms") if isinstance(event.get("t_ms"), int) else None
        for block in _blocks(event):
            name = str(block.get("name", ""))
            if block.get("type") == "tool_use" and name.startswith(TOOL_PREFIX):
                tool = name.removeprefix(TOOL_PREFIX)
                if tool not in TOOLS or not isinstance(block.get("id"), str):
                    continue
                step_id = block["id"][:64]
                self.tools[step_id] = tool
                if t_ms is not None:
                    self.started_ms[step_id] = t_ms
                args = json.dumps(block.get("input") or {}, sort_keys=True, ensure_ascii=False)
                out.append(
                    StepStarted(
                        type="step_started",
                        step_id=step_id,
                        tool=tool,
                        arguments_text=redact(args, MAX_ARGUMENTS),
                    )
                )
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in self.tools:
                step_id = block["tool_use_id"]
                tool = self.tools[step_id]
                content = block.get("content")
                failed = bool(block.get("is_error"))
                payloads = [] if failed else list(_payloads(content))
                if not failed:
                    self.returned_urls.update(
                        m.group(0) for m in CITABLE_URL.finditer(str(content))
                    )
                    if tool == "get_series":
                        self.series_payloads += [(step_id, p) for p in payloads]
                start = self.started_ms.get(step_id)
                code = tool_error_code(content) if failed else None
                out.append(
                    StepFinished(
                        type="step_finished",
                        step_id=step_id,
                        ok=not failed,
                        latency_ms=t_ms - start if t_ms is not None and start is not None else None,
                        error_code=code,
                        summary=f"error: {code}"
                        if failed
                        else summary(tool, payloads[0] if payloads else {}),
                    )
                )
        return out

    def finish(
        self,
        answer: dict[str, Any],
        *,
        num_turns: int,
        duration_ms: int,
        usd: float | None,
        billed: str,
    ) -> list[Series | Answer | RunFinished]:
        """Only call this after `run_events` accepted the answer."""
        labels: dict[Any, str] = {}
        values = [v for v in answer.get("answer_values") or [] if isinstance(v, dict)]
        # A level's description names the series; a change's names a comparison.
        for v in sorted(values, key=lambda v: v.get("label") != "level"):
            if v.get("vector_id") not in labels:
                labels[v.get("vector_id")] = series_label(str(v.get("description", "")))
        shown = [series(sid, p, labels.get(p.get("vector_id"))) for sid, p in self.series_payloads]
        links = [
            {"url": u, "linkable": bool(CITABLE_URL.fullmatch(u)) and u in self.returned_urls}
            for u in answer.get("source_urls") or []
            if isinstance(u, str)
        ]
        return [
            *(s for s in shown if s is not None),
            Answer(
                type="answer",
                answer=answer["answer"],
                answer_values=answer["answer_values"],
                links=links,
                refused=answer["refused"],
            ),
            RunFinished(
                type="run_finished",
                num_turns=num_turns,
                duration_ms=duration_ms,
                api_equivalent_usd=usd,
                billed=billed,
            ),
        ]

    @staticmethod
    def fail(code: FailureCode) -> list[RunFailed]:
        return [RunFailed(type="run_failed", code=code, message=FAILURE_MESSAGES[code])]
