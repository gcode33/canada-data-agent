"""Which StatCan tables are indexed (SPEC §7.1)."""

import tomllib
from pathlib import Path
from typing import Any

SCOPE = Path(__file__).resolve().parents[3] / "config" / "scope.toml"
ACTIVE = "2"  # WDS `archived`: "1" = archived, "2" = current


def load_scope(path: Path = SCOPE) -> dict[str, str]:
    with path.open("rb") as f:
        return tomllib.load(f)["subjects"]


def select(
    cubes: list[dict[str, Any]], subjects: dict[str, str]
) -> tuple[list[dict[str, Any]], dict[str, list[int]]]:
    """Split the cube list into in-scope tables and the ids excluded, by reason."""
    selected: list[dict[str, Any]] = []
    excluded: dict[str, list[int]] = {"archived": [], "no_subject": [], "out_of_scope": []}
    for cube in cubes:
        pid = cube["productId"]
        codes = [str(c) for c in cube.get("subjectCode") or []]
        if cube.get("archived") != ACTIVE:
            excluded["archived"].append(pid)
        elif not codes:
            excluded["no_subject"].append(pid)
        elif any(code[:2] in subjects for code in codes):
            selected.append(cube)
        else:
            excluded["out_of_scope"].append(pid)
    return selected, excluded


def subject_names(cube: dict[str, Any], subjects: dict[str, str]) -> list[str]:
    prefixes = {str(c)[:2] for c in cube.get("subjectCode") or []}
    return [subjects[p] for p in sorted(prefixes) if p in subjects]
