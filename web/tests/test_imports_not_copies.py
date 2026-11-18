"""A8 E2: `web/` imports every rule from `canada_agent` and never re-implements one, so the UI
can't drift from what the runtime checks and the graders enforce. The U0 review showed the
first version only caught verbatim copies; this one catches renamed and lambda copies, any
StatCan URL rule (`statcan.gc` written plainly or regex-escaped), and scans all of `web/`."""

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1]
SKIP = {"tests", ".venv", "node_modules", "dist", "schema", ".pytest_cache", "__pycache__"}
SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".toml", ".json", ".html"}
RULES = (
    "run_events|check_answer|check_grounded|foreign_links|untrusted_text|series_values"
    "|contains_canary|table_url"
)
COPIES = [
    re.compile(rf"\b(def|function|const|let|var)\s+_?({RULES})\b"),  # a definition, renamed or not
    re.compile(rf"(^|[^.\w])_?({RULES})\s*=(?!=)", re.M),  # an assignment (lambda, arrow fn)
    re.compile(r"class\s+_?ErrorCode\b"),
    re.compile(r"statcan\\?\.gc|www150", re.I),  # a StatCan URL, plain or regex-escaped
]


def violations(text: str) -> list[str]:
    return [m.group(0) for rule in COPIES for m in rule.finditer(text)]


def sources() -> list[Path]:
    return [
        p
        for p in WEB.rglob("*")
        if p.is_file() and p.suffix in SUFFIXES and not SKIP & set(p.relative_to(WEB).parts)
    ]


@pytest.mark.parametrize(
    "copy",
    [
        "def foreign_links(text):",
        "def _foreign_links(text):",
        "foreign_links = lambda t: []",
        "const runEvents = 1; function run_events() {}",
        "export const untrusted_text = (s: string) => s;",
        r"CITABLE = re.compile(r'https://www150\.statcan\.gc\.ca/t1/tbl1/en/tv\.action\?pid=(\d{8})\d\d')",
        "const url = `https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=${id}01`;",
        "class ErrorCode(StrEnum):",
    ],
)
def test_the_scan_catches_known_copies(copy):
    assert violations(copy), copy


@pytest.mark.parametrize(
    "fine",
    [
        "from canada_agent.links import CITABLE_URL, foreign_links",
        "from canada_agent.ask import run_events",
        "found = foreign_links(text)",
        "x == foreign_links",
        "# suppressed by StatCan, never zero",
    ],
)
def test_the_scan_allows_imports_and_calls(fine):
    assert violations(fine) == []


def test_web_sources_exist():
    assert any(p.name == "events.py" for p in sources())


def test_no_rule_is_redefined_in_web():
    hits = [f"{p.relative_to(WEB)}: {v}" for p in sources() for v in violations(p.read_text())]
    assert hits == [], "import these from canada_agent instead"
