import pytest

from canada_agent.evals.retrieval import first_rank, score


def test_first_rank_is_one_based_and_none_when_missing():
    assert first_rank([5, 7, 9], {7}) == 2
    assert first_rank([5, 7, 9], {1}) is None


def test_score_reports_strict_and_lenient_recall_and_mrr():
    questions = [
        {"id": "r01", "expected_tables": [1, 2]},  # strict = 1, lenient = {1, 2}
        {"id": "r02", "expected_tables": [3]},
        {"id": "r03", "expected_tables": [4, 5]},
    ]
    results = {"r01": [9, 2, 1], "r02": [3], "r03": [8, 8, 8, 8, 8, 4]}

    report = score(questions, results.__getitem__, k=5)

    # r01: strict rank 3, lenient rank 2. r02: rank 1. r03: rank 6 = outside top 5.
    assert report["recall_at_k_strict"] == pytest.approx(2 / 3)
    assert report["recall_at_k_lenient"] == pytest.approx(2 / 3)
    assert report["mrr_strict"] == pytest.approx((1 / 3 + 1 + 1 / 6) / 3)
    assert report["mrr_lenient"] == pytest.approx((1 / 2 + 1 + 1 / 6) / 3)
    assert report["per_question"]["r03"] == {"strict": 6, "lenient": 6}


def test_a_question_with_no_hits_counts_as_a_miss():
    report = score([{"id": "r01", "expected_tables": [1]}], lambda _: [], k=5)
    assert report["recall_at_k_strict"] == 0
    assert report["mrr_strict"] == 0
