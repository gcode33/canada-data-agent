"""A8 E2: `web/` imports every rule from `canada_agent` and never re-implements one, so the UI
can't drift from what the runtime checks and the graders enforce."""

from pathlib import Path

from canada_agent.links import CITABLE_URL

WEB = Path(__file__).resolve().parents[1]
SOURCES = [p for p in (WEB / "src").rglob("*") if p.suffix in {".py", ".ts", ".tsx", ".js"}]
FORBIDDEN = [
    "def run_events", "def check_answer", "def check_grounded", "def foreign_links",
    "def untrusted_text", "def series_values", "def contains_canary", "class ErrorCode(",
    CITABLE_URL.pattern, "statcan.gc.ca",
]  # fmt: skip


def test_web_sources_exist():
    assert any(p.name == "events.py" for p in SOURCES)


def test_no_rule_is_redefined_in_web():
    hits = [
        f"{p.relative_to(WEB)}: {needle}"
        for p in SOURCES
        for needle in FORBIDDEN
        if needle in p.read_text(encoding="utf-8")
    ]
    assert hits == [], "import these from canada_agent instead"
