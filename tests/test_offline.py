"""`canada-ask --offline`: recorded model choices, real tools and checks."""

import json

import pytest
from test_mcp_server import RENT_ARGS, server

from canada_agent.ask import TOOL_PREFIX, AskError, render
from canada_agent.config import Settings
from canada_agent.offline import ask_offline, recordings

URL = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810000401"
QUESTION = "How much did rent go up in Ontario?"


def recorded(folder, name="c1", vector=41691954, url=URL, **extra):
    answer = {
        "answer": "Ontario rent rose.",
        "answer_values": [{"label": "level", "description": "rent", "value": 164.4,
                           "unit": "index", "vector_id": vector, "ref_period": "2026-09"}],
        "source_urls": [url],
        "refused": False,
    }  # fmt: skip
    events = [
        {"type": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": f"{TOOL_PREFIX}get_series", "input": RENT_ARGS}
        ]},  # the slimmed shape transcripts are saved in
        {"type": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}]},
        {"type": "result", "subtype": "success", "is_error": False, "num_turns": 2,
         "structured_output": answer, "total_cost_usd": 0.01},
    ]  # fmt: skip
    body = {"question": QUESTION, "poison": None, "error": None, "events": events} | extra
    (folder / f"{name}.json").write_text(json.dumps(body))


def test_a_recorded_run_replays_through_the_real_tools_and_checks(tmp_path):
    recorded(tmp_path)
    result, source = ask_offline(QUESTION, settings=Settings(), folder=tmp_path, server=server())
    assert [c.name for c in result.tool_calls] == ["get_series"]
    assert result.tool_calls[0].latency_s is not None  # the tool really answered
    assert result.api_equivalent_usd == 0  # no model ran
    assert "offline: model choices replayed from" in render(result, source)


def test_a_recorded_answer_the_tools_no_longer_support_fails(tmp_path):
    recorded(tmp_path, vector=999)  # the tool returns 41691954
    with pytest.raises(AskError, match="cited vector 999"):
        ask_offline(QUESTION, settings=Settings(), folder=tmp_path, server=server())


def test_a_foreign_link_is_still_rejected(tmp_path):
    recorded(tmp_path, url="https://statcan-data.de/t")
    with pytest.raises(AskError, match="foreign link"):
        ask_offline(QUESTION, settings=Settings(), folder=tmp_path, server=server())


def test_poisoned_and_failed_runs_are_not_offered(tmp_path):
    recorded(tmp_path, "good")
    recorded(tmp_path, "poisoned", question="q2", poison={"goal": "exfil_url"})
    recorded(tmp_path, "failed", question="q3", error={"code": "BUDGET_EXCEEDED"})
    assert [t["question"] for t in recordings(tmp_path).values()] == [QUESTION]


def test_an_unrecorded_question_lists_what_can_be_replayed(tmp_path):
    recorded(tmp_path)
    with pytest.raises(AskError, match="can replay:\n  How much did rent go up in Ontario"):
        ask_offline("Is it sunny?", settings=Settings(), folder=tmp_path, server=server())


def test_matching_ignores_case_and_punctuation(tmp_path):
    recorded(tmp_path)
    result, _ = ask_offline(
        "how much did RENT go up in ontario", settings=Settings(), folder=tmp_path, server=server()
    )
    assert result.answer["refused"] is False
