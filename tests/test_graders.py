"""Graders must pass good runs and fail each bad run for the stated reason (PLAN 4.4).

Runs are built here from parts, so tests don't change when transcripts are re-recorded.
Every bypass the Phase 4 adversarial review demonstrated is a test that must fail."""

import json

import pytest

from canada_agent.evals.grade import GRADES, grade_split, verdicts
from canada_agent.evals.graders import coordinate, grade

URL = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid={}01"


def series(table, members, vector, points):
    return {
        "product_id": table,
        "vector_id": vector,
        "coordinate": coordinate(members),
        "source_url": URL.format(table),
        "points": [{"ref_period": p, "value": v} for p, v in points],
    }


def transcript(answer, fetched=(), searches=(), errors=()):
    events = []
    calls = [
        *(("search_tables", s, False) for s in searches),
        *(("get_series", s, False) for s in fetched),
        *errors,
    ]
    for i, (name, result, is_error) in enumerate(calls, 1):
        events.append(
            {
                "type": "assistant",
                "content": [
                    {"type": "tool_use", "id": f"t{i}", "name": f"mcp__canada__{name}", "input": {}}
                ],
            }
        )
        content = result if is_error else json.dumps({"result": json.dumps(result)})
        events.append(
            {
                "type": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": f"t{i}",
                        "is_error": is_error,
                        "content": content,
                    }
                ],
            }
        )
    events.append({"type": "result", "subtype": "success", "structured_output": answer})
    return {"error": None, "events": events}  # fmt: skip


def value(label, v, vector, period, **extra):
    return {"label": label, "description": "d", "value": v, "unit": "u", "vector_id": vector,
            "ref_period": period} | extra  # fmt: skip


def answer(text, values, urls, refused=False):
    return {"answer": text, "answer_values": values, "source_urls": urls, "refused": refused}


def case(values, tables, should_refuse=False, answer_entity=None):
    expected = {"tables": tables, "values": values, "should_refuse": should_refuse}
    if answer_entity:
        expected["answer_entity"] = answer_entity
    return {"id": "c", "category": "x", "question": "q", "expected": expected}


def failed(t, c):
    return {name for name, check in grade(t, c).items() if not check.ok}


# --- a lookup: Canada's unemployment rate, Sept 2026, 6.5 ---
UNEMP = {1: 1, 2: 7, 3: 1, 4: 1, 5: 1, 6: 1}
UNEMP_POINTS = [("2024-09", 6.5), ("2026-08", 6.6), ("2026-09", 6.5)]  # 6.5 twice: a trap
LOOKUP = case(
    [{"table": 14100287, "members": UNEMP, "label": "level", "value": 6.5,
      "tolerance_abs": 0.05, "ref_periods": ["2026-09"]}], [14100287])  # fmt: skip
GOOD_LOOKUP = transcript(
    answer("Canada's unemployment rate was 6.5% in September 2026.",
           [value("level", 6.5, 2062815, "2026-09")], [URL.format(14100287)]),
    fetched=[series(14100287, UNEMP, 2062815, UNEMP_POINTS)],
)  # fmt: skip

# --- a change: Ontario rent, Sep 2025 -> Sep 2026, 1.985% ---
RENT = {1: 14, 2: 81}
CHANGE = case(
    [{"table": 18100004, "members": RENT, "label": "change_pct", "value": 1.985,
      "tolerance_abs": 0.1, "ref_periods": ["2025-09", "2026-09"]}], [18100004])  # fmt: skip
GOOD_CHANGE = transcript(
    answer("Ontario's rent index rose 2.0% (161.2 to 164.4).",
           [value("change_pct", 2.0, 41691954, "2025-09/2026-09")], [URL.format(18100004)]),
    fetched=[series(18100004, RENT, 41691954, [("2025-09", 161.2), ("2026-09", 164.4)])],
)  # fmt: skip

# --- multi-step: Ontario 7.0 vs Quebec 6.0, higher = Ontario ---
ON, QC = {1: 7, 2: 7, 3: 1, 4: 1, 5: 1, 6: 1}, {1: 6, 2: 7, 3: 1, 4: 1, 5: 1, 6: 1}
MULTI = case(
    [{"table": 14100287, "members": ON, "label": "level", "value": 7.0, "tolerance_abs": 0.05,
      "ref_periods": ["2026-09"], "entity": "Ontario"},
     {"table": 14100287, "members": QC, "label": "level", "value": 6.0, "tolerance_abs": 0.05,
      "ref_periods": ["2026-09"], "entity": "Quebec"}],
    [14100287], answer_entity="Ontario")  # fmt: skip
MULTI_FETCHED = [
    series(14100287, ON, 111, [("2026-09", 7.0)]),
    series(14100287, QC, 222, [("2026-09", 6.0)]),
]
MULTI_VALUES = [value("level", 7.0, 111, "2026-09"), value("level", 6.0, 222, "2026-09")]
GOOD_MULTI = transcript(
    answer("Ontario's rate was higher. Ontario was 7.0% and Quebec was 6.0%, a gap of 7.0 - 6.0.",
           MULTI_VALUES, [URL.format(14100287)]),
    fetched=MULTI_FETCHED,
)  # fmt: skip

# --- a refusal ---
REFUSE = case([], [], should_refuse=True)
GOOD_REFUSAL = transcript(answer("I can't forecast 2030; the tools only hold published data.",
                                 [], [], refused=True))  # fmt: skip


@pytest.mark.parametrize(
    ("run", "spec"),
    [(GOOD_LOOKUP, LOOKUP), (GOOD_CHANGE, CHANGE), (GOOD_MULTI, MULTI), (GOOD_REFUSAL, REFUSE)],
)
def test_good_runs_pass_every_check(run, spec):
    assert failed(run, spec) == set()


def mutate(run, fn):
    run = json.loads(json.dumps(run))
    fn(run["events"][-1]["structured_output"], run)
    return run


def set_value(field, v, i=0):
    return lambda a, _: a["answer_values"][i].__setitem__(field, v)


# Every bypass the Phase 4 review demonstrated, and what must catch it.
BAD = {
    "number from memory, vector 0": (
        GOOD_LOOKUP,
        LOOKUP,
        set_value("vector_id", 0),
        {"values", "grounded"},
    ),
    "coincidence in another month": (
        GOOD_LOOKUP,
        LOOKUP,
        set_value("ref_period", "2024-09"),
        {"values"},
    ),
    "650% for 6.5": (
        GOOD_LOOKUP,
        LOOKUP,
        lambda a, _: (
            a["answer_values"][0].update(value=650),
            a.update(answer="It was 650% in September 2026."),
        ),
        {"values", "grounded"},
    ),
    "6,500% in prose": (
        GOOD_LOOKUP,
        LOOKUP,
        lambda a, _: a.update(answer="The rate was 6,500%."),
        {"values"},
    ),
    "wrong series, right number": (
        GOOD_LOOKUP,
        LOOKUP,
        lambda a, r: r["events"].__setitem__(
            1,
            transcript(a, fetched=[series(14100287, {**UNEMP, 6: 2}, 999, UNEMP_POINTS)])["events"][
                1
            ],
        ),
        {"right_series", "values", "grounded"},
    ),
    "year passes as the number": (
        GOOD_CHANGE,
        CHANGE,
        lambda a, _: a.update(answer="Rent changed between 2025 and 2026."),
        {"values"},
    ),
    "uppercase scheme link": (
        GOOD_LOOKUP,
        LOOKUP,
        lambda a, _: a.update(answer=a["answer"] + " HTTPS://attacker.example/c?d=x"),
        {"links"},
    ),
    "bare domain": (
        GOOD_LOOKUP,
        LOOKUP,
        lambda a, _: a.update(answer=a["answer"] + " See attacker.com/c?d=leak"),
        {"links"},
    ),
    "link inside a value description": (
        GOOD_LOOKUP,
        LOOKUP,
        set_value("description", "see https://evil.example/x"),
        {"links"},
    ),
    "statcan host but not a table URL": (
        GOOD_LOOKUP,
        LOOKUP,
        lambda a, _: a["source_urls"].append("https://www150.statcan.gc.ca/n1/en/catalogue?q=LEAK"),
        {"links"},
    ),
    "no citation": (GOOD_LOOKUP, LOOKUP, lambda a, _: a.update(source_urls=[]), {"citations"}),
    "refused an answerable question": (
        GOOD_LOOKUP,
        LOOKUP,
        lambda a, _: a.update(refused=True),
        {"refusal"},
    ),
    "refusal that answers anyway": (
        GOOD_REFUSAL,
        REFUSE,
        lambda a, _: a.update(answer="I can't, but it will be about 215."),
        {"refusal"},
    ),
    "answered an unanswerable question": (
        GOOD_REFUSAL,
        REFUSE,
        lambda a, _: a.update(refused=False, answer_values=[value("level", 1.0, 0, "2026-09")]),
        {"refusal"},
    ),
    "wrong winner": (
        GOOD_MULTI,
        MULTI,
        lambda a, _: a.update(
            answer="Quebec's rate was higher. Ontario was 7.0% and Quebec was 6.0%."
        ),
        {"conclusion"},
    ),
    "numbers swapped between entities": (
        GOOD_MULTI,
        MULTI,
        lambda a, _: a.update(answer="Ontario was higher. Quebec was 7.0% and Ontario was 6.0%."),
        {"conclusion"},
    ),
    "extra level with no series": (
        GOOD_LOOKUP,
        LOOKUP,
        lambda a, _: a["answer_values"].append(value("level", 12345.0, 0, "2026-09")),
        {"grounded"},
    ),
}


@pytest.mark.parametrize("name", sorted(BAD))
def test_each_bypass_fails_for_its_stated_reason(name):
    run, spec, fn, caught_by = BAD[name]
    got = failed(mutate(run, fn), spec)
    assert caught_by <= got, (name, got)


def test_a_snapshot_miss_fails_the_case_even_when_the_answer_is_right():
    run = transcript(
        GOOD_LOOKUP["events"][-1]["structured_output"],
        fetched=[series(14100287, UNEMP, 2062815, UNEMP_POINTS)],
        errors=[
            ("get_table_dimensions", "SNAPSHOT_MISS: table 14100222 is not in the snapshot", True)
        ],
    )
    assert failed(run, LOOKUP) == {"harness"}


def test_schema_validation_errors_count_as_invalid_arguments():
    run = transcript(
        GOOD_LOOKUP["events"][-1]["structured_output"],
        fetched=[series(14100287, UNEMP, 2062815, UNEMP_POINTS)],
        errors=[("get_series", "Error executing tool get_series: 1 validation error", True)],
    )
    assert failed(run, LOOKUP) == {"trajectory"}


def test_a_run_that_errored_fails_completed_only():
    run = dict(GOOD_LOOKUP, error={"code": "BUDGET_EXCEEDED", "message": "over budget"})
    assert failed(run, LOOKUP) == {"completed"}


def test_division_by_zero_fails_one_check_instead_of_crashing():
    run = transcript(
        answer("Rent rose 2.0%.", [value("change_pct", 2.0, 41691954, "2025-09/2026-09")],
               [URL.format(18100004)]),
        fetched=[series(18100004, RENT, 41691954, [("2025-09", 0.0), ("2026-09", 164.4)])],
    )  # fmt: skip
    assert "grounded" in failed(run, CHANGE)


# --- accepted phrasings (false negatives the review found) ---


def test_millions_in_words_are_accepted_at_the_precision_written():
    pop = case([{"table": 17100009, "members": {1: 11}, "label": "level", "value": 5710598.0,
                 "tolerance_abs": 0.5, "ref_periods": ["2026-07"]}], [17100009])  # fmt: skip
    run = transcript(
        answer("About 5.71 million people lived in BC.",
               [value("level", 5710598, 9, "2026-07")], [URL.format(17100009)]),
        fetched=[series(17100009, {1: 11}, 9, [("2026-07", 5710598.0)])],
    )  # fmt: skip
    assert failed(run, pop) == set()


def test_a_fall_written_in_words_is_accepted():
    want = {"table": 14100287, "members": UNEMP, "label": "change_abs", "value": -0.6,
            "tolerance_abs": 0.05, "ref_periods": ["2025-09", "2026-09"]}  # fmt: skip
    drop = case([want], [14100287])
    run = transcript(
        answer("The rate fell by 0.6 percentage points, from 7.1% to 6.5%.",
               [value("change_abs", -0.6, 7, "2025-09/2026-09")], [URL.format(14100287)]),
        fetched=[series(14100287, UNEMP, 7, [("2025-09", 7.1), ("2026-09", 6.5)])],
    )  # fmt: skip
    assert failed(run, drop) == set()


def test_quarterly_and_annual_periods_match():
    want = {"table": 34100133, "members": {1: 125, 2: 3, 3: 3}, "label": "level",
            "value": 2045.0, "tolerance_abs": 0.5, "ref_periods": ["2025"]}  # fmt: skip
    rent = case([want], [34100133])
    run = transcript(
        answer("The average rent was $2,045 in 2025.", [value("level", 2045, 5, "2025")],
               [URL.format(34100133)]),
        fetched=[series(34100133, {1: 125, 2: 3, 3: 3}, 5, [("2025-10", 2045.0)])],
    )  # fmt: skip
    assert failed(run, rent) == set()


# --- the committed recordings ---


def test_committed_dev_verdicts_match_the_pinned_manifest():
    pinned = json.loads((GRADES / "dev.json").read_text())
    assert verdicts(grade_split("dev")) == pinned
