import json

import pytest

from canada_agent.evals.history import HISTORY, append, entry, percentile, validate, wilson

REPORT = {
    "cases": {"a": {"passed": True}, "b": {"passed": False}, "c": {"passed": True}},
    "pass_rate": 2 / 3,
    "by_category": {"lookup": 1.0, "comparison": 0.5},
    "search_recall_at_5_in_run": 1.0,
}
RESULTS = [
    {
        "duration_ms": 20000,
        "total_cost_usd": 0.02,
        "modelUsage": {
            "claude-sonnet-5-5": {
                "inputTokens": 10,
                "outputTokens": 5,
                "cacheReadInputTokens": 100,
                "cacheCreationInputTokens": 50,
            }
        },
    },
    {"duration_ms": 40000, "total_cost_usd": 0.03, "modelUsage": {}},
]


def make():
    return entry(
        kind="transcripts",
        split="dev",
        model="m",
        prompt_version="v1-x",
        k=1,
        report=REPORT,
        results=RESULTS,
    )


def test_an_entry_has_every_spec_field_and_validates():
    line = make()
    assert validate(line) == []
    assert line["tokens"] == {"input": 10, "output": 5, "cache_read": 100, "cache_creation": 50}
    assert line["api_equivalent_usd"] == 0.05
    assert line["latency_p50_s"] == 30.0
    assert line["n_cases"] == 3


def test_validation_catches_missing_and_mistyped_fields():
    line = make()
    del line["model"]
    line["k"] = "1"
    assert validate(line) == ["missing model", "k should be int"]


def test_append_refuses_a_bad_line_and_writes_a_good_one(tmp_path):
    path = tmp_path / "h.jsonl"
    with pytest.raises(ValueError):
        append({"kind": "x"}, path)
    append(make(), path)
    append(make(), path)
    assert len(path.read_text().splitlines()) == 2


def test_wilson_matches_known_values():
    low, high = wilson(12, 16)  # 75% on 16 cases
    assert low == pytest.approx(0.505, abs=0.002)
    assert high == pytest.approx(0.898, abs=0.002)
    assert wilson(0, 0) == (0.0, 1.0)
    assert wilson(16, 16)[1] == 1.0


def test_percentile():
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
    assert percentile([5.0], 0.95) == 5.0
    assert percentile([], 0.5) == 0.0


def test_every_committed_history_line_validates():
    if not HISTORY.exists():
        pytest.skip("no history yet")
    for number, raw in enumerate(HISTORY.read_text().splitlines(), 1):
        assert validate(json.loads(raw)) == [], number
