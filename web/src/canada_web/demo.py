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

import json
import re
import tomllib
from pathlib import Path
from typing import Any

from canada_agent.ask import PROMPT_VERSION, AskError, run_events
from canada_agent.config import Settings
from canada_agent.errors import ErrorCode
from canada_agent.evals import poison
from canada_agent.evals.lint import GOLDEN, load
from canada_agent.evals.transcripts import TRANSCRIPTS
from canada_agent.links import foreign_links

from canada_web.convert import Converter
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


class DemoError(Exception):
    """The demo can't be built honestly from what's committed."""


def allowlist(path: Path = ALLOWLIST) -> tuple[dict[str, str], dict[str, str]]:
    data = tomllib.loads(path.read_text())
    runs = {case: cat for cat in CATEGORIES for case in data.get(cat, [])}
    if len(runs) != sum(len(data.get(c, [])) for c in CATEGORIES):
        raise DemoError("a case is listed under two categories")
    return runs, dict(data.get("commits", {}))


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
    case: str, category: str, t: dict[str, Any], verdict: dict[str, Any] | None, split: str | None
) -> None:
    """Fail closed (step 1)."""
    if t.get("case") != case:
        raise DemoError(f"{case}: the transcript is for {t.get('case')!r}")
    if split != "dev":
        raise DemoError(f"{case}: not on the dev split ({split!r}); the demo is dev-only")
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
            question=t["question"],
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
    for e in events:
        if e.get("type") != "result":
            stream += convert.feed(e)
    if result is None:
        stream += convert.fail(FailureCode.ANSWER_REJECTED)
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
    for e in stream:  # step 3: nothing published may carry an outside link
        hits = foreign_links(e.model_dump(mode="json"))
        if hits:
            raise DemoError(f"{case}: {e.type} would publish outside links {hits}")
    return stream


def tested() -> dict[str, Any]:
    """The "How it's tested" tab, from committed evidence only: nothing hand-typed."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    m = HEADLINE.search(readme)
    if not m:
        raise DemoError("README's held-out headline row wasn't found")
    passed, total, pct, lo, hi = map(int, m.groups())
    gate = json.loads((REPO / "evals" / "gate-result.json").read_text())
    base = json.loads((REPO / "evals" / "baseline.json").read_text())
    return {
        "held_out": {
            "passed": passed,
            "total": total,
            "percent": pct,
            "wilson": [lo, hi],
            "release": "v1.0.0",
        },
        "gate": {
            "model": gate["model"],
            "k": gate["k"],
            "passed": gate["passed"],
            "mean_pass_rate": gate["mean_pass_rate"],
            "cases": len(gate["cases"]),
        },
        "baseline": {
            "model": base["model"],
            "k": base["k"],
            "mean_pass_rate": base["mean_pass_rate"],
            "stable": len(base["stable"]),
            "unstable": sorted(base["unstable"]),
        },
        "links": {
            "repo": "https://github.com/gcode33/canada-data-agent",
            "staged_gate_failure": "https://github.com/gcode33/canada-data-agent/pull/24",
        },
    }


def dump(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"


def build(
    out: Path, allow: Path = ALLOWLIST, recorded: Path = RECORDED, grades: Path = GRADES
) -> list[Path]:
    runs, commits = allowlist(allow)
    if not grades.exists():
        raise DemoError(f"no pinned grader verdicts at {grades.name}")
    verdicts = json.loads(grades.read_text())
    splits = {c["id"]: c["split"] for c in load(GOLDEN)}
    (out / "replays").mkdir(parents=True, exist_ok=True)
    written, index = [], []
    for case, category in runs.items():
        if splits.get(case) != "dev":  # before anything else: never even open a test recording
            raise DemoError(f"{case}: not on the dev split ({splits.get(case)!r}); dev only")
        path = recorded / f"{case}.json"
        if not path.exists():
            raise DemoError(f"{case}: allow-listed but not recorded")
        t = json.loads(path.read_text(encoding="utf-8"))
        check(case, category, t, verdicts.get(case), splits.get(case))
        stream = replay(case, category, t, commits)
        target = out / "replays" / f"{case}.json"
        target.write_text(dump([e.model_dump(mode="json") for e in stream]), encoding="utf-8")
        written.append(target)
        index.append({"case": case, "category": category, "question": t["question"]})
    for name, data in (("index.json", index), ("tested.json", tested())):
        (out / name).write_text(dump(data), encoding="utf-8")
        written.append(out / name)
    return written
