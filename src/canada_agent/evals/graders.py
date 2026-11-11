"""Deterministic graders over recorded agent runs (SPEC 10.3, ADR 0007).

Each grader takes a parsed run and its golden case and returns a `Check`: pass or fail with
a reason a human can act on. No model is involved, so they run on committed transcripts in
every-PR CI. A case passes when every applicable check passes.

The rules after the Phase 4 adversarial review (each closes a demonstrated bypass):
- An expected value must come from **the golden series** (its coordinate) at **the golden
  periods**, at the scale StatCan stores. Coincidences in other months, numbers from
  memory with `vector_id: 0`, and "650%" for 6.5% all fail.
- The prose must state the same number. Only there may it be rescaled, and only with a
  scale word ("5.71 million"), matched to the precision written. A change's sign may be
  carried by a word ("fell 0.6 points").
- Multi-step answers must name the right entity, with each number beside its own entity.
- Refusals may state no figures, and no answer may contain a non-StatCan link or domain.
- Harness gaps (SNAPSHOT_MISS) and invalid tool calls fail the case.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

MAX_TOOL_CALLS = 8
CITABLE_URL = re.compile(r"https://www150\.statcan\.gc\.ca/t1/tbl1/en/tv\.action\?pid=(\d{8})01")
ANY_URL = re.compile(r"[a-z][a-z0-9+.-]*://[^\s)\]>\"']+", re.IGNORECASE)
DOMAIN = re.compile(
    r"\b(?:[a-z0-9-]+\.)+(?:com|net|org|io|co|ru|cn|xyz|info|biz|me|dev|app|ly|gg|ai|"
    r"site|top|link|click|example|ca|gc\.ca)\b",
    re.IGNORECASE,
)
ALLOWED_DOMAIN = "www150.statcan.gc.ca"
NUMBER = re.compile(r"(?<![\w.])([-−]?)(\d[\d,]*(?:\.\d+)?)(\s*(?:million|thousand|billion|k)\b)?",
                    re.IGNORECASE)  # fmt: skip
SCALE_WORDS = {"thousand": 1e3, "k": 1e3, "million": 1e6, "billion": 1e9}
TOOL_ERRORS = ("BAD_ARGUMENTS", "validation error", "unknown argument", "Input validation")
YEAR = re.compile(r"^(19|20)\d\d$")
CLAUSE = re.compile(
    r"[.;,:]\s|\s(?:and|but|versus|vs\.?|than|while|whereas|compared (?:with|to))\s",
    re.IGNORECASE,
)


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


def coordinate(members: dict[Any, Any]) -> str:
    """Golden members as WDS's 10-position coordinate (independent of the series code)."""
    ids = [str(members[k]) for k in sorted(members, key=int)]
    return ".".join(ids + ["0"] * (10 - len(ids)))


def _series(run: Run) -> list[dict[str, Any]]:
    return [
        c.result
        for c in run.calls
        if c.name == "get_series" and not c.is_error and isinstance(c.result, dict)
    ]


def _point(series: dict[str, Any], period: str) -> float | None:
    """The value at a golden period: YYYY-MM exactly, or a bare year for annual tables."""
    for point in series.get("points", []):
        ref = str(point.get("ref_period", ""))
        if (ref == period or (len(period) == 4 and ref[:4] == period)) and point.get(
            "value"
        ) is not None:
            return float(point["value"])
    return None


def _value_periods(ref_period: str) -> list[str]:
    return [p.strip() for p in re.split(r"[/–—]| to ", ref_period) if p.strip()]


def _same_periods(answer_period: str, golden: list[str]) -> bool:
    """`2025-09/2026-09` matches golden ["2025-09", "2026-09"]; `2026-07-01` matches
    "2026-07"; a year matches an annual golden period."""
    got = _value_periods(answer_period)
    if len(got) != len(golden):
        return False
    return all(p == g or p[: len(g)] == g for p, g in zip(got, golden, strict=True))


def _recompute(label: str, first: float, last: float) -> float | None:
    if label == "change_pct":
        return (last - first) / first * 100 if first else None
    if label == "change_abs":
        return last - first
    if label == "ratio":
        return first / last if last else None
    return None


def _prose_numbers(text: str) -> list[tuple[float, float, int, int]]:
    """(value, step, start, end) for each number in prose, rescaled by any scale word.
    `step` is the unit of the last digit shown, so "5.71 million" matches 5,710,598."""
    out = []
    for m in NUMBER.finditer(text):
        sign, digits, word = m.group(1), m.group(2).replace(",", ""), (m.group(3) or "").strip()
        try:
            number = float(digits)
        except ValueError:
            continue
        scale = SCALE_WORDS.get(word.casefold(), 1.0)
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        step = scale * 10**-decimals
        value = (-number if sign else number) * scale
        out.append((value, step, m.start(), m.end()))
    return out


def _stated(text: str, value: float, tolerance: float) -> list[tuple[int, int]]:
    """Where the prose states `value` (sign may be in words), at the precision written."""
    spans = []
    for number, step, start, end in _prose_numbers(text):
        if abs(abs(number) - abs(value)) <= max(step / 2, tolerance) + 1e-9:
            spans.append((start, end))
    return spans


# --- the graders ---


def completed(run: Run, case: dict[str, Any]) -> Check:
    if run.error:
        return Check(False, f"run failed: {run.error.get('code')}: {run.error.get('message')}")
    if run.answer is None:
        return Check(False, "no structured answer")
    return Check(True)


def harness(run: Run, case: dict[str, Any]) -> Check:
    """SPEC 10.6: a snapshot gap fails the case; it must never steer the agent unnoticed."""
    misses = [c.name for c in run.calls if c.is_error and "SNAPSHOT_MISS" in str(c.result)]
    if misses:
        return Check(False, f"SNAPSHOT_MISS in {misses}: the snapshot doesn't cover this run")
    return Check(True)


def refusal(run: Run, case: dict[str, Any]) -> Check:
    should = case["expected"]["should_refuse"]
    answer = run.answer or {}
    if should:
        if not answer.get("refused") or answer.get("answer_values"):
            return Check(False, "should have refused with no values")
        figures = [
            text[s:e]
            for text in [answer.get("answer", "")]
            for _, _, s, e in _prose_numbers(text)
            if not YEAR.match(text[s:e])
        ]
        if figures:
            return Check(False, f"a refusal may not state figures: {figures[:3]}")
    elif answer.get("refused"):
        return Check(False, "refused an answerable question")
    return Check(True)


def trajectory(run: Run, case: dict[str, Any]) -> Check:
    if len(run.calls) > MAX_TOOL_CALLS:
        return Check(False, f"{len(run.calls)} tool calls, budget {MAX_TOOL_CALLS}")
    bad = [c.name for c in run.calls if c.is_error and any(e in str(c.result) for e in TOOL_ERRORS)]
    if bad:
        return Check(False, f"invalid arguments to {bad}")
    return Check(True)


def links(run: Run, case: dict[str, Any]) -> Check:
    """No link or domain other than StatCan anywhere in the answer, any case, any field."""
    text = json.dumps(run.answer or {}, ensure_ascii=False)
    for url in ANY_URL.findall(text):
        if not CITABLE_URL.fullmatch(url.rstrip(".,;")):
            return Check(False, f"link that isn't a StatCan table URL: {url[:80]}")
    for domain in DOMAIN.findall(text):
        if domain.casefold() != ALLOWED_DOMAIN:
            return Check(False, f"non-StatCan domain in the answer: {domain}")
    return Check(True)


def right_series(run: Run, case: dict[str, Any]) -> Check:
    """Every expected series was fetched (table and coordinate), not just its table."""
    fetched = {(s.get("product_id"), s.get("coordinate")) for s in _series(run)}
    for want in case["expected"]["values"]:
        key = (want["table"], coordinate(want["members"]))
        if key not in fetched:
            return Check(False, f"never fetched {key}; fetched {sorted(fetched)}")
    return Check(True)


def values(run: Run, case: dict[str, Any]) -> Check:
    """Each expected value: in answer_values from the golden series and periods, at stored
    scale and within tolerance, and stated in the prose."""
    answer = run.answer or {}
    by_coordinate = {s.get("coordinate"): s for s in _series(run)}
    prose = answer.get("answer", "")
    for want in case["expected"]["values"]:
        series = by_coordinate.get(coordinate(want["members"])) or {}
        vector = series.get("vector_id")
        matches = [
            v
            for v in answer.get("answer_values") or []
            if v.get("label") == want["label"]
            and vector
            and v.get("vector_id") == vector
            and _same_periods(str(v.get("ref_period", "")), want["ref_periods"])
            and abs(float(v.get("value", "nan")) - want["value"]) <= want["tolerance_abs"] + 1e-9
        ]
        if not matches:
            offered = [
                (v.get("label"), v.get("value"), v.get("vector_id"), v.get("ref_period"))
                for v in answer.get("answer_values") or []
            ]
            return Check(
                False,
                f"expected {want['label']} {want['value']} from vector {vector} for "
                f"{want['ref_periods']}; got {offered}",
            )
        if not _stated(prose, float(matches[0]["value"]), want["tolerance_abs"]):
            return Check(False, f"{matches[0]['value']} is in answer_values but not in the prose")
    return Check(True)


def grounded(run: Run, case: dict[str, Any]) -> Check:
    """Every answer value (expected or extra) follows from points returned in this run."""
    series_by_vector = {s.get("vector_id"): s for s in _series(run)}
    for value in (run.answer or {}).get("answer_values") or []:
        vector = value.get("vector_id")
        label = value.get("label")
        if not vector:
            if label == "level":
                return Check(False, f"level {value.get('value')} cites no series")
            continue  # a cross-series change; `values` binds every expected number
        series = series_by_vector.get(vector)
        if series is None:
            return Check(False, f"vector {vector} was never returned by get_series")
        periods = _value_periods(str(value.get("ref_period", "")))
        points = [_point(series, p) for p in periods]
        if not periods or any(p is None for p in points):
            return Check(False, f"vector {vector} has no point for {value.get('ref_period')}")
        if label == "level":
            truth, tolerance = points[0], 1e-6 * max(1.0, abs(points[0]))
        else:
            if len(points) < 2:
                return Check(False, f"{label} needs two periods, got {periods}")
            truth = _recompute(label, points[0], points[-1])
            if truth is None:
                return Check(False, f"{label} is undefined for these points (division by zero)")
            tolerance = 0.051 if label == "change_pct" else 0.051 * max(1.0, abs(truth))
        if abs(float(value.get("value", "nan")) - truth) > tolerance:
            return Check(
                False, f"{value.get('value')} doesn't follow from the points ({truth:.4g})"
            )
    return Check(True)


def citations(run: Run, case: dict[str, Any]) -> Check:
    cited = {
        m.group(1)
        for url in (run.answer or {}).get("source_urls") or []
        if (m := CITABLE_URL.fullmatch(url))
    }
    missing = [t for t in case["expected"]["tables"] if str(t) not in cited]
    if missing:
        return Check(False, f"doesn't cite {missing}")
    return Check(True)


def conclusion(run: Run, case: dict[str, Any]) -> Check:
    """Multi-step: the first entity named in the first sentence is the right one, and each
    number is never given for the other entity in a clause naming only that one (a
    swap). Deliberately strict: "Quebec
    was lower than Ontario" fails even though it's correct (ADR 0007)."""
    winner = case["expected"].get("answer_entity")
    if not winner:
        return Check(True)
    prose = (run.answer or {}).get("answer", "")
    lowered = prose.casefold()
    entities = [v["entity"] for v in case["expected"]["values"]]
    first = lowered.split(". ")[0]
    named = sorted((first.find(e.casefold()), e) for e in entities if e.casefold() in first)
    if not named or named[0][1] != winner:
        return Check(False, f"the first sentence doesn't lead with {winner!r}")
    for clause in CLAUSE.split(prose):
        lowered_clause = clause.casefold()
        present = {e for e in entities if e.casefold() in lowered_clause}
        if len(present) != 1:
            continue  # names neither entity (e.g. "a gap of 7.0 - 6.0") or both: no claim
        (named,) = present
        for want in case["expected"]["values"]:
            if want["entity"] != named and _stated(clause, want["value"], want["tolerance_abs"]):
                own = [w for w in case["expected"]["values"] if w["entity"] == named]
                if not any(_stated(clause, w["value"], w["tolerance_abs"]) for w in own):
                    return Check(
                        False, f"{want['value']} is given for {named!r}, not {want['entity']!r}"
                    )
    return Check(True)


ANSWERABLE = (right_series, values, grounded, citations, conclusion)
ALWAYS = (completed, harness, refusal, trajectory, links)


def grade(transcript: dict[str, Any], case: dict[str, Any]) -> dict[str, Check]:
    run = parse(transcript)
    checks = {g.__name__: g(run, case) for g in ALWAYS}
    if not checks["completed"].ok:
        return checks
    if not case["expected"]["should_refuse"]:
        checks |= {g.__name__: g(run, case) for g in ANSWERABLE}
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


def degraded_searches(transcript: dict[str, Any]) -> tuple[int, int]:
    """(degraded, total) search_tables calls, so recall can't hide which search ran."""
    calls = [c for c in parse(transcript).calls if c.name == "search_tables"]
    degraded = sum(
        isinstance(c.result, dict) and bool(c.result.get("degraded_retrieval")) for c in calls
    )
    return degraded, len(calls)
