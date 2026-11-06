"""`canada-grade`: grade recorded transcripts against the golden set, with no model.

- A case with no transcript, or a stale one (question or prompt changed since recording),
  fails; it is never skipped.
- Injection cases count only when their run was actually poisoned (PLAN 5.3); until then
  the category reports n/a instead of an empty 1.0.
- `--check` compares the verdicts with the pinned manifest `evals/grades/<split>.json` and
  exits 1 on any difference, so a grader change, a stale transcript or a newly failing case
  can't pass CI unnoticed. `--write` updates the manifest (a reviewed commit).
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from canada_agent import ask as agent
from canada_agent.evals import history
from canada_agent.evals.graders import degraded_searches, grade, search_recall_at_5
from canada_agent.evals.lint import GOLDEN, load
from canada_agent.evals.poison import spec_for
from canada_agent.evals.transcripts import TRANSCRIPTS

GRADES = GOLDEN.parents[1] / "grades"


def counts(case: dict[str, Any], transcript: dict[str, Any] | None) -> bool:
    """Whether a case counts toward pass rates: injection only once it was really poisoned."""
    return case["category"] != "injection" or bool(transcript and transcript.get("poison"))


def grade_case(case: dict[str, Any], transcript: dict[str, Any] | None) -> dict[str, Any]:
    base = {"category": case["category"], "counted": counts(case, transcript)}
    if transcript is None:
        return base | {"passed": False, "failed": {"recorded": "no transcript"}}
    stale = []
    if transcript.get("question") != case["question"]:
        stale.append("question changed since recording")
    if transcript.get("prompt_version") != agent.PROMPT_VERSION:
        stale.append(f"recorded with prompt {transcript.get('prompt_version')}")
    if (transcript.get("poison") or None) != spec_for(case):
        stale.append("poison changed since recording")
    checks = grade(transcript, case)
    failed = {name: c.why for name, c in checks.items() if not c.ok}
    if stale:
        failed["stale"] = "; ".join(stale)
    degraded, searches = degraded_searches(transcript)
    return base | {
        "errored": bool(transcript.get("error")),
        "passed": not failed,
        "failed": failed,
        "search_recall_at_5": search_recall_at_5(transcript, case),
        "searches": searches,
        "degraded_searches": degraded,
    }


def load_transcripts(folder: Path) -> dict[str, dict[str, Any]]:
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))
    }


def summarise(results: dict[str, dict[str, Any]], split: str) -> dict[str, Any]:
    counted = {k: r for k, r in results.items() if r["counted"]}
    by_category: dict[str, list[bool]] = defaultdict(list)
    for r in results.values():
        by_category[r["category"]].append(r["passed"])
    recalls = [
        r["search_recall_at_5"] for r in counted.values() if r.get("search_recall_at_5") is not None
    ]
    return {
        "split": split,
        "cases": results,
        "n_counted": len(counted),
        "pass_rate": sum(r["passed"] for r in counted.values()) / len(counted) if counted else 0.0,
        "by_category": {
            k: (
                sum(v) / len(v)
                if any(results[c]["counted"] for c in results if results[c]["category"] == k)
                else None
            )
            for k, v in sorted(by_category.items())
        },
        "search_recall_at_5_in_run": sum(recalls) / len(recalls) if recalls else None,
        "searches": sum(r.get("searches", 0) for r in counted.values()),
        "degraded_searches": sum(r.get("degraded_searches", 0) for r in counted.values()),
    }


def grade_split(split: str, folder: Path | None = None) -> dict[str, Any]:
    folder = folder or TRANSCRIPTS / split
    transcripts = load_transcripts(folder)
    cases = [c for c in load(GOLDEN) if c["split"] == split]
    return summarise({c["id"]: grade_case(c, transcripts.get(c["id"])) for c in cases}, split)


def verdicts(report: dict[str, Any]) -> dict[str, Any]:
    """The pinned part of a report: who passed, and why each failure failed."""
    return {
        case_id: {"passed": r["passed"], "failed": sorted(r["failed"]), "counted": r["counted"]}
        for case_id, r in report["cases"].items()
    }


def history_line(report: dict[str, Any], transcripts: list[dict[str, Any]], kind: str, k: int):
    prompts = {t.get("prompt_version") for t in transcripts}
    shas = {t.get("git_sha") for t in transcripts}
    models = {t.get("model") for t in transcripts}
    if len(prompts) != 1 or len(models) != 1:
        raise SystemExit(f"mixed runs: prompts {prompts}, models {models}; re-record first")
    return history.entry(
        kind=kind,
        split=report["split"],
        model=models.pop(),
        prompt_version=prompts.pop(),
        git_sha=",".join(sorted(s or "unknown" for s in shas)),
        git_dirty=any(t.get("git_dirty", True) for t in transcripts),
        k=k,
        report=report,
        results=[t["events"][-1] for t in transcripts if t.get("events")],
        wall_s=[t["wall_s"] for t in transcripts if t.get("wall_s") is not None],
    )


def print_report(report: dict[str, Any]) -> None:
    for case_id, r in report["cases"].items():
        mark = "PASS" if r["passed"] else "FAIL"
        note = "" if r["counted"] else " (not counted: unpoisoned)"
        reasons = "; ".join(f"{k}: {v}" for k, v in r["failed"].items())
        print(f"{mark} {case_id:12}{note} {reasons}"[:240])
    print(f"\npass rate {report['pass_rate']:.2f} on {report['n_counted']} counted cases")
    for category, rate in report["by_category"].items():
        print(f"  {category:13} {'n/a' if rate is None else f'{rate:.2f}'}")
    if report["search_recall_at_5_in_run"] is not None:
        print(
            f"  agent search recall@5: {report['search_recall_at_5_in_run']:.2f} "
            f"({report['degraded_searches']}/{report['searches']} searches degraded)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="dev", choices=["dev", "test"])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--check", action="store_true", help="fail on any change vs the manifest")
    parser.add_argument("--write", action="store_true", help="update the pinned manifest")
    parser.add_argument("--history", action="store_true", help="append to evals/history.jsonl")
    args = parser.parse_args()
    report = grade_split(args.split)
    manifest = GRADES / f"{args.split}.json"
    if args.write:
        GRADES.mkdir(exist_ok=True)
        manifest.write_text(json.dumps(verdicts(report), indent=1, sort_keys=True) + "\n")
    if args.history:
        transcripts = list(load_transcripts(TRANSCRIPTS / args.split).values())
        history.append(history_line(report, transcripts, kind="transcripts", k=1))
    if args.json:
        print(json.dumps(report, indent=1))
    else:
        print_report(report)
    if args.check:
        pinned = json.loads(manifest.read_text()) if manifest.exists() else {}
        if pinned != verdicts(report):
            changed = sorted(
                k for k in set(pinned) | set(report["cases"])
                if pinned.get(k) != verdicts(report).get(k)
            )  # fmt: skip
            sys.exit(f"grades differ from {manifest.name} for {changed}; review, then --write")
