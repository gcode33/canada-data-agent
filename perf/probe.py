"""One timed sample, run by `bench.py` with each side's own Python (so `canada_agent` is that
side's code). Prints the elapsed seconds for one measurement and nothing else."""

import asyncio
import os
import subprocess
import sys
import time

QUERY = "How much did rent go up in Ontario last year?"


def handshake() -> float:
    """Tool server start → ready to list its tools over stdio, as `claude -p` starts it."""
    from mcp import StdioServerParameters
    from mcp.client.client import Client

    server = StdioServerParameters(
        command=sys.executable, args=["-m", "canada_agent.mcp_server"], env=dict(os.environ)
    )

    async def run() -> float:
        start = time.perf_counter()
        async with Client(server) as client:
            await client.list_tools()
            return time.perf_counter() - start

    return asyncio.run(run())


def search() -> float:
    """One `search_tables` call in-process, after a warm-up call (full-text path, no Voyage)."""
    from canada_agent.config import Settings
    from canada_agent.search import tables

    index = tables.PostgresTableIndex(Settings().database_url, None)
    tables.search_tables(index, QUERY)
    start = time.perf_counter()
    tables.search_tables(index, QUERY)
    return time.perf_counter() - start


def import_time(module: str) -> float:
    """A fresh interpreter importing one module: what a CLI or tool-server start pays."""
    start = time.perf_counter()
    subprocess.run([sys.executable, "-c", f"import {module}"], check=True)  # noqa: S603
    return time.perf_counter() - start


MEASURES = {
    "import_ask": lambda: import_time("canada_agent.ask"),
    "import_mcp_server": lambda: import_time("canada_agent.mcp_server"),
    "handshake": handshake,
    "search_tables": search,
}

if __name__ == "__main__":
    print(f"{MEASURES[sys.argv[1]]():.6f}")
