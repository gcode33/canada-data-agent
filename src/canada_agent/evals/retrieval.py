"""Offline retrieval eval: does search put the expected table in the top k? (SPEC §10.3)

Strict = the first listed table; lenient = any listed table. MRR is the mean of 1/rank of
the first hit (0 when absent), which rewards ranking the right table near the top.
`canada-eval-retrieval --method fts` prints a Markdown ablation row and per-question ranks.
"""

import argparse
import json
from collections.abc import Callable
from typing import Any

import psycopg

from canada_agent.config import Settings
from canada_agent.evals.lint import RETRIEVAL, load
from canada_agent.search.fts import search_fts

Searcher = Callable[[str], list[int]]


def first_rank(results: list[int], wanted: set[int]) -> int | None:
    for rank, table in enumerate(results, 1):
        if table in wanted:
            return rank
    return None


def score(questions: list[dict[str, Any]], search: Callable[[str], list[int]], k: int = 5) -> dict:
    per_question: dict[str, dict[str, int | None]] = {}
    for q in questions:
        results = search(q["id"])
        strict = first_rank(results, {q["expected_tables"][0]})
        lenient = first_rank(results, set(q["expected_tables"]))
        per_question[q["id"]] = {"strict": strict, "lenient": lenient}

    def recall(kind: str) -> float:
        return sum(1 for r in per_question.values() if r[kind] and r[kind] <= k) / len(questions)

    def mrr(kind: str) -> float:
        return sum(1 / r[kind] for r in per_question.values() if r[kind]) / len(questions)

    return {
        "k": k,
        "n": len(questions),
        "recall_at_k_strict": recall("strict"),
        "recall_at_k_lenient": recall("lenient"),
        "mrr_strict": mrr("strict"),
        "mrr_lenient": mrr("lenient"),
        "per_question": per_question,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--method", choices=["fts"], default="fts")
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()

    questions = load(RETRIEVAL)
    by_id = {q["id"]: q["question"] for q in questions}
    with psycopg.connect(Settings().database_url) as conn:
        report = score(questions, lambda qid: search_fts(conn, by_id[qid]), k=args.k)

    k = report["k"]
    print(
        f"| {args.method} | {report['recall_at_k_strict']:.2f} | "
        f"{report['recall_at_k_lenient']:.2f} | {report['mrr_strict']:.2f} | "
        f"{report['mrr_lenient']:.2f} |   <- recall@{k} strict, lenient; MRR strict, lenient"
    )
    print(json.dumps(report["per_question"], indent=1))


if __name__ == "__main__":
    main()
