"""`canada-grade`: grade recorded transcripts against the golden set, with no model.

A case with no transcript counts as a failure, never a skip, so a missing recording can't
make the score look better. Prints one line per case, then pass rates per category.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from canada_agent import ask as agent
from canada_agent.config import Settings
from canada_agent.evals import history
from canada_agent.evals.graders import grade, search_recall_at_5
from canada_agent.evals.lint import GOLDEN, load
from canada_agent.evals.transcripts import TRANSCRIPTS


def grade_split(split: str, folder: Path = TRANSCRIPTS) -> dict[str, Any]:
    cases = [c for c in load(GOLDEN) if c["split"] == split]
    results = {}
    for case in cases:
        path = folder / split / f"{case['id']}.json"
        if not path.exists():
            results[case["id"]] = {
                "category": case["category"],
                "passed": False,
                "failed": {"recorded": "no transcript"},
                "search_recall_at_5": None,
            }
            continue
        transcript = json.loads(path.read_text(encoding="utf-8"))
        checks = grade(transcript, case)
        results[case["id"]] = {
            "category": case["category"],
            "passed": all(c.ok for c in checks.values()),
            "failed": {name: c.why for name, c in checks.items() if not c.ok},
            "search_recall_at_5": search_recall_at_5(transcript, case),
        }
    by_category: dict[str, list[bool]] = defaultdict(list)
    for r in results.values():
        by_category[r["category"]].append(r["passed"])
    recalls = [
        r["search_recall_at_5"] for r in results.values() if r["search_recall_at_5"] is not None
    ]
    return {
        "split": split,
        "cases": results,
        "pass_rate": sum(r["passed"] for r in results.values()) / len(results),
        "by_category": {k: sum(v) / len(v) for k, v in sorted(by_category.items())},
        "search_recall_at_5_in_run": sum(recalls) / len(recalls) if recalls else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="dev", choices=["dev", "test"])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--history", action="store_true", help="append to evals/history.jsonl")
    args = parser.parse_args()
    report = grade_split(args.split)
    if args.history:
        transcripts = [
            json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((TRANSCRIPTS / args.split).glob("*.json"))
        ]
        results = [t["events"][-1] for t in transcripts if t["events"]]
        models = {t["model"] for t in transcripts} or {Settings().agent_model}
        history.append(
            history.entry(
                kind="transcripts",
                split=args.split,
                model=",".join(sorted(models)),
                prompt_version=agent.PROMPT_VERSION,
                k=1,
                report=report,
                results=[r for r in results if r.get("type") == "result"],
            )
        )
    if args.json:
        print(json.dumps(report, indent=1))
        return
    for case_id, r in report["cases"].items():
        mark = "PASS" if r["passed"] else "FAIL"
        reasons = "; ".join(f"{k}: {v}" for k, v in r["failed"].items())
        print(f"{mark} {case_id:12} {reasons}"[:220])
    print(f"\npass rate {report['pass_rate']:.2f} on {len(report['cases'])} {args.split} cases")
    for category, rate in report["by_category"].items():
        print(f"  {category:13} {rate:.2f}")
    recall = report["search_recall_at_5_in_run"]
    if recall is not None:
        print(f"  search recall@5 inside runs: {recall:.2f}")
    sys.exit(0)
