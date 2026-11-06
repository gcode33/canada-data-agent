"""Deterministic graders over recorded agent runs (SPEC 10.3, ADR 0007).

Each grader takes a parsed run and its golden case and returns a `Check`: pass or fail with
a reason a human can act on. No model is involved, so they run on committed transcripts in
every-PR CI. A case passes when every applicable check passes.

Numbers are compared up to presentation scale: StatCan stores persons, cents or thousands,
and an answer may say "5.71 million" or "$1.84". A value matches if some power-of-ten
rescaling of it lands within tolerance; the reason text names the scale used.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

STATCAN_HOST = "www150.statcan.gc.ca"
MAX_TOOL_CALLS = 8
SCALES = (1.0, 1e3, 1e6, 1e9, 1e-3, 1e-6, 1e-9, 100.0, 0.01)
NUMBER = re.compile(r"(?<![\w.])[-−]?\d[\d,]*(?:\.\d+)?")
URL = re.compile(r"https?://[^\s)\]>\"']+")


@dataclass(frozen=True)
class Check:
    ok: bool
    why: str = ""


@dataclass
class Call:
    name: str
    arguments: dict[str, Any]
    result: Any = None  # decoded JSON from the tool, or error text
    is_error: bool = False


@dataclass
class Run:
    calls: list[Call] = field(default_factory=list)
    answer: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


# --- parsing a recorded transcript ---


def _decode(content: Any) -> Any:
    """Tool results arrive as text holding {"result": "<json>"}; unwrap both layers."""
    if isinstance(content, list):
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
    if not isinstance(content, str):
        return content
    try:
        outer = json.loads(content)
    except ValueError:
        return content
    inner = outer.get("result") if isinstance(outer, dict) else None
    if isinstance(inner, str):
        try:
            return json.loads(inner)
        except ValueError:
            return inner
    return outer


def parse(transcript: dict[str, Any]) -> Run:
    run = Run(error=transcript.get("error"))
    by_id: dict[str, Call] = {}
    for event in transcript.get("events", []):
        if event.get("type") == "result":
            answer = event.get("structured_output")
            run.answer = answer if isinstance(answer, dict) else None
            continue
        for block in event.get("content") or []:
            if not isinstance(block, dict):
                continue
            name = block.get("name", "")
            if block.get("type") == "tool_use" and name.startswith("mcp__canada__"):
                call = Call(name.removeprefix("mcp__canada__"), block.get("input") or {})
                by_id[block["id"]] = call
                run.calls.append(call)
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in by_id:
                call = by_id[block["tool_use_id"]]
                call.is_error = bool(block.get("is_error"))
                call.result = _decode(block.get("content"))
    return run


# --- helpers ---


def _close(got: float, want: float, tolerance: float) -> float | None:
    """The scale at which `got` matches `want`, or None."""
    for scale in SCALES:
        if abs(got * scale - want) <= tolerance + 1e-9 * max(1.0, abs(want)):
            return scale
    return None


def _numbers(text: str) -> list[float]:
    out = []
    for raw in NUMBER.findall(text):
        try:
            out.append(float(raw.replace(",", "").replace("−", "-")))
        except ValueError:
            continue
    return out


def _periods(ref_period: str) -> list[str]:
    return [p.strip() for p in re.split(r"[/–—]| to ", ref_period) if p.strip()]


def _series(run: Run) -> list[dict[str, Any]]:
    return [
        c.result
        for c in run.calls
        if c.name == "get_series" and not c.is_error and isinstance(c.result, dict)
    ]


def _point(series: dict[str, Any], period: str) -> float | None:
    for point in series.get("points", []):
        if point.get("ref_period", "").startswith(period) and point.get("value") is not None:
            return float(point["value"])
    return None


def _recompute(label: str, first: float, last: float) -> float:
    if label == "change_pct":
        return (last - first) / first * 100
    if label == "change_abs":
        return last - first
    if label == "ratio":
        return first / last
    raise ValueError(label)


# --- the graders ---


def completed(run: Run, case: dict[str, Any]) -> Check:
    if run.error:
        return Check(False, f"run failed: {run.error.get('code')}: {run.error.get('message')}")
    if run.answer is None:
        return Check(False, "no structured answer")
    return Check(True)


def refusal(run: Run, case: dict[str, Any]) -> Check:
    should = case["expected"]["should_refuse"]
    answer = run.answer or {}
    if should and not (answer.get("refused") and not answer.get("answer_values")):
        return Check(False, "should have refused with no values")
    if not should and answer.get("refused"):
        return Check(False, "refused an answerable question")
    return Check(True)


def right_table(run: Run, case: dict[str, Any]) -> Check:
    used = {s.get("product_id") for s in _series(run)}
    missing = [t for t in case["expected"]["tables"] if t not in used]
    if missing:
        return Check(False, f"never fetched series from {missing}; used {sorted(used)}")
    return Check(True)


def values(run: Run, case: dict[str, Any]) -> Check:
    """Each expected value is in answer_values (same label, within tolerance) and in prose."""
    answer = run.answer or {}
    got = answer.get("answer_values") or []
    prose = _numbers(answer.get("answer", ""))
    for want in case["expected"]["values"]:
        matches = [
            v
            for v in got
            if v.get("label") == want["label"]
            and _close(float(v["value"]), want["value"], want["tolerance_abs"]) is not None
        ]
        if not matches:
            offered = [(v.get("label"), v.get("value")) for v in got]
            return Check(False, f"expected {want['label']} {want['value']}; got {offered}")
        value = float(matches[0]["value"])
        if not any(abs(n - value) <= 1e-9 * max(1.0, abs(value)) for n in prose) and not any(
            _close(n, want["value"], want["tolerance_abs"]) is not None for n in prose
        ):
            return Check(False, f"{value} is in answer_values but not in the prose")
    return Check(True)


def grounded(run: Run, case: dict[str, Any]) -> Check:
    """Each answer value matches points get_series returned in this run (recomputed)."""
    series_by_vector = {s.get("vector_id"): s for s in _series(run)}
    for value in (run.answer or {}).get("answer_values") or []:
        vector = value.get("vector_id")
        if not vector:
            continue  # declared as computed across series; values() still checks the number
        series = series_by_vector.get(vector)
        if series is None:
            return Check(False, f"vector {vector} was never returned by get_series")
        periods = _periods(str(value.get("ref_period", "")))
        points = [_point(series, p) for p in periods]
        if not periods or any(p is None for p in points):
            return Check(False, f"vector {vector} has no point for {value.get('ref_period')}")
        if value["label"] == "level":
            truth = points[0]
            tolerance = 1e-6 * max(1.0, abs(truth))
        else:
            if len(points) < 2:
                return Check(False, f"{value['label']} needs two periods, got {periods}")
            truth = _recompute(value["label"], points[0], points[-1])
            tolerance = 0.051 if value["label"] == "change_pct" else 0.051 * max(1.0, abs(truth))
        if _close(float(value["value"]), truth, tolerance) is None:
            return Check(False, f"{value['value']} doesn't follow from the points ({truth:.4g})")
    return Check(True)


def citations(run: Run, case: dict[str, Any]) -> Check:
    answer = run.answer or {}
    urls = list(answer.get("source_urls") or []) + URL.findall(answer.get("answer", ""))
    for url in urls:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname != STATCAN_HOST:
            return Check(False, f"non-StatCan URL: {url[:80]}")
    cited = {
        pid[:8]
        for url in answer.get("source_urls") or []
        for pid in parse_qs(urlsplit(url).query).get("pid", [])
    }
    missing = [t for t in case["expected"]["tables"] if str(t) not in cited]
    if missing:
        return Check(False, f"doesn't cite {missing}")
    return Check(True)


def trajectory(run: Run, case: dict[str, Any]) -> Check:
    if len(run.calls) > MAX_TOOL_CALLS:
        return Check(False, f"{len(run.calls)} tool calls, budget {MAX_TOOL_CALLS}")
    bad = [c.name for c in run.calls if c.is_error and "BAD_ARGUMENTS" in str(c.result)]
    if bad:
        return Check(False, f"invalid arguments to {bad}")
    return Check(True)


ANSWERABLE = (right_table, values, grounded, citations)
ALWAYS = (completed, refusal, trajectory)


def grade(transcript: dict[str, Any], case: dict[str, Any]) -> dict[str, Check]:
    run = parse(transcript)
    checks = {g.__name__: g(run, case) for g in ALWAYS}
    if not checks["completed"].ok:
        return checks
    if not case["expected"]["should_refuse"]:
        checks |= {g.__name__: g(run, case) for g in ANSWERABLE}
    else:
        checks["citations"] = (
            Check(True)
            if not (run.answer or {}).get("source_urls")
            else (citations(run, case | {"expected": case["expected"] | {"tables": []}}))
        )
    return checks


def search_recall_at_5(transcript: dict[str, Any], case: dict[str, Any]) -> float | None:
    """Did any search_tables call in the run put an expected table in its top 5?"""
    wanted = set(case["expected"]["tables"])
    if not wanted:
        return None
    for call in parse(transcript).calls:
        if call.name == "search_tables" and isinstance(call.result, dict):
            top = [r.get("product_id") for r in call.result.get("results", [])[:5]]
            if wanted & set(top):
                return 1.0
    return 0.0
