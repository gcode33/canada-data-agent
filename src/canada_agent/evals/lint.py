"""Lint the eval sets so a malformed or lazy question fails CI, not an eval run.

Errors fail the build. Warnings (e.g. a question that just repeats the table title's words,
which flatters keyword search) are printed for a human to judge.
"""

import re
import sys
from pathlib import Path
from typing import Any

import yaml

RETRIEVAL = Path(__file__).resolve().parents[3] / "evals" / "retrieval" / "questions.yaml"
ID = re.compile(r"^r\d{2}$")
MAX_QUESTION = 200  # search_tables accepts queries up to 200 characters (SPEC §8)
MIN_DAILY_SHARE = 1 / 3  # SPEC §10.2
OVERLAP_WARN = 0.3
STOP = frozenset({
    "a", "an", "and", "are", "at", "by", "did", "do", "does", "for", "from", "how", "in",
    "is", "it", "like", "of", "on", "or", "over", "per", "right", "the", "this", "to", "up",
    "was", "were", "what", "who", "with", "year",
})  # fmt: skip


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP}


def overlap(a: str, b: str) -> float:
    wa, wb = words(a), words(b)
    return len(wa & wb) / len(wa | wb) if wa | wb else 0.0


def lint_retrieval(items: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    if not isinstance(items, list) or not items:
        return ["retrieval set must be a non-empty list"], []
    for i, item in enumerate(items):
        where = item.get("id", f"#{i}") if isinstance(item, dict) else f"#{i}"
        if not isinstance(item, dict):
            errors.append(f"{where}: must be a mapping")
            continue
        qid = item.get("id", "")
        if not ID.match(str(qid)):
            errors.append(f"{where}: id must look like r01")
        elif qid in seen:
            errors.append(f"{where}: duplicate id")
        seen.add(str(qid))

        question = item.get("question")
        if not isinstance(question, str) or not question.strip():
            errors.append(f"{where}: question is required")
            question = ""
        elif len(question) > MAX_QUESTION:
            errors.append(f"{where}: question longer than {MAX_QUESTION} characters")

        tables = item.get("expected_tables")
        if (
            not isinstance(tables, list)
            or not tables
            or not all(isinstance(t, int) and 10_000_000 <= t <= 99_999_999 for t in tables)
        ):
            errors.append(f"{where}: expected_tables must be a list of 8-digit table ids")
        elif len(set(tables)) != len(tables):
            errors.append(f"{where}: expected_tables has duplicates")

        phrasing = item.get("phrasing")
        if phrasing not in {"daily", "own"}:
            errors.append(f"{where}: phrasing must be 'daily' or 'own'")
        if phrasing == "daily" and not str(item.get("source", "")).startswith(
            "https://www150.statcan.gc.ca/n1/daily-quotidien/"
        ):
            errors.append(f"{where}: daily phrasing needs a The Daily source URL")

        title = item.get("primary_title")
        if not isinstance(title, str) or not title:
            errors.append(f"{where}: primary_title is required")
        elif question and (score := overlap(question, title)) >= OVERLAP_WARN:
            warnings.append(
                f"{where}: question shares {score:.0%} of its words with the "
                "table title; keyword search will find it too easily"
            )

    daily = sum(1 for it in items if isinstance(it, dict) and it.get("phrasing") == "daily")
    if daily / len(items) < MIN_DAILY_SHARE:
        errors.append(f"only {daily}/{len(items)} questions use Daily phrasing; need at least 1/3")
    return errors, warnings


def load(path: Path) -> Any:
    with path.open() as f:
        return yaml.safe_load(f)


def main() -> None:
    errors, warnings = lint_retrieval(load(RETRIEVAL))
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}")
    print(f"{RETRIEVAL.name}: {len(errors)} error(s), {len(warnings)} warning(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
