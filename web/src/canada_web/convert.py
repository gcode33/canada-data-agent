"""Raw `claude -p` stream events → the UI's events (A8 §9, ADR 0010). One converter for replays
and live runs, so both show exactly the same thing for the same run.

What reaches the browser, and how:
- **step summaries** are built from parsed integers and validated periods ("13 points, 2025-09
  to 2026-09"), never from tool text, which may carry injected instructions;
- **every published string** first goes through `display_text`: invisible and bidi characters
  are dropped and look-alike dots become ".", so a host hidden as `evil\u00ad.com` or `evilꓸcom`
  is visible to `foreign_links` (U1 security review; the same fix lands in `links.py` in U2);
- **arguments** are the model's own, cleaned with `untrusted_text`, with any outside link
  replaced by "[outside link withheld]" and length-capped;
- **series** and the **answer** are emitted only by `finish`, which the caller invokes after the
  production `run_events` checks passed; a failed run gets `fail` and a fixed message only;
- **links** are marked `linkable` here, in Python, with the agent's own `CITABLE_URL` and the
  URLs the tools returned in this run. The browser never decides.
"""

import json
import math
import re
import unicodedata
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
from canada_web.messages import failure_message

WITHHELD = "[outside link withheld]"
TOOL_CODE = re.compile(r"\b([A-Z][A-Z0-9_]{3,}):")
PERIOD = re.compile(r"^\d{4}(-\d{2}){0,2}$")
SCALAR = re.compile(r"^[a-z ]{1,24}$")
STATUS = re.compile(r"^[A-Za-z.]{1,3}$")
STEP_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# A series' name comes from the checked answer's description of one of its *level* values, with
# any period in it removed ("Ontario Rent CPI Sep 2026" names a 13-month chart "Ontario Rent CPI").
_MONTH = (
    r"(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|july?|aug(ust)?|sept?(ember)?"
    r"|oct(ober)?|nov(ember)?|dec(ember)?)\.?"
)
PERIOD_TOKEN = re.compile(
    rf"\b({_MONTH}(\s+\d{{1,2}},?)?\s+\d{{4}}|{_MONTH}(?=\s+(to|-|–)\b)|q[1-4]\s+\d{{4}}"
    rf"|\d{{4}}-\d{{2}}(/\d{{4}}-\d{{2}})?|(?<![\d.])\d{{4}}(?![\d.]))\b",
    re.I,
)
DANGLING = re.compile(r"(\s+(on|in|for|at|as of|of|to|from|between|and)|\s*[-–,(/])+\s*$", re.I)
# Characters that render as nothing (or reorder text) but can split a host name, and characters
# that look like a dot. Dropped or mapped before any check, and in everything published.
_INVISIBLE_RANGES = (
    (0x034F, 0x034F), (0x115F, 0x1160), (0x17B4, 0x17B5), (0x180B, 0x180F), (0x3164, 0x3164),
    (0xFE00, 0xFE0F), (0xFFA0, 0xFFA0), (0xE0000, 0xE0FFF),
)  # fmt: skip
DOTS = dict.fromkeys(map(ord, "\ua4f8\u2e31\u30fb\uff65\u06d4\u0964\u1427\u2024\ufe52\uff0e"), ".")
DEFANGED = re.compile(r"\s*[\[({]\s*dot\s*[\])}]\s*|%2e", re.I)


def _visible(c: str) -> bool:
    o = ord(c)
    if unicodedata.category(c) == "Cf":  # soft hyphen, zero-width, bidi controls, tags…
        return False
    return not any(lo <= o <= hi for lo, hi in _INVISIBLE_RANGES)


def display_text(text: str) -> str:
    """Text as a reader will see it, with nothing hidden: no invisible or bidi characters,
    look-alike dots as ".", and defanged dots ("[dot]", "%2e") restored, so `foreign_links`
    sees what a person would."""
    text = "".join(c for c in text if _visible(c)).translate(DOTS)
    return DEFANGED.sub(".", text)


def redact(text: str, limit: int) -> str:
    """Model or third-party text, safe to show: cleaned, outside links withheld, capped."""
    text = untrusted_text(display_text(text[: 8 * limit]), limit=4 * limit)
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


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def summary(tool: str, payload: dict[str, Any]) -> str:
    """What a successful call returned, from integers and validated periods only."""
    if tool == "search_tables":
        ids = [r.get("product_id") for r in _list(payload.get("results")) if isinstance(r, dict)]
        ids = [i for i in ids if isinstance(i, int) and not isinstance(i, bool)]
        listed = f": {', '.join(map(str, ids[:5]))}" if ids else ""
        return f"{_count(len(ids), 'table')}{listed}"[:MAX_SUMMARY]
    if tool == "get_table_dimensions":
        dims = [d for d in _list(payload.get("dimensions")) if isinstance(d, dict)]
        members = sum(len(_list(d.get("members"))) for d in dims)
        return f"{_count(len(dims), 'dimension')}, {_count(members, 'member')} shown"
    points = _list(payload.get("points"))
    periods = _periods(points)
    span = f", {periods[0]} to {periods[-1]}" if periods else ""
    return f"{_count(len(points), 'point')}{span}"


def series_label(description: str) -> str | None:
    """A chart name from a level's description, with every period token removed; None if
    nothing meaningful is left (the page then says "Series <id>")."""
    name = display_text(description[: 4 * MAX_SUMMARY])  # bounded before any regex
    name = PERIOD_TOKEN.sub(" ", name)
    name = re.sub(r"\(\s*\)", " ", name)
    name = re.sub(r"\s+([,)])", r"\1", re.sub(r"\s+", " ", name))
    name = DANGLING.sub("", name).strip(" ,-–(/")
    return redact(name, MAX_SUMMARY) if len(name) >= 3 else None


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
        if isinstance(value, float) and not math.isfinite(value):
            return None  # NaN or infinity isn't data; don't chart it (and JSON can't hold it)
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
                if tool not in TOOLS:
                    continue
                step_id = block.get("id")
                if not isinstance(step_id, str) or not STEP_ID.match(step_id):
                    raise ValueError(f"unusable tool call id {str(step_id)[:80]!r}")
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
        values = [v for v in answer.get("answer_values") or [] if isinstance(v, dict)]
        labels: dict[Any, str | None] = {}
        for v in values:  # only a level names its series; a change names a comparison
            if v.get("label") == "level" and v.get("vector_id") not in labels:
                labels[v.get("vector_id")] = series_label(str(v.get("description", "")))
        shown = [series(sid, p, labels.get(p.get("vector_id"))) for sid, p in self.series_payloads]
        links = [
            {
                "url": display_text(u),
                "linkable": bool(CITABLE_URL.fullmatch(u)) and u in self.returned_urls,
            }
            for u in answer.get("source_urls") or []
            if isinstance(u, str)
        ]
        shown_values = [
            v
            | {
                "description": display_text(str(v["description"])),
                "unit": display_text(str(v["unit"])),
            }
            for v in answer["answer_values"]
        ]
        return [
            *(s for s in shown if s is not None),
            Answer(
                type="answer",
                answer=display_text(answer["answer"]),
                answer_values=shown_values,
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
    def fail(code: FailureCode, detail: str = "") -> list[RunFailed]:
        """`detail` is the internal error text, used only to pick a fixed reason; never shown."""
        return [RunFailed(type="run_failed", code=code, message=failure_message(code, detail))]
