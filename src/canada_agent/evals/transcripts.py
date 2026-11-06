"""`canada-transcripts`: run golden cases through the real agent and record what happened.

Each run is saved to evals/transcripts/<split>/<case>.json, so graders can run offline in
every-PR CI with no model. The data comes from the snapshot, so answers are stable. Voyage
is still called if a key is set (ADR 0009 note in FINDINGS-LOG), and each result says
whether retrieval was degraded. Resumable: cases already recorded are skipped, and a
subscription usage limit stops the run cleanly.
"""

import argparse
import json
import sys
from typing import Any

from canada_agent import ask as agent
from canada_agent.config import Settings
from canada_agent.evals.lint import GOLDEN, load

TRANSCRIPTS = GOLDEN.parents[1] / "transcripts"


def slim(event: dict[str, Any]) -> dict[str, Any] | None:
    """Keep what graders need; drop session ids and anything else that varies per run."""
    kind = event.get("type")
    if kind == "result":
        keys = ("type", "subtype", "is_error", "structured_output", "num_turns", "duration_ms")
        return {k: event[k] for k in (*keys, "total_cost_usd", "modelUsage") if k in event}
    if kind in ("assistant", "user"):
        blocks = event.get("message", {}).get("content")
        return {"type": kind, "content": blocks} if isinstance(blocks, list) else None
    return None


def record(case: dict[str, Any], model: str, settings: Settings) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    outcome: dict[str, Any] = {"case": case["id"], "question": case["question"], "model": model}
    outcome["prompt_version"] = agent.PROMPT_VERSION
    try:
        agent.ask(case["question"], model=model, settings=settings, capture=events)
        outcome["error"] = None
    except agent.UsageLimitError:
        raise
    except agent.AskError as exc:
        outcome["error"] = {"code": str(exc.code) if exc.code else None, "message": str(exc)[:300]}
    outcome["events"] = [e for e in map(slim, events) if e]
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="dev", choices=["dev", "test"])
    parser.add_argument("--model")
    parser.add_argument("--only", help="comma-separated case ids")
    args = parser.parse_args()
    settings = Settings(data_backend="snapshot")
    model = args.model or settings.agent_model
    folder = TRANSCRIPTS / args.split
    folder.mkdir(parents=True, exist_ok=True)
    only = set(args.only.split(",")) if args.only else None
    cases = [c for c in load(GOLDEN) if c["split"] == args.split]
    for case in cases:
        if only and case["id"] not in only:
            continue
        path = folder / f"{case['id']}.json"
        if path.exists() and not only:
            continue
        try:
            outcome = record(case, model, settings)
        except agent.UsageLimitError as exc:
            sys.exit(f"stopped at {case['id']}: {exc}; rerun after the reset to resume")
        path.write_text(json.dumps(outcome, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(case["id"], (outcome["error"] or {}).get("code") or "recorded", flush=True)
