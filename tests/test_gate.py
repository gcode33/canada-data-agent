import json
import subprocess
import sys

import pytest

from canada_agent.evals import gate


def cases(**rates):
    return {
        k: {"category": "injection" if k.startswith("inject") else "lookup", "pass_rate": v,
            "agreement": max(v, 1 - v), "failures": [], "leaked": 0}
        for k, v in rates.items()
    }  # fmt: skip


BASE = {"pass_rates": {"a": 1.0, "b": 1.0, "c": 2 / 3, "d": 1.0}, "quarantined": []}


def test_a_steady_run_passes():
    assert gate.judge(cases(a=1.0, b=1.0, c=2 / 3, d=1.0), BASE, usd=1.0) == []


def test_a_case_dropping_from_three_to_one_of_three_is_a_flip():
    reasons = gate.judge(cases(a=1 / 3, b=1.0, c=2 / 3, d=1.0), BASE, usd=1.0)
    assert any(r.startswith("flip: a") for r in reasons)


def test_two_of_three_is_not_a_flip():
    assert gate.judge(cases(a=2 / 3, b=1.0, c=2 / 3, d=1.0), BASE, usd=1.0) == []


def test_a_mean_drop_over_ten_points_fails():
    reasons = gate.judge(cases(a=2 / 3, b=2 / 3, c=1 / 3, d=2 / 3), BASE, usd=1.0)
    assert any("mean pass rate fell" in r for r in reasons)


def test_an_injection_that_got_through_fails_the_gate():
    runs = cases(a=1.0, inject_x=2 / 3)
    runs["inject_x"]["leaked"] = 1
    assert any("injection got through: inject_x" in r for r in gate.judge(runs, BASE, usd=1.0))


def test_an_attack_the_runtime_defence_blocked_does_not_fail_the_gate():
    runs = cases(a=1.0, b=1.0, c=2 / 3, d=1.0, inject_x=2 / 3)  # blocked: failed, not leaked
    runs["inject_x"]["leaked"] = 0
    assert gate.judge(runs, BASE, usd=1.0) == []


def test_leaks_are_counted_from_graded_runs():
    leaked = {"failed": {"injection": "carried link"}}
    blocked = {"failed": {"completed": "run failed: citation is not a StatCan URL", "links": "x"}}
    assert gate.leaked_runs([leaked, blocked, {"failed": {}}]) == 1


def test_cost_over_the_cap_fails():
    assert any("over the $2.00 cap" in r for r in gate.judge(cases(a=1.0), BASE, usd=2.5))


def test_quarantined_cases_run_but_do_not_count():
    base = dict(BASE, quarantined=["a"])
    assert gate.judge(cases(a=0.0, b=1.0, c=2 / 3, d=1.0), base, usd=1.0) == []


def test_without_a_baseline_only_injection_and_cost_rules_apply():
    assert gate.judge(cases(a=0.0), {}, usd=1.0) == []


def test_inputs_hash_tracks_inputs_and_ignores_caches(tmp_path, monkeypatch):
    src = tmp_path / "src" / "canada_agent"
    src.mkdir(parents=True)
    (src / "a.py").write_text("x = 1")
    monkeypatch.setattr(gate, "INPUTS", ("src/canada_agent", "missing.txt"))
    (tmp_path / "missing.txt").write_text("m")
    first = gate.inputs_hash(tmp_path)
    (src / "__pycache__").mkdir()
    (src / "__pycache__" / "a.pyc").write_bytes(b"junk")
    assert gate.inputs_hash(tmp_path) == first
    (src / "a.py").write_text("x = 2")
    assert gate.inputs_hash(tmp_path) != first


def run_verify(tmp_path, result):
    if result is not None:
        (tmp_path / "gate-result.json").write_text(json.dumps(result))
    code = (
        "import sys; from pathlib import Path; from canada_agent.evals import gate as g;"
        f"g.RESULT = Path({str(tmp_path / 'gate-result.json')!r});"
        "sys.argv = ['x', 'verify']; g.main()"
    )
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)  # noqa: S603


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (None, "no evals/gate-result.json"),
        ({"inputs_hash": "old", "passed": True}, "stale"),
    ],
)
def test_verify_fails_on_a_missing_or_stale_receipt(tmp_path, result, message):
    out = run_verify(tmp_path, result)
    assert out.returncode == 1 and message in out.stderr


def test_verify_fails_on_a_failing_receipt_and_passes_a_good_one(tmp_path):
    digest = gate.inputs_hash()
    failing = run_verify(tmp_path, {"inputs_hash": digest, "passed": False, "reasons": ["flip"]})
    assert failing.returncode == 1 and "failed" in failing.stderr
    good = {"inputs_hash": digest, "passed": True, "model": "m", "k": 3, "mean_pass_rate": 0.9}
    assert run_verify(tmp_path, good).returncode == 0
