"""Draw docs/chart.svg: pass rate with its Wilson 95% interval, one row per measured run.

Reads the latest `evals/history.jsonl` entry for each (split, model, k). The interval is
over cases (k=1 rows), which are the independent unit; the README says so.

    uv run python evals/chart.py
"""

import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "evals" / "history.jsonl"
OUT = ROOT / "docs" / "chart.svg"
MODELS = {"claude-sonnet-5-5": "Sonnet 5.5", "claude-haiku-5-5": "Haiku 5.5"}

W, LEFT, RIGHT, TOP, ROW = 720, 250, 40, 56, 46

STYLE = """
  .surface { fill: #fcfcfb; }
  .ink { fill: #0b0b0b; } .ink2 { fill: #52514e; } .muted { fill: #898781; }
  .grid { stroke: #e1e0d9; } .axis { stroke: #c3c2b7; }
  .mark { fill: #2a78d6; stroke: #fcfcfb; } .whisker { stroke: #2a78d6; }
  @media (prefers-color-scheme: dark) {
    .surface { fill: #1a1a19; }
    .ink { fill: #f0efec; } .ink2 { fill: #c3c2b7; }
    .grid { stroke: #2c2c2a; } .axis { stroke: #383835; }
    .mark { fill: #3987e5; stroke: #1a1a19; } .whisker { stroke: #3987e5; }
  }
  text { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
"""


def rows(history: Path = HISTORY) -> list[dict]:
    """The latest entry per (split, model, k) on the newest prompt, so a run recorded under
    an older prompt can't stand in for today's agent; entries with no counted cases skipped."""
    try:
        lines = history.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    entries = [json.loads(line) for line in lines if line.strip()]
    entries = [e for e in entries if e.get("n_counted")]
    if not entries:
        return []
    prompt = entries[-1].get("prompt_version")
    latest: dict[tuple, dict] = {}
    for e in entries:
        if e.get("prompt_version") == prompt:
            latest[(e["split"], e["model"], e["k"])] = e
    # the held-out test split first: it is the headline
    return sorted(latest.values(), key=lambda e: (e["split"] != "test", e["model"], e["k"]))


def svg(entries: list[dict]) -> str:
    plot = W - LEFT - RIGHT
    h = TOP + ROW * len(entries) + 44

    def x(v: float) -> float:
        return LEFT + v * plot

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {h}" width="{W}" '
        f'height="{h}" role="img" aria-labelledby="t d">',
        "<title id='t'>Golden-set pass rate with 95% Wilson intervals</title>",
        "<desc id='d'>"
        + escape(
            "; ".join(
                f"{e['split']} split, {MODELS.get(e['model'], e['model'])}: "
                f"{e['pass_rate']:.2f} ({e['wilson_95'][0]:.2f} to {e['wilson_95'][1]:.2f}), "
                f"{e['n_counted']} cases"
                for e in entries
            )
        )
        + "</desc>",
        f"<style>{STYLE}</style>",
        f'<rect class="surface" width="{W}" height="{h}" rx="8"/>',
        '<text class="ink" x="16" y="28" font-size="15" font-weight="600">'
        "Golden-set pass rate, with 95% Wilson interval over cases</text>",
    ]
    for tick in (0, 0.25, 0.5, 0.75, 1.0):
        out.append(
            f'<line class="grid" x1="{x(tick):.1f}" x2="{x(tick):.1f}" y1="{TOP - 8}" '
            f'y2="{TOP + ROW * len(entries) - 8}" stroke-width="1"/>'
        )
        out.append(
            f'<text class="muted" x="{x(tick):.1f}" y="{TOP + ROW * len(entries) + 10}" '
            f'font-size="12" text-anchor="middle">{tick:.0%}</text>'
        )
    for i, e in enumerate(entries):
        y = TOP + ROW * i + 14
        lo, hi = e["wilson_95"]
        head = e["split"] == "test"
        split = "Held-out test" if head else "Dev (tuned on)" if e["split"] == "dev" else e["split"]
        label = f"{split} · {MODELS.get(e['model'], e['model'])}"
        detail = f"{e['n_counted']} cases, k={e['k']}, {str(e['timestamp'])[:10]}"
        out += [
            f'<text class="ink" x="16" y="{y - 2}" font-size="13" '
            f'font-weight="{600 if head else 400}">{escape(label)}</text>',
            f'<text class="ink2" x="16" y="{y + 14}" font-size="12">{escape(detail)}</text>',
            f'<line class="whisker" x1="{x(lo):.1f}" x2="{x(hi):.1f}" y1="{y}" y2="{y}" '
            'stroke-width="2" stroke-linecap="round"/>',
            f'<circle class="mark" cx="{x(e["pass_rate"]):.1f}" cy="{y}" r="5" stroke-width="2"/>',
            f'<text class="ink" x="{x(hi) + 8:.1f}" y="{y + 4}" font-size="12">'
            f"{e['pass_rate']:.0%}</text>",
        ]
    out.append(
        f'<text class="muted" x="16" y="{h - 12}" font-size="11">'
        "Snapshot data; search mostly full-text in these runs (README). "
        "Source: evals/history.jsonl</text>"
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    entries = rows()
    OUT.write_text(svg(entries), encoding="utf-8")
    for e in entries:
        print(e["split"], e["model"], e["pass_rate"], e["wilson_95"])
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
