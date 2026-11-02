"""Offline retrieval eval: does search put the expected table in the top k? (SPEC §10.3)

Strict = the first listed table; lenient = any listed table. MRR is the mean of 1/rank of
the first hit (0 when absent), which rewards ranking the right table near the top.
`canada-eval-retrieval --method fts|vector` prints a Markdown ablation row and per-question
ranks. `--record` embeds unrecorded questions live (needs VOYAGE_API_KEY) and stores them,
so later runs, including CI, replay them with no key; that's `make record`.
"""

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

import psycopg

from canada_agent.config import Settings
from canada_agent.embed.voyage import VoyageClient
from canada_agent.evals.lint import RETRIEVAL, load
from canada_agent.search.fts import search_fts
from canada_agent.search.vector import query_vector, search_vector

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
    parser.add_argument("--method", choices=["fts", "vector"], default="fts")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--record", action="store_true", help="embed unrecorded questions")
    args = parser.parse_args()

    settings = Settings()
    questions = load(RETRIEVAL)
    by_id = {q["id"]: q["question"] for q in questions}
    client = VoyageClient(settings.voyage_api_key.get_secret_value()) if args.record else None
    unrecorded: list[str] = []

    with psycopg.connect(settings.database_url, autocommit=True) as conn:

        def search(qid: str) -> list[int]:
            if args.method == "fts":
                return search_fts(conn, by_id[qid])
            vector = query_vector(conn, by_id[qid], client)
            if vector is None:
                unrecorded.append(qid)  # scored as a miss, never silently skipped
                return []
            return search_vector(conn, vector)

        report = score(questions, search, k=args.k)
    if unrecorded:
        print(
            f"warning: {len(unrecorded)} unrecorded questions scored as misses: {unrecorded}"
            " (run `make record`)",
            file=sys.stderr,
        )

    k = report["k"]
    print(
        f"| {args.method} | {report['recall_at_k_strict']:.2f} | "
        f"{report['recall_at_k_lenient']:.2f} | {report['mrr_strict']:.2f} | "
        f"{report['mrr_lenient']:.2f} |   <- recall@{k} strict, lenient; MRR strict, lenient"
    )
    print(json.dumps(report["per_question"], indent=1))
    if unrecorded:
        sys.exit(1)  # in CI: a question was added without `make record`


if __name__ == "__main__":
    main()
