"""Recompute every golden value from StatCan's full-table CSV download (PLAN header, A7).

The builder also writes the expected answers, so this script is the independent check. It
shares no code with the WDS client: only the Python standard library, PyYAML, and a
different StatCan path (the CSV download, not the API). A test asserts that it never imports
`canada_agent`. Run: `make verify-golden`. Needs network on first use; CSVs are cached in
data/csv (gitignored) because some are large.
"""

import csv
import io
import sys
import urllib.request
import zipfile
from collections.abc import Iterator
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "evals" / "golden"
CACHE = ROOT / "data" / "csv"
CSV_URL = "https://www150.statcan.gc.ca/n1/tbl/csv/{table}-eng.zip"


def download(table: int) -> Path:
    path = CACHE / f"{table}.zip"
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(  # noqa: S310 - fixed https StatCan URL
            CSV_URL.format(table=table), headers={"User-Agent": "canada-data-agent-evals"}
        )
        with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310
            path.write_bytes(response.read())
    return path


def rows(table: int) -> Iterator[dict[str, str]]:
    with zipfile.ZipFile(download(table)) as archive, archive.open(f"{table}.csv") as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig"))


def period(ref_date: str) -> str:
    """2026-07-01 and 2026-09 become YYYY-MM; annual dates like 2025 stay as they are."""
    return ref_date[:7] if ref_date[4:5] == "-" else ref_date


def coordinate(members: dict) -> str:
    """Member ids in dimension order, joined the way the CSV's COORDINATE column writes them."""
    return ".".join(str(members[position]) for position in sorted(members))


def load_series(table: int, wanted: set[str]) -> dict[str, dict[str, dict[str, str]]]:
    """{coordinate: {YYYY-MM: row}} for the coordinates asked for."""
    found: dict[str, dict[str, dict[str, str]]] = {c: {} for c in wanted}
    for row in rows(table):
        coord = row["COORDINATE"]
        if coord in found:
            found[coord][period(row["REF_DATE"])] = row
    return found


def recompute(label: str, periods: list[str], series: dict[str, dict[str, str]]) -> float:
    numbers = [float(series[p]["VALUE"]) for p in periods]
    if label == "level":
        return numbers[0]
    first, last = numbers[0], numbers[-1]
    if label == "change_pct":
        return (last - first) / first * 100
    if label == "change_abs":
        return last - first
    if label == "ratio":
        return first / last
    raise ValueError(f"unknown label {label!r}")


def cases() -> list[dict]:
    out: list[dict] = []
    for path in sorted(GOLDEN.glob("*.yaml")):
        out.extend(yaml.safe_load(path.read_text(encoding="utf-8")))
    return out


def verify(items: list[dict]) -> list[str]:
    """Problems found; empty means every value matches StatCan's CSV."""
    needed: dict[int, set[str]] = {}
    for case in items:
        for value in case["expected"].get("values", []):
            needed.setdefault(value["table"], set()).add(coordinate(value["members"]))
    data = {t: load_series(t, coords) for t, coords in needed.items()}

    problems: list[str] = []
    for case in items:
        for value in case["expected"].get("values", []):
            where = f"{case['id']} {value['label']}"
            series = data[value["table"]][coordinate(value["members"])]
            periods = value["ref_periods"]
            missing = [p for p in periods if p not in series or not series[p]["VALUE"]]
            if missing:
                problems.append(f"{where}: no CSV value for {missing}")
                continue
            got = recompute(value["label"], periods, series)
            # Exact up to how the case stores it: levels as published, changes to 3 decimals.
            # The case's tolerance_abs is for grading answers, never for checking the key.
            exact = 1e-9 * max(1.0, abs(got)) if value["label"] == "level" else 0.0006
            if abs(got - value["value"]) > exact:
                problems.append(f"{where}: CSV gives {got:.4f}, case says {value['value']}")
    return problems


def main() -> None:
    items = cases()
    problems = verify(items)
    for problem in problems:
        print(problem, file=sys.stderr)
    checked = sum(len(c["expected"].get("values", [])) for c in items)
    print(f"{checked} values in {len(items)} cases checked against StatCan CSVs")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
