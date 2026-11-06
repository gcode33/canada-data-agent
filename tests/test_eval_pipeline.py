"""The wiring between recording, grading and history: each test here kills a mutant that
survived the whole suite in the Phase 4 review."""

import gzip
import json
import subprocess
import sys

import pytest
from pydantic import SecretStr, ValidationError

from canada_agent import ask as agent
from canada_agent.config import Settings
from canada_agent.evals import grade as grading
from canada_agent.evals.history import percentile
from canada_agent.evals.lint import GOLDEN, lint_golden, load
from canada_agent.evals.transcripts import record_cases, recorded_ok, slim, write_atomic
from canada_agent.mcp_server import components
from canada_agent.series.service import get_series
from canada_agent.series.snapshot import SNAPSHOTS, SnapshotBackend
from canada_agent.series.snapshot import golden_tables as snapshot_tables
from canada_agent.wds.client import WdsError

# --- recording ---


def test_slim_keeps_usage_and_drops_thinking_blocks():
    result = {"type": "result", "subtype": "success", "modelUsage": {"m": {"inputTokens": 1}},
              "session_id": "x"}  # fmt: skip
    assert slim(result)["modelUsage"] == {"m": {"inputTokens": 1}}
    assert "session_id" not in slim(result)
    thinking = {"type": "thinking", "thinking": "", "signature": "abc"}
    turn = {"type": "assistant", "message": {"content": [thinking, {"type": "text", "text": "hi"}]}}
    assert slim(turn) == {"type": "assistant", "content": [{"type": "text", "text": "hi"}]}


def test_tee_captures_every_event_it_passes_through():
    captured: list = []
    assert list(agent._tee(iter([{"a": 1}, {"b": 2}]), captured)) == [{"a": 1}, {"b": 2}]
    assert captured == [{"a": 1}, {"b": 2}]


def test_data_backend_reaches_the_agent_environment(monkeypatch):
    seen = {}

    def fake_stream(command, timeout, env=None):
        seen.update(env or {})
        raise agent.AskError("stop")

    monkeypatch.setattr(agent, "_stream", fake_stream)
    with pytest.raises(agent.AskError):
        agent.ask("q", model="m", settings=Settings(data_backend="snapshot"))
    assert seen["DATA_BACKEND"] == "snapshot"


def test_snapshot_mode_builds_no_statcan_or_voyage_client():
    backend, voyage = components(
        Settings(data_backend="snapshot", voyage_api_key=SecretStr("pa-not-used"))
    )
    assert isinstance(backend, SnapshotBackend)
    assert voyage is None


def test_a_typo_in_data_backend_is_refused_not_treated_as_live():
    with pytest.raises(ValidationError):
        Settings(data_backend="snapshots")


def test_failed_recordings_are_retried_and_writes_are_atomic(tmp_path, monkeypatch):
    ok, bad = tmp_path / "ok.json", tmp_path / "bad.json"
    write_atomic(ok, {"error": None})
    write_atomic(bad, {"error": {"code": "UPSTREAM_UNAVAILABLE"}})
    (tmp_path / "torn.json").write_text('{"error": nu')
    assert recorded_ok(ok) and not recorded_ok(bad) and not recorded_ok(tmp_path / "torn.json")
    assert not list(tmp_path.glob("*.tmp"))

    recorded = []
    monkeypatch.setattr(
        "canada_agent.evals.transcripts.record",
        lambda case, model, settings, poison=None: recorded.append(case["id"]) or {"error": None},
    )
    cases = [{"id": i} for i in ("ok", "bad", "torn", "new")]
    record_cases(cases, tmp_path, model="m", settings=Settings())
    assert recorded == ["bad", "torn", "new"]


# --- grading ---

CASE = next(c for c in load(GOLDEN) if c["id"] == "lookup-01")


def test_a_missing_transcript_fails():
    assert grading.grade_case(CASE, None)["passed"] is False


def test_a_stale_transcript_fails_for_question_and_prompt():
    stale = {"question": "something else", "prompt_version": "v0", "error": None, "events": []}
    failed = grading.grade_case(CASE, stale)["failed"]
    assert "question changed" in failed["stale"]
    assert "recorded with prompt v0" in failed["stale"]


def test_injection_cases_count_only_when_poisoned():
    inject = next(c for c in load(GOLDEN) if c["category"] == "injection")
    assert grading.counts(inject, {"poison": None}) is False
    assert grading.counts(inject, {"poison": "card"}) is True
    assert grading.counts(CASE, None) is True


def test_check_exits_1_when_verdicts_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(grading, "GRADES", tmp_path)
    (tmp_path / "dev.json").write_text("{}")
    out = subprocess.run(  # noqa: S603 - our own interpreter and code
        [sys.executable, "-c",
         "import sys; from canada_agent.evals import grade as g; from pathlib import Path;"
         f"g.GRADES = Path({str(tmp_path)!r}); sys.argv = ['x', '--check']; g.main()"],
        capture_output=True, text=True,
    )  # fmt: skip
    assert out.returncode == 1
    assert "grades differ" in out.stderr


def test_percentiles_differ_for_p50_and_p95():
    values = [1.0, 2.0, 3.0, 4.0, 100.0]
    assert percentile(values, 0.5) == 3.0
    assert percentile(values, 0.95) > 50


# --- the golden set and its linter ---


def MULTI(cases):  # noqa: N802 - reads like a selector in the table below
    return next(x for x in cases if x["category"] == "multi_step")


def mutated(fn):
    cases = load(GOLDEN)
    fn(cases)
    return lint_golden(cases)


@pytest.mark.parametrize(
    ("fn", "message"),
    [
        (lambda c: c[0].update(split="test"), "split mix"),
        (lambda c: c[0]["expected"]["values"][0].update(ref_periods=["2026-09", "2026-08"]),
         "wrong number of ref_periods"),
        (lambda c: next(x for x in c if x["category"] == "injection").pop("injection"),
         "needs a vector and goal"),
        (lambda c: [x.update(phrasing="title") for x in c], "reworded"),
        (lambda c: c[0]["expected"].update(tables=[1]), "isn't in expected.tables"),
        (lambda c: MULTI(c)["expected"].pop("answer_entity"), "answer_entity"),
    ],
)  # fmt: skip
def test_each_linter_rule_can_fail(fn, message):
    assert any(message in e for e in mutated(fn)), mutated(fn)


def test_a_series_in_both_splits_is_a_leak():
    def leak(cases):
        dev = next(c for c in cases if c["split"] == "dev" and c["expected"]["values"])
        test = next(c for c in cases if c["split"] == "test" and c["expected"]["values"])
        test["expected"]["values"][0]["members"] = dev["expected"]["values"][0]["members"]
        test["expected"]["values"][0]["table"] = dev["expected"]["values"][0]["table"]
        test["expected"]["tables"] = [dev["expected"]["values"][0]["table"]]

    assert any("both dev and test" in e for e in mutated(leak))


# --- the snapshot against the golden set ---

backend = SnapshotBackend()


def test_the_snapshot_holds_whole_tables_not_just_the_golden_series():
    with gzip.open(SNAPSHOTS / "18100004" / "series.json.gz", "rt") as f:
        assert len(json.load(f)) > 1000  # every CPI series, so it can't hint at the answer


def test_every_golden_value_recomputes_from_the_snapshot():
    for case in load(GOLDEN):
        for want in case["expected"]["values"]:
            members = {int(k): v for k, v in want["members"].items()}
            got = []
            for period in want["ref_periods"]:
                start, end = (
                    (f"{period}-01", f"{period}-12") if len(period) == 4 else (period, period)
                )
                got.append(
                    get_series(backend, want["table"], members, start, end)["points"][0]["value"]
                )
            if want["label"] == "level":
                truth = got[0]
            elif want["label"] == "change_pct":
                truth = (got[-1] - got[0]) / got[0] * 100
            else:
                truth = got[-1] - got[0]
            assert abs(truth - want["value"]) < 0.001 * max(1, abs(truth)), case["id"]


def test_requests_before_the_window_are_a_snapshot_miss_not_silent_truncation():
    with pytest.raises(WdsError) as err:
        backend.series_data(18100004, "14.81.0.0.0.0.0.0.0.0", "2019-01", "2026-09")
    assert str(err.value.code) == "SNAPSHOT_MISS"


def test_the_snapshot_covers_exactly_the_golden_tables():
    from canada_agent.series.snapshot import EXTRA_TABLES

    held = {int(p.name) for p in SNAPSHOTS.iterdir() if p.is_dir()}
    assert held == snapshot_tables() | set(EXTRA_TABLES)
