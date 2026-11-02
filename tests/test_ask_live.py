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
