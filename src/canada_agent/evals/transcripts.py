"""`canada-transcripts`: run golden cases through the real agent and record what happened.

Each run is saved as JSON, so graders can run offline in every-PR CI with no model. Runs
use the snapshot (`DATA_BACKEND=snapshot`), where the MCP server builds no StatCan or
Voyage client: Claude is the only outside service a run reaches (PLAN 4.3). Search then
uses full-text plus recorded query vectors, and every search says whether it was degraded.

Each transcript is stamped with the question, prompt version, git commit (and whether the
tree was dirty) and wall-clock seconds, so `canada-grade --check` can refuse stale ones.
Resumable: successful recordings are skipped, failed ones are retried, files are written
atomically, and a subscription usage limit stops the run cleanly.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from canada_agent import ask as agent
from canada_agent.config import Settings
from canada_agent.evals.lint import GOLDEN, load
from canada_agent.evals.poison import spec_for as poison_spec

TRANSCRIPTS = GOLDEN.parents[1] / "transcripts"


def git_state() -> tuple[str, bool]:
    """(short sha, dirty) of the code that produced a run."""
    try:
        sha = subprocess.run(  # noqa: S603 - fixed argv
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 - git from PATH
            capture_output=True, text=True, check=True,
        ).stdout.strip()  # fmt: skip
        dirty = subprocess.run(  # noqa: S603
            ["git", "status", "--porcelain", "--", "src", "evals/golden", "snapshots"],  # noqa: S607
            capture_output=True, text=True, check=True,
        ).stdout.strip() != ""  # fmt: skip
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True
    return sha, dirty


def slim(event: dict[str, Any]) -> dict[str, Any] | None:
    """Keep what graders need; drop session ids, thinking blocks and their signatures."""
    kind = event.get("type")
    if kind == "result":
        keys = ("type", "subtype", "is_error", "structured_output", "num_turns", "duration_ms")
        return {k: event[k] for k in (*keys, "total_cost_usd", "modelUsage") if k in event}
    if kind in ("assistant", "user"):
        blocks = event.get("message", {}).get("content")
        if not isinstance(blocks, list):
            return None
        kept = [b for b in blocks if not (isinstance(b, dict) and b.get("type") == "thinking")]
        return {"type": kind, "content": kept} if kept else None
    return None


def record(
    case: dict[str, Any], model: str, settings: Settings, poison: str | None = None
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    sha, dirty = git_state()
    outcome: dict[str, Any] = {
        "case": case["id"],
        "question": case["question"],
        "model": model,
        "prompt_version": agent.PROMPT_VERSION,
        "git_sha": sha,
        "git_dirty": dirty,
        "poison": poison,
    }
    started = time.monotonic()
    run_settings = settings.model_copy(update={"poison": poison or ""})
    try:
        agent.ask(case["question"], model=model, settings=run_settings, capture=events)
        outcome["error"] = None
    except agent.UsageLimitError:
        raise
    except agent.AskError as exc:
        outcome["error"] = {"code": str(exc.code) if exc.code else None, "message": str(exc)[:300]}
    outcome["wall_s"] = round(time.monotonic() - started, 1)
    outcome["events"] = [e for e in map(slim, events) if e]
    return outcome


def write_atomic(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)  # a kill mid-write can't leave a half-written transcript


def recorded_ok(path: Path) -> bool:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("error") is None
    except (OSError, ValueError):
        return False


def record_cases(
    cases: list[dict[str, Any]],
    folder: Path,
    *,
    model: str,
    settings: Settings,
    force: bool = False,
    poison_for: Any = poison_spec,
) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for case in cases:
        path = folder / f"{case['id']}.json"
        if not force and recorded_ok(path):
            continue
        try:
            outcome = record(case, model, settings, poison_for(case))
        except agent.UsageLimitError as exc:
            sys.exit(f"stopped at {case['id']}: {exc}; rerun after the reset to resume")
        write_atomic(path, outcome)
        print(case["id"], (outcome["error"] or {}).get("code") or "recorded", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="dev", choices=["dev", "test"])
    parser.add_argument("--model")
    parser.add_argument("--only", help="comma-separated case ids")
    parser.add_argument("--force", action="store_true", help="re-record even successful runs")
    args = parser.parse_args()
    settings = Settings(data_backend="snapshot")
    only = set(args.only.split(",")) if args.only else None
    cases = [c for c in load(GOLDEN) if c["split"] == args.split and (not only or c["id"] in only)]
    record_cases(
        cases,
        TRANSCRIPTS / args.split,
        model=args.model or settings.agent_model,
        settings=settings,
        force=args.force or bool(only),
        poison_for=poison_spec,
    )
