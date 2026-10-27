import pytest

from canada_agent.evals.lint import RETRIEVAL, lint_retrieval, load, overlap


def good(qid="r01", phrasing="daily", **extra):
    item = {
        "id": qid,
        "question": "How fast did prices for rent rise in September?",
        "expected_tables": [18100004],
        "primary_title": "Consumer Price Index, monthly, not seasonally adjusted",
        "phrasing": phrasing,
        "source": "https://www150.statcan.gc.ca/n1/daily-quotidien/261019/dq261019a-eng.htm",
    }
    return item | extra


def test_the_committed_retrieval_set_has_no_errors():
    errors, _ = lint_retrieval(load(RETRIEVAL))
    assert errors == []


def test_the_committed_set_has_fifteen_questions_and_a_third_daily():
    items = load(RETRIEVAL)
    assert len(items) == 15
    assert sum(i["phrasing"] == "daily" for i in items) >= 5


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"id": "q1"}, "id must look like r01"),
        ({"question": ""}, "question is required"),
        ({"question": "x" * 201}, "longer than 200"),
        ({"expected_tables": []}, "8-digit"),
        ({"expected_tables": [1810004]}, "8-digit"),
        ({"expected_tables": [18100004, 18100004]}, "duplicates"),
        ({"phrasing": "news"}, "phrasing must be"),
        ({"source": "https://example.com/blog"}, "The Daily source"),
        ({"primary_title": ""}, "primary_title is required"),
    ],
)
def test_each_rule_catches_its_mistake(change, message):
    errors, _ = lint_retrieval([good(**change)])
    assert any(message in e for e in errors), errors


def test_duplicate_ids_are_caught():
    errors, _ = lint_retrieval([good("r01"), good("r01")])
    assert any("duplicate id" in e for e in errors)


def test_too_few_daily_questions_is_an_error():
    items = [good("r01")] + [good(f"r0{i}", phrasing="own") for i in range(2, 5)]
    errors, _ = lint_retrieval(items)
    assert any("Daily phrasing" in e for e in errors)


def test_title_echo_is_a_warning_not_an_error():
    echo = good(question="Consumer Price Index monthly not seasonally adjusted")
    errors, warnings = lint_retrieval([echo])
    assert errors == []
    assert warnings and "table title" in warnings[0]


def test_overlap_ignores_stop_words_and_case():
    assert overlap("The Price of RENT", "rent price") == 1.0
    assert overlap("rent", "gasoline") == 0.0
