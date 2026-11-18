"""`canada-web`: the web UI's command line (A8). `schema` and `build-demo`; `serve` comes in U2."""

import argparse
import json
import sys
from pathlib import Path

from canada_web.events import SCHEMA_VERSION, json_schema

WEB = Path(__file__).resolve().parents[2]
SCHEMA = WEB / "schema" / f"events.{SCHEMA_VERSION}.json"


def schema_text() -> str:
    return json.dumps(json_schema(), indent=1, sort_keys=True) + "\n"


def cmd_schema(args: argparse.Namespace) -> None:
    text = schema_text()
    if args.check:
        if not SCHEMA.exists() or SCHEMA.read_text() != text:
            sys.exit(f"{SCHEMA.relative_to(WEB)} is stale: run `canada-web schema` and commit it")
        print(f"{SCHEMA.relative_to(WEB)} is up to date")
        return
    SCHEMA.write_text(text)
    print(f"wrote {SCHEMA.relative_to(WEB)}")


def cmd_build_demo(args: argparse.Namespace) -> None:
    from canada_web.demo import DemoError, build

    try:
        written = build(Path(args.out))
    except DemoError as exc:
        sys.exit(f"build-demo refused: {exc}")
    print(f"wrote {len(written)} files to {args.out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    schema = sub.add_parser("schema", help="write the event JSON Schema (or --check it)")
    schema.add_argument("--check", action="store_true")
    demo = sub.add_parser("build-demo", help="build the replay demo's data (no model, no network)")
    demo.add_argument("--out", default=str(WEB / "frontend" / "public"))
    args = parser.parse_args()
    {"schema": cmd_schema, "build-demo": cmd_build_demo}[args.command](args)
