import ast
import importlib.util
from pathlib import Path

import pytest

from canada_agent.evals.lint import GOLDEN, lint_golden, load

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "evals" / "verify_golden.py"
spec = importlib.util.spec_from_file_location("verify_golden", SCRIPT)
verify_golden = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify_golden)


def test_the_committed_golden_set_passes_the_linter():
    assert lint_golden(load(GOLDEN)) == []


def test_the_verifier_shares_no_code_with_the_system_under_test():
    imported = set()
    for node in ast.walk(ast.parse(SCRIPT.read_text())):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert "canada_agent" not in imported
    assert "httpx" not in imported


def test_recompute_maths():
    series = {"a": {"VALUE": "161.2"}, "b": {"VALUE": "164.4"}}
    assert verify_golden.recompute("level", ["a"], series) == 161.2
    assert verify_golden.recompute("change_pct", ["a", "b"], series) == pytest.approx(
        1.985, abs=1e-3
    )
    assert verify_golden.recompute("change_abs", ["a", "b"], series) == pytest.approx(3.2)
    with pytest.raises(ValueError, match="unknown label"):
        verify_golden.recompute("median", ["a"], series)


@pytest.mark.parametrize(
    ("raw", "out"), [("2026-09", "2026-09"), ("2026-07-01", "2026-07"), ("2025", "2025")]
)
def test_periods(raw, out):
    assert verify_golden.period(raw) == out


def fake_case(value):
    return {
        "id": "c",
        "expected": {
            "values": [
                {
                    "table": 1,
                    "members": {1: 14, 2: 81},
                    "label": "change_pct",
                    "value": value,
                    "tolerance_abs": 0.1,
                    "ref_periods": ["2025-09", "2026-09"],
                }
            ]
        },
    }


@pytest.fixture
def csv_rows(monkeypatch):
    rows = [
        {"COORDINATE": "14.81", "REF_DATE": "2025-09", "VALUE": "161.2"},
        {"COORDINATE": "14.81", "REF_DATE": "2026-09", "VALUE": "164.4"},
        {"COORDINATE": "14.82", "REF_DATE": "2026-09", "VALUE": "999"},
    ]
    monkeypatch.setattr(verify_golden, "rows", lambda table: iter(rows))


def test_a_correct_value_passes_and_a_wrong_one_is_caught(csv_rows):
    assert verify_golden.verify([fake_case(1.985)]) == []
    assert "CSV gives 1.9851" in verify_golden.verify([fake_case(9.9)])[0]


def test_a_period_missing_from_the_csv_is_a_problem_not_a_crash(csv_rows):
    case = fake_case(2.0)
    case["expected"]["values"][0]["ref_periods"] = ["2020-01", "2026-09"]
    assert "no CSV value" in verify_golden.verify([case])[0]


def base_cases():
    return load(GOLDEN)


def test_linter_catches_a_broken_mix():
    assert any("category mix" in e for e in lint_golden(base_cases()[:-1]))


def test_linter_catches_an_unverified_case():
    cases = base_cases()
    cases[0]["verified_against_csv"] = False
    assert any("not verified" in e for e in lint_golden(cases))


def test_linter_catches_a_refusal_expecting_values():
    cases = base_cases()
    refusal = next(c for c in cases if c["expected"]["should_refuse"])
    refusal["expected"]["values"] = [{"label": "level"}]
    assert any("must expect no values" in e for e in lint_golden(cases))
