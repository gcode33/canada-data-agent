"""`canada-build-cards`: pull the live cube list, keep in-scope tables, store their cards.

Embedding happens separately (step 2.2), so this needs no API key. Re-running is cheap:
metadata comes from the HTTP cache and unchanged cards are skipped by hash.
"""

import json
import logging
import sys
from collections import Counter

import psycopg

from canada_agent.config import Settings
from canada_agent.index.cards import build_card
from canada_agent.index.scope import load_scope, select, subject_names
from canada_agent.index.store import CardRow, upsert_card
from canada_agent.logs import configure_logging
from canada_agent.series.backend import LiveBackend
from canada_agent.wds.cache import PostgresCache
from canada_agent.wds.client import WdsClient, WdsError

EMBEDDING_MODEL = "voyage-4"
log = logging.getLogger("canada_agent.index.build")


def main() -> None:
    configure_logging()
    settings = Settings()
    client = WdsClient(cache=PostgresCache(settings.database_url), max_rps=settings.statcan_max_rps)
    backend = LiveBackend(client)
    subjects = load_scope()

    cubes = client.get("getAllCubesListLite", {}, kind="metadata")
    selected, excluded = select(cubes, subjects)
    log.info(
        "scope",
        extra={
            "total": len(cubes),
            "selected": len(selected),
            "excluded": {k: len(v) for k, v in excluded.items()},
            "no_subject_ids": excluded["no_subject"],
        },
    )

    outcome: Counter[str] = Counter()
    failed: dict[int, str] = {}
    with psycopg.connect(settings.database_url) as conn:
        for i, cube in enumerate(selected, 1):
            pid = cube["productId"]
            try:
                meta = backend.metadata(pid)
            except WdsError as exc:
                outcome["failed"] += 1
                failed[pid] = str(exc.code)
                continue
            names = subject_names(cube, subjects)
            codes = [str(c) for c in cube.get("subjectCode") or []]
            row = CardRow.from_metadata(meta, codes, build_card(meta, names), EMBEDDING_MODEL)
            outcome["written" if upsert_card(conn, row) else "unchanged"] += 1
            if i % 50 == 0:
                print(f"  {i}/{len(selected)} tables", file=sys.stderr)

    summary = {"selected": len(selected), **outcome, "failed_ids": failed}
    print(json.dumps(summary, indent=2))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
