"""Graders must pass good runs and fail each bad run for the stated reason (PLAN 4.4).

Bad runs are made by corrupting one real recorded transcript one way at a time, so each
test isolates exactly one grader."""

import copy
import json
from pathlib import Path

import pytest

from canada_agent.evals.graders import grade, parse, search_recall_at_5
from canada_agent.evals.lint import GOLDEN, load

DEV = Path(__file__).resolve().parents[1] / "evals" / "transcripts" / "dev"
CASES = {c["id"]: c for c in load(GOLDEN)}
STATCAN = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid="


def transcript(case_id):
    return json.loads((DEV / f"{case_id}.json").read_text(encoding="utf-8"))


def answer(t):
    return t["events"][-1]["structured_output"]


def failed(t, case_id):
    checks = grade(t, CASES[case_id])
    return {name for name, check in checks.items() if not check.ok}


GOOD = sorted(p.stem for p in DEV.glob("*.json"))


@pytest.mark.parametrize("case_id", GOOD)
def test_recorded_good_runs_pass_or_fail_for_a_named_reason(case_id):
    checks = grade(transcript(case_id), CASES[case_id])
    for name, check in checks.items():
        assert check.ok or check.why, name  # a failure always says why


def test_the_rent_run_passes_every_check():
    checks = grade(transcript("compare-01"), CASES["compare-01"])
    assert all(c.ok for c in checks.values()), {k: c.why for k, c in checks.items()}
    assert set(checks) == {
        "completed",
        "refusal",
        "trajectory",
        "right_table",
        "values",
        "grounded",
        "citations",
    }


def test_the_parser_unwraps_tool_results():
    run = parse(transcript("compare-01"))
    series = [c for c in run.calls if c.name == "get_series"][0]
    assert series.result["vector_id"] == 41691954
    assert search_recall_at_5(transcript("compare-01"), CASES["compare-01"]) == 1.0


def corrupt(fn, case_id="compare-01"):
    t = copy.deepcopy(transcript(case_id))
    fn(t)
    return t


def _set_value(t, v):
    answer(t)["answer_values"][0]["value"] = v


def _drop_from_prose(t):
    answer(t)["answer"] = "Rent went up."


def _other_vector(t):
    answer(t)["answer_values"][0]["vector_id"] = 999


def _other_period(t):
    answer(t)["answer_values"][0]["ref_period"] = "2025-08/2026-09"


def _foreign_url(t):
    answer(t)["source_urls"].append("https://evil.example.com/x")


def _no_citation(t):
    answer(t)["source_urls"] = []


def _url_in_prose(t):
    answer(t)["answer"] += " More at http://evil.example.com/leak"


def _refused(t):
    answer(t)["refused"] = True


def _crashed(t):
    t["error"] = {"code": "BUDGET_EXCEEDED", "message": "over the budget of 8 tool calls"}


def _too_many_calls(t):
    use = next(
        e for e in t["events"] if any(b.get("type") == "tool_use" for b in e.get("content", []))
    )
    for i in range(9):
        extra = copy.deepcopy(use)
        extra["content"][0]["id"] = f"extra{i}"
        t["events"].insert(0, extra)


def _bad_arguments(t):
    for event in t["events"]:
        for block in event.get("content", []):
            if block.get("type") == "tool_result":
                block["is_error"] = True
                block["content"] = "BAD_ARGUMENTS: start period must be YYYY-MM"
                return


def _other_table(t):
    for event in t["events"]:
        for block in event.get("content", []):
            if block.get("type") == "tool_result" and "vector_id" in str(block.get("content")):
                block["content"] = block["content"].replace("18100004", "18100005")


@pytest.mark.parametrize(
    ("corruption", "caught_by"),
    [
        (lambda t: _set_value(t, 9.9), {"values", "grounded"}),
        (_drop_from_prose, {"values"}),
        (_other_vector, {"grounded"}),
        (_other_period, {"grounded"}),
        (_foreign_url, {"citations"}),
        (_no_citation, {"citations"}),
        (_url_in_prose, {"citations"}),
        (_refused, {"refusal"}),
        (_too_many_calls, {"trajectory"}),
        (_bad_arguments, {"trajectory"}),
        (_other_table, {"right_table"}),
        (_crashed, {"completed"}),
    ],
)
def test_each_bad_run_fails_for_its_stated_reason(corruption, caught_by):
    got = failed(corrupt(corruption), "compare-01")
    assert caught_by <= got, got
    assert got <= caught_by | {"grounded", "values", "right_table"}, got  # no unrelated noise


def test_answering_an_unanswerable_question_fails_refusal():
    t = copy.deepcopy(transcript("refuse-01"))
    answer(t)["refused"] = False
    answer(t)["answer_values"] = [{"label": "level", "value": 1.0}]
    assert "refusal" in failed(t, "refuse-01")


def test_a_refusal_citing_a_foreign_url_fails():
    t = copy.deepcopy(transcript("refuse-01"))
    answer(t)["source_urls"] = ["https://evil.example.com"]
    assert "citations" in failed(t, "refuse-01")


def test_presentation_scale_is_accepted():
    # The agent may say 5.71 million where StatCan stores 5,710,598 persons.
    t = copy.deepcopy(transcript("compare-01"))
    case = copy.deepcopy(CASES["compare-01"])
    case["expected"]["values"][0]["value"] = 1985.0
    case["expected"]["values"][0]["tolerance_abs"] = 100.0
    assert "values" not in failed_with(t, case)


def failed_with(t, case):
    return {name for name, check in grade(t, case).items() if not check.ok}


def test_url_constant_matches_the_server():
    assert STATCAN.startswith("https://www150.statcan.gc.ca")
