"""`canada-ask --offline`: recorded model choices, real tools and checks."""

import asyncio
import json

import pytest
from test_mcp_server import RENT_ARGS, FakeIndex, server

from canada_agent import offline
from canada_agent.ask import PROMPT_VERSION, TOOL_PREFIX, AskError, render
from canada_agent.config import Settings
from canada_agent.errors import ErrorCode
from canada_agent.offline import ask_offline, recordings, stdio_server

URL = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810000401"
QUESTION = "How much did rent go up in Ontario?"
SEARCH = {"query": "rent", "k": 2}
FOUND = json.dumps({"result": json.dumps({"results": [{"product_id": 18100004},
                                                      {"product_id": 18100001}]})})  # fmt: skip


def recorded(folder, name="c1", vector=41691954, url=URL, calls=None, **extra):
    answer = {
        "answer": "Ontario rent rose.",
        "answer_values": [{"label": "change_pct", "description": "rent", "value": 2.0,
                           "unit": "percent", "vector_id": vector, "ref_period": "2026-09"}],
        "source_urls": [url],
        "refused": False,
    }  # fmt: skip
    events = []
    default = [("get_series", RENT_ARGS, "x")]
    for i, (tool, args, result) in enumerate(default if calls is None else calls):
        events += [
            {"type": "assistant", "content": [
                {"type": "tool_use", "id": f"t{i}", "name": f"{TOOL_PREFIX}{tool}", "input": args}
            ]},  # the slimmed shape transcripts are saved in
            {"type": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"t{i}", "content": result}
            ]},
        ]  # fmt: skip
    events.append({"type": "result", "subtype": "success", "is_error": False, "num_turns": 2,
                   "structured_output": answer, "total_cost_usd": 0.01})  # fmt: skip
    body = {"question": QUESTION, "poison": None, "error": None, "prompt_version": PROMPT_VERSION,
            "events": events} | extra  # fmt: skip
    (folder / f"{name}.json").write_text(json.dumps(body))


def replay(folder, question=QUESTION, **kw):
    return ask_offline(question, settings=Settings(), folder=folder, server=kw.pop("srv", server()))


def test_a_recorded_run_replays_through_the_real_tools_and_checks(tmp_path):
    recorded(tmp_path)
    result, source = replay(tmp_path)
    assert [c.name for c in result.tool_calls] == ["get_series"]
    assert result.api_equivalent_usd == 0  # no model ran
    assert "Not a model run" in render(result, source)


def test_a_refusal_with_no_calls_says_so_instead_of_claiming_calls_passed(tmp_path):
    recorded(tmp_path, calls=[])
    body = json.loads((tmp_path / "c1.json").read_text())
    body["events"][-1]["structured_output"] |= {"answer_values": [], "source_urls": [],
                                                "refused": True}  # fmt: skip
    (tmp_path / "c1.json").write_text(json.dumps(body))
    result, source = replay(tmp_path)
    assert "no tool calls to replay" in render(result, source)


def test_a_recorded_answer_the_tools_no_longer_support_fails(tmp_path):
    recorded(tmp_path, vector=999)  # the tool returns 41691954
    with pytest.raises(AskError, match="cited vector 999"):
        replay(tmp_path)


def test_a_foreign_link_is_still_rejected(tmp_path):
    recorded(tmp_path, url="https://statcan-data.de/t")
    with pytest.raises(AskError, match="foreign link"):
        replay(tmp_path)


# --- Phase 6 review: a replay must fail when the plumbing is broken ---


def test_search_returning_other_tables_than_recorded_fails(tmp_path):
    # An empty or broken index: the code review's "passes with the database down" finding.
    calls = [("search_tables", SEARCH, FOUND), ("get_series", RENT_ARGS, "x")]
    recorded(tmp_path, calls=calls)
    replay(tmp_path, srv=server(index=FakeIndex(tables=(18100004, 18100001))))  # same: passes
    with pytest.raises(AskError, match="different tables") as caught:
        replay(tmp_path, srv=server(index=FakeIndex(tables=(46100092,))))
    assert caught.value.code == ErrorCode.UPSTREAM_UNAVAILABLE


def test_a_call_that_errors_on_replay_but_not_when_recorded_fails(tmp_path):
    recorded(tmp_path, calls=[("get_table_dimensions", {"product_id": 42}, "ok")])
    with pytest.raises(AskError, match="failed on replay but not when recorded"):
        replay(tmp_path)


def test_the_call_budget_stops_the_replay_before_the_extra_call_runs(tmp_path):
    recorded(tmp_path, calls=[("get_series", RENT_ARGS, "x")] * 9)
    with pytest.raises(AskError, match="budget of 8") as caught:
        replay(tmp_path)
    assert caught.value.code == ErrorCode.BUDGET_EXCEEDED


def test_a_hung_server_is_over_the_time_budget(tmp_path, monkeypatch):
    recorded(tmp_path)

    async def hang(*_):
        await asyncio.sleep(5)

    monkeypatch.setattr(offline, "_replay", hang)
    settings = Settings(question_timeout_s=0.1)
    with pytest.raises(AskError, match="budget") as caught:
        ask_offline(QUESTION, settings=settings, folder=tmp_path, server=server())
    assert caught.value.code == ErrorCode.BUDGET_EXCEEDED


def test_a_malformed_recording_is_a_bug_not_an_outage(tmp_path):
    recorded(tmp_path)
    body = json.loads((tmp_path / "c1.json").read_text())
    del body["events"][0]["content"][0]["id"]
    (tmp_path / "c1.json").write_text(json.dumps(body))
    with pytest.raises(KeyError):
        replay(tmp_path)


# --- which recordings may be replayed ---


def test_only_clean_current_recordings_are_offered(tmp_path):
    recorded(tmp_path, "good")
    recorded(tmp_path, "poisoned", question="q2", poison={"goal": "exfil_url"})
    recorded(tmp_path, "failed", question="q3", error={"code": "BUDGET_EXCEEDED"})
    recorded(tmp_path, "stale", question="q4", prompt_version="v1-old")
    (tmp_path / "torn.json").write_text('{"question": "q5", "ev')
    assert [t["question"] for t in recordings(tmp_path).values()] == [QUESTION]


def test_runs_the_graders_failed_are_not_replayed(tmp_path):
    folder = tmp_path / "transcripts" / "dev"
    folder.mkdir(parents=True)
    recorded(folder, "good")
    recorded(folder, "wrong", question="q2")
    (tmp_path / "grades").mkdir()
    (tmp_path / "grades" / "dev.json").write_text(
        json.dumps({"good": {"passed": True}, "wrong": {"passed": False}})
    )
    assert [t["question"] for t in recordings(folder).values()] == [QUESTION]


def test_an_unrecorded_question_lists_what_can_be_replayed(tmp_path):
    recorded(tmp_path)
    with pytest.raises(AskError, match="can replay:\n  How much did rent go up in Ontario"):
        replay(tmp_path, "Is it sunny?")


def test_matching_ignores_case_accents_and_punctuation_but_not_decimals(tmp_path):
    recorded(tmp_path)
    replay(tmp_path, "how much did RENT go up in ontario")
    assert offline._key("Did prices rise 2.5%?") != offline._key("Did prices rise 2 5%?")
    assert offline._key("Québec") == offline._key("quebec")


def test_the_stdio_server_is_pinned_to_the_snapshot_whatever_the_environment(monkeypatch):
    monkeypatch.setenv("DATA_BACKEND", "live")
    monkeypatch.setenv("POISON", '{"goal": "exfil_url"}')
    params = stdio_server(Settings())
    assert params.env["DATA_BACKEND"] == "snapshot"
    assert params.env["POISON"] == ""
    assert params.args == ["-m", "canada_agent.mcp_server"]
