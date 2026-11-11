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


GOLDEN = RETRIEVAL.parents[1] / "golden" / "cases.yaml"
GOLDEN_MIX = {"lookup": 12, "comparison": 10, "multi_step": 6, "unanswerable": 6, "injection": 6}
GOLDEN_SPLIT = {"dev": 24, "test": 16}
LABELS = {"level", "change_abs", "change_pct", "ratio"}
TWO_PERIODS = LABELS - {"level"}


def lint_golden(cases: list[dict[str, Any]]) -> list[str]:
    """Mix and split from SPEC 10.2; every answerable value must be CSV-verified."""
    errors: list[str] = []
    ids = [c.get("id") for c in cases]
    errors += [f"{i}: duplicate id" for i in {i for i in ids if ids.count(i) > 1}]
    for field, wanted in (("category", GOLDEN_MIX), ("split", GOLDEN_SPLIT)):
        counts = {k: sum(c.get(field) == k for c in cases) for k in wanted}
        if counts != wanted:
            errors.append(f"{field} mix is {counts}, SPEC wants {wanted}")
    for case in cases:
        where = case.get("id", "?")
        question = case.get("question") or ""
        if not question.strip() or len(question) > MAX_QUESTION:
            errors.append(f"{where}: question missing or over {MAX_QUESTION} characters")
        expected = case.get("expected") or {}
        values = expected.get("values") or []
        if expected.get("should_refuse"):
            if values or expected.get("tables"):
                errors.append(f"{where}: a refusal case must expect no values or tables")
            continue
        if not values:
            errors.append(f"{where}: an answerable case needs expected values")
        if case.get("verified_against_csv") is not True:
            errors.append(f"{where}: not verified against StatCan's CSV")
        for value in values:
            periods = value.get("ref_periods") or []
            if value.get("label") not in LABELS:
                errors.append(f"{where}: unknown label {value.get('label')!r}")
            elif len(periods) != (2 if value["label"] in TWO_PERIODS else 1):
                errors.append(f"{where}: wrong number of ref_periods for {value['label']}")
            if value.get("table") not in expected.get("tables", []):
                errors.append(f"{where}: value's table isn't in expected.tables")
            for alt in value.get("alternatives") or []:
                if not (
                    isinstance(alt.get("table"), int)
                    and alt.get("members")
                    and alt.get("ref_periods")
                ):
                    errors.append(f"{where}: alternative needs table, members and ref_periods")
        if case.get("category") == "injection" and not case.get("injection"):
            errors.append(f"{where}: injection case needs a vector and goal")
    # One series must not be graded in both splits, or the test split leaks from dev.
    splits: dict[tuple, set[str]] = {}
    for case in cases:
        for value in (case.get("expected") or {}).get("values") or []:
            key = (value.get("table"), tuple(sorted((value.get("members") or {}).items())))
            splits.setdefault(key, set()).add(case.get("split", ""))
    leaks = [key for key, seen in splits.items() if len(seen) > 1]
    errors += [f"series {table} {dict(m)} is in both dev and test" for table, m in leaks]
    injected = [
        (v.get("table"), tuple(sorted((v.get("members") or {}).items())))
        for c in cases
        if c.get("category") == "injection"
        for v in (c.get("expected") or {}).get("values") or []
    ]
    others = {
        (v.get("table"), tuple(sorted((v.get("members") or {}).items())))
        for c in cases
        if c.get("category") != "injection"
        for v in (c.get("expected") or {}).get("values") or []
    }
    errors += [
        f"injection series {t} reuses another case's series" for t, _ in set(injected) & others
    ]
    for case in cases:
        if case.get("category") == "multi_step" and not case["expected"].get("answer_entity"):
            errors.append(f"{case.get('id')}: multi_step needs answer_entity and per-value entity")
    reworded = sum(c.get("phrasing") == "own" for c in cases)
    if reworded < len(cases) * MIN_DAILY_SHARE:
        errors.append(f"only {reworded} reworded questions; at least a third are required")
    return errors


def main() -> None:
    errors, warnings = lint_retrieval(load(RETRIEVAL))
    errors += lint_golden(load(GOLDEN))
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}")
    print(f"{RETRIEVAL.name} + {GOLDEN.name}: {len(errors)} error(s), {len(warnings)} warning(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
