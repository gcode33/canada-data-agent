"""A8 E2: `web/` imports every rule from `canada_agent` and never re-implements one, so the UI
can't drift from what the runtime checks and the graders enforce. The U0 review showed the
first version only caught verbatim copies; this one catches renamed and lambda copies (Python
by its syntax tree, so keyword arguments don't count; JS/TS by pattern), any StatCan URL rule
(`statcan.gc` written plainly or regex-escaped), and scans all of `web/`."""

import ast
import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1]
SKIP = {"tests", ".venv", "node_modules", "dist", "schema", ".pytest_cache", "__pycache__"}
SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".toml", ".json", ".html"}
NAMES = {
    "run_events", "check_answer", "check_grounded", "foreign_links", "untrusted_text",
    "series_values", "contains_canary", "table_url", "ErrorCode", "CITABLE_URL",
}  # fmt: skip
STATCAN = re.compile(r"statcan\\?\.gc|www150", re.I)
JS_NAMES = "|".join(sorted(NAMES))
JS_DEFINES = re.compile(
    rf"\b(function|const|let|var|class)\s+_?({JS_NAMES})\b"
    rf"|^\s*(export\s+)?_?({JS_NAMES})\s*=(?!=)",
    re.M,
)


def _python_definitions(text: str) -> list[str]:
    """Names from NAMES that the code defines or assigns (a leading underscore counts)."""
    found = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            targets = [node.name]
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        elif isinstance(node, ast.AnnAssign) and node.value is not None:  # a bare annotation is
            targets = [node.target.id] if isinstance(node.target, ast.Name) else []  # a field
        else:
            continue
        found += [f"defines {t}" for t in targets if t.lstrip("_") in NAMES]
    return found


def violations(text: str, python: bool = True) -> list[str]:
    hits = [m.group(0) for m in STATCAN.finditer(text)]
    if python:
        try:
            return hits + _python_definitions(text)
        except SyntaxError:
            pass
    return hits + [m.group(0) for m in JS_DEFINES.finditer(text)]


def sources() -> list[Path]:
    return [
        p
        for p in WEB.rglob("*")
        if p.is_file() and p.suffix in SUFFIXES and not SKIP & set(p.relative_to(WEB).parts)
    ]


@pytest.mark.parametrize(
    ("copy", "python"),
    [
        ("def foreign_links(text):\n    return []", True),
        ("def _foreign_links(text):\n    return []", True),
        ("foreign_links = lambda t: []", True),
        ("class ErrorCode(StrEnum):\n    X = 'x'", True),
        ("CITABLE_URL = None", True),
        ("CITABLE_URL: re.Pattern = re.compile('x')", True),
        (r"URL = re.compile(r'https://www150\.statcan\.gc\.ca/t1/tbl1/en/tv\.action')", True),
        ("function run_events() {}", False),
        ("export const untrusted_text = (s: string) => s;", False),
        ("const url = `https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=${id}01`;", False),
    ],
)
def test_the_scan_catches_known_copies(copy, python):
    assert violations(copy, python), copy


@pytest.mark.parametrize(
    ("fine", "python"),
    [
        ("from canada_agent.links import CITABLE_URL, foreign_links", True),
        ("found = foreign_links(text)", True),
        ("x = Series(\n    table_url=table_url(pid),\n    step_id=s,\n)", True),
        ("run(foreign_links=foreign_links)", True),
        ("# suppressed by StatCan, never zero", True),
        ("class Series(BaseModel):\n    table_url: str", True),
        ("const found = series.points.length;", False),
    ],
)
def test_the_scan_allows_imports_calls_and_keyword_arguments(fine, python):
    assert violations(fine, python) == []


def test_web_sources_exist():
    assert any(p.name == "events.py" for p in sources())


def test_no_rule_is_redefined_in_web():
    hits = [
        f"{p.relative_to(WEB)}: {v}"
        for p in sources()
        for v in violations(p.read_text(), python=p.suffix == ".py")
    ]
    assert hits == [], "import these from canada_agent instead"
