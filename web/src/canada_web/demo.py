"""`canada-web build-demo`: the public replay demo's data (A8 §11, ADR 0010).

Builds `replays/<case>.json` (one event stream per allow-listed dev run), `index.json` and
`tested.json`, with no database, model or network. For every run it:
1. fails closed unless the run is on the allow-list, on the dev split, recorded under today's
   prompt, pinned by the graders with the outcome its category needs, and poisoned only if it's
   an attack;
2. re-wraps the slimmed recording into stream shape and runs the **production** `run_events`
   with a fixed clock: answers and attacks must pass, the rejected run must be refused
   (`ANSWER_REJECTED`). This checks each recorded answer against its recorded tool results; it
   does not re-run the tools (the `fresh-clone` CI job does that);
3. converts it with the same `Converter` live mode uses, validates the stream's ordering, and
   fails if `foreign_links` finds anything in any string it would publish.
Same inputs, same bytes.
"""

import hashlib
import json
import re
import shutil
import tomllib
from pathlib import Path
from typing import Any

from canada_agent.ask import PROMPT_VERSION, AskError, run_events
from canada_agent.config import Settings
from canada_agent.errors import ErrorCode
from canada_agent.evals import poison
from canada_agent.evals.gate import FLIP_TO, MAX_MEAN_DROP, MAX_USD, STUDY_K, K
from canada_agent.evals.lint import GOLDEN, load
from canada_agent.evals.transcripts import TRANSCRIPTS
from canada_agent.links import foreign_links

from canada_web.convert import Converter, display_text
from canada_web.events import (
    Attack,
    FailureCode,
    RecordingProvenance,
    RunStarted,
    validate_stream,
)

WEB = Path(__file__).resolve().parents[2]
REPO = WEB.parent
ALLOWLIST = WEB / "demo" / "allowlist.toml"
RECORDED = TRANSCRIPTS / "dev"
GRADES = REPO / "evals" / "grades" / "dev.json"
CATEGORIES = ("answer", "refusal", "attack_resisted", "rejected")
CANARY = "CANARY-0000000000000000"  # recordings never saw a canary; the check can't fire here
HEADLINE = re.compile(r"\| Pass rate \| (\d+)/(\d+) = (\d+)% \(Wilson (\d+)–(\d+)%\) \|")
REPO_URL = "https://github.com/gcode33/canada-data-agent"
TIMEOUT_S = Settings.model_fields["question_timeout_s"].default


class DemoError(Exception):
    """The demo can't be built honestly from what's committed."""


def allowlist(path: Path = ALLOWLIST) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """(case -> category, commit -> date, case -> pinned sha256 of its transcript)."""
    data = tomllib.loads(path.read_text())
    runs = {case: cat for cat in CATEGORIES for case in data.get(cat, [])}
    if len(runs) != sum(len(data.get(c, [])) for c in CATEGORIES):
        raise DemoError("a case is listed under two categories")
    return runs, dict(data.get("commits", {})), dict(data.get("sha256", {}))


def rewrap(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Slimmed transcript events back into `claude -p` stream shape (what run_events reads)."""
    out = []
    for e in events:
        if e.get("type") in ("assistant", "user") and "message" not in e:
            out.append(
                {k: v for k, v in e.items() if k != "content"}
                | {"message": {"content": e.get("content") or []}}
            )
        else:
            out.append(e)
    return out


def check(
    case: str, category: str, t: dict[str, Any], verdict: dict[str, Any] | None, golden: dict
) -> None:
    """Fail closed (step 1). The transcript must also match its golden case: same question, and
    the same planted attack (or none), so a hand-edited recording can't change what's shown."""
    if t.get("case") != case:
        raise DemoError(f"{case}: the transcript is for {t.get('case')!r}")
    if golden.get("split") != "dev":
        raise DemoError(f"{case}: not on the dev split ({golden.get('split')!r}); dev only")
    if t.get("question") != golden.get("question"):
        raise DemoError(f"{case}: the recorded question isn't the golden case's")
    try:
        recorded = poison.parse(t["poison"]) if t.get("poison") else None
    except (TypeError, ValueError) as exc:
        raise DemoError(f"{case}: unreadable poison spec") from exc
    expected = poison.spec_for(golden)
    if recorded != (poison.parse(expected) if expected else None):
        raise DemoError(f"{case}: the recorded attack isn't the golden case's")
    wall = t.get("wall_s")
    if not isinstance(wall, int | float) or not 0 <= wall <= TIMEOUT_S:
        raise DemoError(f"{case}: wall time {wall!r} is outside the {TIMEOUT_S:.0f}s budget")
    if t.get("prompt_version") != PROMPT_VERSION:
        raise DemoError(f"{case}: recorded under another prompt ({t.get('prompt_version')})")
    if verdict is None:
        raise DemoError(f"{case}: no pinned grader verdict")
    if bool(t.get("poison")) != (category == "attack_resisted"):
        raise DemoError(f"{case}: poisoned runs must be, and only be, attack_resisted")
    if category == "rejected":
        if verdict.get("passed") or (t.get("error") or {}).get("code") != "ANSWER_REJECTED":
            raise DemoError(f"{case}: a rejected run must be graded failed and ANSWER_REJECTED")
    elif not verdict.get("passed") or t.get("error"):
        raise DemoError(f"{case}: an {category} run must be graded passed with no error")


def replay(case: str, category: str, t: dict[str, Any], commits: dict[str, str]) -> list[Any]:
    events = rewrap(t["events"])
    results = [i for i, e in enumerate(events) if e.get("type") == "result"]
    if results != [len(events) - 1]:  # anything after the result would skip every check
        raise DemoError(f"{case}: a transcript must end with exactly one result event")
    try:  # step 2: the production checks, with a fixed clock
        result = run_events(
            events,
            max_tool_calls=Settings.model_fields["max_tool_calls"].default,
            deadline_s=1e9,
            canary=CANARY,
            clock=lambda: 0.0,
        )
        refused = None
    except AskError as exc:
        result, refused = None, exc
    if category == "rejected":
        if refused is None or refused.code != ErrorCode.ANSWER_REJECTED:
            raise DemoError(f"{case}: the checks were expected to refuse this answer")
    elif refused is not None:
        raise DemoError(f"{case}: the production checks now refuse it: {refused}")

    sha = str(t.get("git_sha", ""))
    if sha not in commits:
        raise DemoError(f"{case}: recorded at {sha!r}, which has no date in the allow-list")
    timed = any(isinstance(e.get("t_ms"), int) for e in t["events"])
    spec = poison.parse(t["poison"]) if t.get("poison") else None
    stream: list[Any] = [
        RunStarted(
            type="run_started",
            mode="replay",
            category=category,
            question=display_text(t["question"]),
            model=t["model"],
            prompt_version=t["prompt_version"],
            provenance=RecordingProvenance(
                source="recording",
                case=case,
                model=t["model"],
                commit=sha,
                commit_date=commits[sha],
                recorded_at=t.get("recorded_at"),
                timing="recorded" if timed else "approximate",
                recorded_wall_s=t.get("wall_s"),
            ),
            attack=Attack(goal=spec["goal"], route=spec["vector"]) if spec else None,
        )
    ]
    convert = Converter()
    try:
        for e in events[:-1]:
            stream += convert.feed(e)
    except ValueError as exc:
        raise DemoError(f"{case}: {exc}") from exc
    if result is None:
        stream += convert.fail(FailureCode.ANSWER_REJECTED, str(refused))
    else:
        stream += convert.finish(
            result.answer,
            num_turns=result.num_turns,
            duration_ms=result.duration_ms,
            usd=None,
            billed="none",
        )
    problems = validate_stream(stream)
    if problems:
        raise DemoError(f"{case}: invalid stream: {problems}")
    for e in stream:  # step 3: nothing published may carry an outside link or hidden text
        data = e.model_dump(mode="json")
        hits = foreign_links(data)
        if hits:
            raise DemoError(f"{case}: {e.type} would publish outside links {hits}")
        hidden = [x for x in _strings(data) if display_text(x) != x]
        if hidden:
            raise DemoError(f"{case}: {e.type} would publish hidden characters in {hidden[0]!r}")
    return stream


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def tested() -> dict[str, Any]:
    """The "How it's tested" tab's numbers, from committed evidence: the README headline, the
    held-out run's history entry, the gate receipt, the baseline, the flakiness study and the
    gate's own constants. (The tab's sentences are fixed text in Tested.tsx.)"""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    m = HEADLINE.search(readme)
    if not m:
        raise DemoError("README's held-out headline row wasn't found")
    passed, total, pct, lo, hi = map(int, m.groups())
    history = [json.loads(line) for line in (REPO / "evals" / "history.jsonl").open()]
    held_out = [h for h in history if h.get("split") == "test" and h.get("kind") == "transcripts"]
    if not held_out:
        raise DemoError("no held-out run in evals/history.jsonl")
    gate = json.loads((REPO / "evals" / "gate-result.json").read_text())
    base = json.loads((REPO / "evals" / "baseline.json").read_text())
    study = json.loads((REPO / "evals" / "flakiness.json").read_text())
    return {
        "held_out": {"passed": passed, "total": total, "percent": pct, "wilson": [lo, hi],
                     "release": "v1.0.0", "model": held_out[-1]["model"]},
        "gate": {"model": gate["model"], "k": gate["k"], "passed": gate["passed"],
                 "mean_pass_rate": gate["mean_pass_rate"], "cases": len(gate["cases"])},
        # A flip is a stable case passing at most this many of K runs (gate.py: <= FLIP_TO + 1e-9).
        "rules": {"k": K, "study_k": STUDY_K, "flip_max_passes": int(FLIP_TO * K + 1e-9),
                  "max_mean_drop": MAX_MEAN_DROP, "max_usd": MAX_USD},
        "baseline": {"model": base["model"], "k": base["k"],
                     "mean_pass_rate": base["mean_pass_rate"], "stable": len(base["stable"]),
                     "unstable": sorted(base["unstable"])},
        "study": {"model": study["model"], "k": study["k"],
                  "mean_pass_rate": study["mean_pass_rate"]},
        "links": {"repo": REPO_URL,
                  "staged_gate_failure": f"{REPO_URL}/pull/24",
                  "headline": f"{REPO_URL}/blob/main/docs/FINDINGS.md#the-headline"},
    }  # fmt: skip


def dump(data: Any) -> str:
    text = json.dumps(
        data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return text + "\n"


def build(
    out: Path, allow: Path = ALLOWLIST, recorded: Path = RECORDED, grades: Path = GRADES
) -> list[Path]:
    runs, commits, pinned = allowlist(allow)
    if not grades.exists():
        raise DemoError(f"no pinned grader verdicts at {grades.name}")
    verdicts = json.loads(grades.read_text())
    golden = {c["id"]: c for c in load(GOLDEN)}
    shutil.rmtree(out / "replays", ignore_errors=True)  # never publish a stale replay
    (out / "replays").mkdir(parents=True)
    written, index = [], []
    for case, category in runs.items():
        split = golden.get(case, {}).get("split")
        if split != "dev":  # before anything else: never even open a test recording
            raise DemoError(f"{case}: not on the dev split ({split!r}); dev only")
        path = recorded / f"{case}.json"
        if not path.exists():
            raise DemoError(f"{case}: allow-listed but not recorded")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != pinned.get(case):
            raise DemoError(f"{case}: the transcript isn't the one pinned in the allow-list")
        t = json.loads(raw)
        check(case, category, t, verdicts.get(case), golden[case])
        stream = replay(case, category, t, commits)
        target = out / "replays" / f"{case}.json"
        target.write_text(dump([e.model_dump(mode="json") for e in stream]), encoding="utf-8")
        written.append(target)
        index.append({"case": case, "category": category, "question": display_text(t["question"])})
    for name, data in (("index.json", index), ("tested.json", tested())):
        (out / name).write_text(dump(data), encoding="utf-8")
        written.append(out / name)
    shutil.copyfile(REPO / "docs" / "chart.svg", out / "chart.svg")  # the README's own chart
    written.append(out / "chart.svg")
    return written
