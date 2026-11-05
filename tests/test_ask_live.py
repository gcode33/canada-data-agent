import pytest

from canada_agent.ask import ask
from canada_agent.config import Settings

pytestmark = pytest.mark.live

QUESTION = (
    "By how much did the rent index in Ontario change from September 2025 to "
    "September 2026, in percent?"
)


def test_slice_answers_the_rent_question_with_a_citation():
    settings = Settings()
    result = ask(QUESTION, model=settings.agent_model, settings=settings, table=18100004)
    answer = result.answer
    assert answer["refused"] is False
    assert any(abs(v["value"] - 2.0) < 1e-9 for v in answer["answer_values"]), answer
    assert (
        "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810000401" in answer["source_urls"]
    )


def test_the_agent_finds_the_table_by_itself():
    settings = Settings()
    answer = ask(
        "How much did rent go up in Ontario last year?",
        model=settings.agent_model,
        settings=settings,
    ).answer
    assert answer["refused"] is False
    assert (
        "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810000401" in answer["source_urls"]
    )


@pytest.mark.parametrize(
    "question",
    [
        "What was Canada's unemployment rate in September 2026?",
        "How many people live in British Columbia right now?",
    ],
)
def test_demo_questions_get_cited_values(question):
    settings = Settings()
    answer = ask(question, model=settings.agent_model, settings=settings).answer
    assert answer["refused"] is False
    assert answer["answer_values"] and answer["source_urls"]


def test_a_forecast_is_refused():
    settings = Settings()
    answer = ask(
        "What will Ontario's rent index be in 2030?", model=settings.agent_model, settings=settings
    ).answer
    assert answer["refused"] is True
    assert answer["answer_values"] == []
