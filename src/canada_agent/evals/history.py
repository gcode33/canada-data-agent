"""`evals/history.jsonl`: one line per eval run, append-only (SPEC 10.7, PLAN 4.5).

Every field SPEC 10.7 names: model, prompt version, tokens (input, output, cache), USD,
p50/p95 latency and per-category scores, plus the git commit and a Wilson 95% interval,
so any number in the README can be traced to the run that produced it. USD is what the
runs would cost on the API, as `claude -p` reports it; the subscription pays (ADR 0009).
"""

import json
import math
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HISTORY = Path(__file__).resolve().parents[3] / "evals" / "history.jsonl"
REQUIRED = {
    "timestamp": str,
    "git_sha": str,
    "kind": str,
    "split": str,
    "model": str,
    "prompt_version": str,
    "n_cases": int,
    "k": int,
    "tokens": dict,
    "api_equivalent_usd": float,
    "latency_p50_s": float,
    "latency_p95_s": float,
    "pass_rate": float,
    "wilson_95": list,
    "by_category": dict,
}
TOKEN_KEYS = ("input", "output", "cache_read", "cache_creation")


def wilson(passed: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% interval for a pass rate; honest at small n, unlike +/- 1.96 * sqrt(p(1-p)/n)."""
    if n == 0:
        return (0.0, 1.0)
    p = passed / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def usage(results: list[dict[str, Any]]) -> tuple[dict[str, int], float, list[float]]:
    """Token totals, USD and per-run latency from the `result` events of transcripts."""
    tokens = dict.fromkeys(TOKEN_KEYS, 0)
    usd = 0.0
    latencies = []
    for result in results:
        usd += float(result.get("total_cost_usd") or 0)
        if result.get("duration_ms"):
            latencies.append(result["duration_ms"] / 1000)
        for model_usage in (result.get("modelUsage") or {}).values():
            tokens["input"] += model_usage.get("inputTokens", 0)
            tokens["output"] += model_usage.get("outputTokens", 0)
            tokens["cache_read"] += model_usage.get("cacheReadInputTokens", 0)
            tokens["cache_creation"] += model_usage.get("cacheCreationInputTokens", 0)
    return tokens, usd, latencies


def git_sha() -> str:
    try:
        return subprocess.run(  # noqa: S603 - fixed argv
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 - git from PATH, as make does
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def entry(
    *,
    kind: str,
    split: str,
    model: str,
    prompt_version: str,
    k: int,
    report: dict[str, Any],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    tokens, usd, latencies = usage(results)
    cases = report["cases"].values()
    passed = sum(c["passed"] for c in cases)
    low, high = wilson(passed, len(report["cases"]))
    return {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "kind": kind,
        "split": split,
        "model": model,
        "prompt_version": prompt_version,
        "n_cases": len(report["cases"]),
        "k": k,
        "tokens": tokens,
        "api_equivalent_usd": round(usd, 4),
        "latency_p50_s": round(percentile(latencies, 0.5), 1),
        "latency_p95_s": round(percentile(latencies, 0.95), 1),
        "pass_rate": round(report["pass_rate"], 4),
        "wilson_95": [round(low, 4), round(high, 4)],
        "by_category": {k: round(v, 4) for k, v in report["by_category"].items()},
        "search_recall_at_5_in_run": report.get("search_recall_at_5_in_run"),
    }


def validate(line: dict[str, Any]) -> list[str]:
    problems = [f"missing {k}" for k in REQUIRED if k not in line]
    problems += [
        f"{k} should be {t.__name__}"
        for k, t in REQUIRED.items()
        if k in line and not isinstance(line[k], t)
    ]
    if "tokens" in line and set(line["tokens"]) != set(TOKEN_KEYS):
        problems.append(f"tokens must have exactly {TOKEN_KEYS}")
    return problems


def append(line: dict[str, Any], path: Path = HISTORY) -> None:
    problems = validate(line)
    if problems:
        raise ValueError(f"bad history line: {problems}")
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, sort_keys=True) + "\n")
