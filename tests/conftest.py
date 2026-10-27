import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import sql

DEFAULT_URL = "postgresql://canada:canada@localhost:5432/canada"


@pytest.fixture
def fresh_db_url() -> Iterator[str]:
    """A brand-new empty database for one test, dropped afterwards."""
    base = os.environ.get("DATABASE_URL", DEFAULT_URL)
    name = f"test_{uuid.uuid4().hex[:12]}"
    try:
        admin = psycopg.connect(base, autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.skip(f"no PostgreSQL at DATABASE_URL ({exc.__class__.__name__}); run `make up`")
    with admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield psycopg.conninfo.make_conninfo(base, dbname=name)
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            drop = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)")
            admin.execute(drop.format(sql.Identifier(name)))
