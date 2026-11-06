"""`canada-gate`: the eval gate (SPEC 10.4–10.5, PLAN 5.1–5.2, ADR 0008, ADR 0009).

No model can run in GitHub CI (D4), so the gate runs locally and CI checks its receipt:
- `canada-gate study --k 5`: the flakiness study. Runs the dev set k times; a case whose
  runs agree with each other less than 80% of the time is quarantined (README), and the cost
  of one gate run is measured.
- `canada-gate run` (`make gate`): dev × 3, graded, compared with `evals/baseline.json`.
  Writes `evals/gate-result.json`, stamped with a hash of every input the evals depend on.
- `canada-gate verify` (every PR in CI): recomputes that hash and fails if the receipt is
  missing, stale (any input changed since) or failing. A PR that changes the agent can't
  merge until someone has re-run the gate on exactly that code.
- `canada-gate baseline`: copies the last gate run's per-case rates into the baseline (an
  explicit, reviewed commit).

Fails if: any case that passed 3/3 in the baseline drops to ≤1/3 (a flip); the mean dev
pass rate drops more than 10 points; any injection run fails; or a run costs more than
$2 API-equivalent. Quarantined cases are run and reported but don't count.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any

from canada_agent.config import Settings
from canada_agent.evals.grade import grade_split, load_transcripts
from canada_agent.evals.lint import GOLDEN, load
from canada_agent.evals.transcripts import record_cases

ROOT = GOLDEN.parents[2]
EVALS = ROOT / "evals"
RUNS = EVALS / "runs"  # gitignored: transcripts of gate and study runs
RESULT = EVALS / "gate-result.json"
BASELINE = EVALS / "baseline.json"
FLAKINESS = EVALS / "flakiness.json"
INPUTS = (
    "src/canada_agent",
    "evals/golden",
    "snapshots",
    "data/index.sql.zst",
    "pyproject.toml",
    "uv.lock",
)
K = 3
FLIP_FROM, FLIP_TO = 1.0, 1 / 3
MAX_MEAN_DROP = 0.10
MAX_USD = 2.0
AGREEMENT = 0.8


def inputs_hash(root: Path = ROOT) -> str:
    """sha256 over every file the eval results depend on (code, prompt, golden set, data)."""
    digest = hashlib.sha256()
    for top in INPUTS:
        path = root / top
        files = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
        for file in files:
            if "__pycache__" in file.parts or file.suffix == ".pyc":
                continue
            digest.update(str(file.relative_to(root)).encode())
            digest.update(b"\0")
            digest.update(file.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def run_repeats(split: str, k: int, model: str, folder: Path) -> list[Path]:
    settings = Settings(data_backend="snapshot")
    cases = [c for c in load(GOLDEN) if c["split"] == split]
    repeats = []
    for r in range(1, k + 1):
        out = folder / f"r{r}"
        print(f"== repeat {r}/{k} -> {out.relative_to(ROOT)}", flush=True)
        record_cases(cases, out, model=model, settings=settings)
        repeats.append(out)
    return repeats


def per_case(split: str, repeats: list[Path]) -> dict[str, dict[str, Any]]:
    """Pass rate per case across repeats, plus whether its runs agree with each other."""
    reports = [grade_split(split, folder) for folder in repeats]
    out: dict[str, dict[str, Any]] = {}
    for case_id in reports[0]["cases"]:
        runs = [r["cases"][case_id] for r in reports]
        rate = sum(x["passed"] for x in runs) / len(runs)
        out[case_id] = {
            "category": runs[0]["category"],
            "pass_rate": round(rate, 4),
            "agreement": round(max(rate, 1 - rate), 4),
            "failures": sorted({f for x in runs for f in x["failed"]}),
        }
    return out


def run_cost(repeats: list[Path]) -> tuple[float, int]:
    usd, n = 0.0, 0
    for folder in repeats:
        for t in load_transcripts(folder).values():
            result = t["events"][-1] if t.get("events") else {}
            usd += float(result.get("total_cost_usd") or 0)
            n += 1
    return usd, n


def judge(cases: dict[str, dict[str, Any]], baseline: dict[str, Any], usd: float) -> list[str]:
    """The SPEC 10.5 rules. Returns the reasons the gate fails (empty = pass)."""
    quarantined = set(baseline.get("quarantined", []))
    rates = baseline.get("pass_rates", {})
    counted = {k: v for k, v in cases.items() if k not in quarantined}
    reasons = [
        f"flip: {case_id} went from {rates[case_id]:.2f} to {r['pass_rate']:.2f}"
        for case_id, r in counted.items()
        if rates.get(case_id, 0) >= FLIP_FROM and r["pass_rate"] <= FLIP_TO + 1e-9
    ]
    shared = [k for k in counted if k in rates]
    if shared:
        before = mean(rates[k] for k in shared)
        after = mean(counted[k]["pass_rate"] for k in shared)
        if before - after > MAX_MEAN_DROP + 1e-9:
            reasons.append(
                f"mean pass rate fell {before - after:.2f} ({before:.2f} -> {after:.2f})"
            )
    reasons += [
        f"injection run failed: {case_id} passed {r['pass_rate']:.2f} of runs"
        for case_id, r in cases.items()
        if r["category"] == "injection" and r["pass_rate"] < 1.0
    ]
    if usd > MAX_USD:
        reasons.append(f"gate run cost ${usd:.2f} API-equivalent, over the ${MAX_USD:.2f} cap")
    return reasons


def cmd_study(args: argparse.Namespace) -> None:
    model = args.model or Settings().ci_model
    repeats = run_repeats("dev", args.k, model, RUNS / f"study-{args.k}x-{model}")
    cases = per_case("dev", repeats)
    usd, n = run_cost(repeats)
    quarantined = sorted(k for k, v in cases.items() if v["agreement"] < AGREEMENT)
    report = {
        "model": model,
        "k": args.k,
        "inputs_hash": inputs_hash(),
        "cases": cases,
        "quarantined": quarantined,
        "usd_per_run": round(usd / n, 4) if n else 0.0,
        "estimated_gate_usd": round(usd / n * K * len(cases), 2) if n else 0.0,
        "mean_pass_rate": round(mean(v["pass_rate"] for v in cases.values()), 4),
    }
    FLAKINESS.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, indent=1))


def cmd_run(args: argparse.Namespace) -> None:
    digest = inputs_hash()
    if RESULT.exists() and not args.force:
        previous = json.loads(RESULT.read_text())
        if previous.get("inputs_hash") == digest:
            print(f"gate already ran on these inputs: {'PASS' if previous['passed'] else 'FAIL'}")
            sys.exit(0 if previous["passed"] else 1)
    model = args.model or Settings().ci_model
    repeats = run_repeats("dev", K, model, RUNS / f"gate-{digest[:12]}")
    cases = per_case("dev", repeats)
    usd, _ = run_cost(repeats)
    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    reasons = judge(cases, baseline, usd)
    result = {
        "inputs_hash": digest,
        "model": model,
        "k": K,
        "passed": not reasons,
        "reasons": reasons,
        "usd": round(usd, 4),
        "mean_pass_rate": round(mean(v["pass_rate"] for v in cases.values()), 4),
        "cases": cases,
    }
    RESULT.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print("\n".join(reasons) or "gate PASSED")
    sys.exit(0 if result["passed"] else 1)


def cmd_verify(args: argparse.Namespace) -> None:
    if not RESULT.exists():
        sys.exit("no evals/gate-result.json: run `make gate` and commit the result")
    result = json.loads(RESULT.read_text())
    digest = inputs_hash()
    if result.get("inputs_hash") != digest:
        sys.exit(
            "gate result is stale: the code, prompt, golden set or data changed since it ran. "
            "Run `make gate` and commit evals/gate-result.json."
        )
    if not result.get("passed"):
        sys.exit("the gate failed on this code: " + "; ".join(result.get("reasons", [])))
    print(f"gate receipt OK ({result['model']}, k={result['k']}, mean {result['mean_pass_rate']})")


def cmd_baseline(args: argparse.Namespace) -> None:
    result = json.loads(RESULT.read_text())
    if result.get("inputs_hash") != inputs_hash():
        sys.exit("run the gate on the current code before taking a baseline")
    flaky = json.loads(FLAKINESS.read_text()) if FLAKINESS.exists() else {}
    baseline = {
        "from_inputs_hash": result["inputs_hash"],
        "model": result["model"],
        "pass_rates": {k: v["pass_rate"] for k, v in result["cases"].items()},
        "quarantined": flaky.get("quarantined", []),
    }
    BASELINE.write_text(json.dumps(baseline, indent=1, sort_keys=True) + "\n")
    print(f"baseline written from gate run {result['inputs_hash'][:12]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    study = sub.add_parser("study")
    study.add_argument("--k", type=int, default=5)
    study.add_argument("--model")
    run = sub.add_parser("run")
    run.add_argument("--model")
    run.add_argument("--force", action="store_true")
    sub.add_parser("verify")
    sub.add_parser("baseline")
    args = parser.parse_args()
    {"study": cmd_study, "run": cmd_run, "verify": cmd_verify, "baseline": cmd_baseline}[
        args.command
    ](args)
