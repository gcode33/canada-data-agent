"""`make bench`: an offline benchmark of a base ref against this checkout (A8 §6.3, ADR 0011).

Why this shape (the A8 review): batch medians drift 4–5% on their own, so a single before/after
number proves nothing. So:
- base and head run **interleaved** (ABBA order) on the same machine, in one sitting;
- **both sides are fresh worktrees built the same way**, each with its own new venv and
  compiled bytecode (`uv sync --compile-bytecode`). The first A/A run put head in the existing
  checkout and only base in a fresh worktree: identical code then showed head ~3 ms (1%)
  "faster" on every process-start measure, with intervals excluding 0. So only committed
  code is benchmarked, and head is a ref too;
- 3 warm-up rounds are discarded, then n samples per side (default 30);
- a change counts only if the bootstrap interval of the difference in medians excludes 0.
  The intervals are **Bonferroni-adjusted across the measures** (4 measures → 98.75% each),
  because four plain 95% intervals would flag a "change" in an A/A run about 19% of the time;
- raw samples and the environment are written to `docs/perf/`, so anyone can recompute.

Offline: the snapshot backend, no Voyage key, no StatCan, no model. It needs the local
Postgres with the seeded index (`make up`) for `search_tables`.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "perf"
PROBE = Path(__file__).resolve().with_name("probe.py")
MEASURES = ("import_ask", "import_mcp_server", "handshake", "search_tables")
RESAMPLES = 4000


def run(cmd: list[str], cwd: Path, **kw) -> str:
    return subprocess.run(  # noqa: S603 - fixed argv
        cmd, cwd=cwd, check=True, capture_output=True, text=True, **kw
    ).stdout.strip()


def prepare(side: Path) -> Path:
    """A venv with this side's code and compiled bytecode; returns its Python."""
    run(["uv", "sync", "--frozen", "--compile-bytecode", "--quiet"], side)  # noqa: S607
    return side / ".venv" / "bin" / "python"


def probe_env() -> dict[str, str]:
    from canada_agent.config import Settings  # this checkout's settings, shared by both sides

    env = dict(os.environ)
    env |= {
        "DATABASE_URL": Settings().database_url,
        "DATA_BACKEND": "snapshot",
        "VOYAGE_API_KEY": "",
        "POISON": "",
    }
    return env


def sample(python: Path, side: Path, measure: str, env: dict[str, str]) -> float:
    return float(run([str(python), str(PROBE), measure], side, env=env))


def bootstrap(base: list[float], head: list[float], level: float, seed: int) -> list[float]:
    """Percentile interval of median(head) − median(base)."""
    rng = random.Random(seed)  # noqa: S311 - a seeded bootstrap, not security
    diffs = sorted(
        median(rng.choices(head, k=len(head))) - median(rng.choices(base, k=len(base)))
        for _ in range(RESAMPLES)
    )
    tail = (1 - level) / 2
    k = round(tail * RESAMPLES)  # symmetric tails: drop k samples from each end
    return [diffs[k], diffs[RESAMPLES - 1 - k]]


def environment(base: Path, head: Path) -> dict[str, str]:
    def safe(cmd: list[str], cwd: Path = ROOT) -> str:
        try:
            return run(cmd, cwd)
        except (OSError, subprocess.CalledProcessError):
            return "unknown"

    db = safe(["docker", "compose", "ps", "-q", "db"])  # noqa: S607
    return {
        "date": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "machine": next(
            (v for v in (safe(["sysctl", "-n", "hw.model"]),) if v != "unknown"),  # noqa: S607
            platform.machine(),
        ),
        "cpu": safe(["sysctl", "-n", "machdep.cpu.brand_string"]),  # noqa: S607
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "power": (safe(["pmset", "-g", "batt"]).splitlines() or [""])[0]  # noqa: S607
        if shutil.which("pmset")
        else "",
        "postgres_image": safe(["docker", "inspect", "--format", "{{.Config.Image}}", db])
        if db != "unknown"
        else "unknown",
        "base_sha": safe(["git", "rev-parse", "HEAD"], base),
        "head_sha": safe(["git", "rev-parse", "HEAD"], head),
        "base_lock_sha256": hashlib.sha256((base / "uv.lock").read_bytes()).hexdigest()[:16],
        "head_lock_sha256": hashlib.sha256((head / "uv.lock").read_bytes()).hexdigest()[:16],
    }


def report(result: dict) -> str:
    level = result["interval_level"]
    lines = [
        f"# Benchmark: {result['label']}",
        "",
        f"Base `{result['base_ref']}` ({result['env']['base_sha'][:7]}) against head "
        f"`{result['head_ref']}` ({result['env']['head_sha'][:7]}), both fresh worktrees, "
        f"{result['n']} interleaved samples per side after "
        f"{result['warmup']} warm-up rounds, on {result['env']['machine']} "
        f"({result['env']['cpu']}), {result['env']['date']}.",
        "",
        f"| Measure | Base median | Head median | Head − base | {level:.2%} interval | Verdict |",
        "|---|---|---|---|---|---|",
    ]
    for m, r in result["measures"].items():
        lo, hi = r["interval_ms"]
        lines.append(
            f"| {m} | {r['base_median_ms']:.1f} ms | {r['head_median_ms']:.1f} ms | "
            f"{r['diff_ms']:+.1f} ms | [{lo:+.1f}, {hi:+.1f}] | {r['verdict']} |"
        )
    lines += [
        "",
        f"Intervals are bootstrap percentile intervals ({RESAMPLES} resamples) of the "
        f"difference in medians, Bonferroni-adjusted for {len(result['measures'])} measures. "
        "Raw samples and the environment are in the JSON file beside this one.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", default="main", help="the base git ref")
    parser.add_argument("--head", default="HEAD", help="the head git ref (committed code only)")
    parser.add_argument("--label", default="bench")
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--alpha", type=float, default=0.05, help="family-wise, across measures")
    parser.add_argument("--seed", type=int, default=20261118)
    args = parser.parse_args()

    level = 1 - args.alpha / len(MEASURES)
    if args.head == "HEAD" and run(["git", "status", "--porcelain", "--", "src"], ROOT):  # noqa: S607
        sys.exit("src/ has uncommitted changes: commit them first (only committed code is benched)")
    with tempfile.TemporaryDirectory(prefix="canada-bench-") as tmp:
        sides = {"base": Path(tmp) / "base", "head": Path(tmp) / "head"}
        created: list[Path] = []
        try:
            for side, ref in (("base", args.ref), ("head", args.head)):
                run(["git", "worktree", "add", "--detach", "--quiet", str(sides[side]), ref], ROOT)  # noqa: S607
                created.append(sides[side])
            pythons = {side: prepare(path) for side, path in sides.items()}
            env = probe_env()
            samples: dict[str, dict[str, list[float]]] = {
                m: {"base": [], "head": []} for m in MEASURES
            }
            for i in range(args.warmup + args.n):
                order = ("base", "head") if i % 2 == 0 else ("head", "base")
                for m in MEASURES:
                    for side in order:
                        t = sample(pythons[side], sides[side], m, env)
                        if i >= args.warmup:
                            samples[m][side].append(t)
                print(f"round {i + 1}/{args.warmup + args.n}", file=sys.stderr, flush=True)
            info = environment(sides["base"], sides["head"])
        finally:
            # Each removal on its own, so one failure can't hide the original error or leave
            # the other worktree registered; then prune whatever git still remembers.
            for path in created:
                try:
                    run(["git", "worktree", "remove", "--force", str(path)], ROOT)  # noqa: S607
                except subprocess.CalledProcessError as exc:
                    print(f"could not remove worktree {path}: {exc}", file=sys.stderr)
            subprocess.run(["git", "worktree", "prune"], cwd=ROOT, check=False)  # noqa: S603, S607

    measures = {}
    for k, m in enumerate(MEASURES):
        b, h = samples[m]["base"], samples[m]["head"]
        lo, hi = bootstrap(b, h, level, args.seed + k)
        verdict = "faster" if hi < 0 else "slower" if lo > 0 else "no detectable change"
        measures[m] = {
            "base_median_ms": median(b) * 1000,
            "head_median_ms": median(h) * 1000,
            "diff_ms": (median(h) - median(b)) * 1000,
            "interval_ms": [lo * 1000, hi * 1000],
            "verdict": verdict,
            "samples_s": {"base": b, "head": h},
        }
    result = {
        "label": args.label,
        "base_ref": args.ref,
        "head_ref": args.head,
        "n": args.n,
        "warmup": args.warmup,
        "interval_level": level,
        "env": info,
        "measures": measures,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    stem = OUT / f"{info['date'][:10]}-{args.label}"
    stem.with_suffix(".json").write_text(json.dumps(result, indent=1) + "\n")
    stem.with_suffix(".md").write_text(report(result))
    print(report(result))


if __name__ == "__main__":
    main()
