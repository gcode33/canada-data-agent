from pathlib import Path

import psycopg
import pytest

from canada_agent.db.migrate import MigrationError, apply_migrations, discover

pytestmark = pytest.mark.db

REAL_MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def test_real_migrations_apply_and_enable_pgvector(fresh_db_url):
    applied = apply_migrations(fresh_db_url, REAL_MIGRATIONS)

    assert [m.version for m in applied] == [m.version for m in discover(REAL_MIGRATIONS)]
    with psycopg.connect(fresh_db_url) as conn:
        ext = conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'").fetchone()
    assert ext is not None


def test_second_run_applies_nothing(fresh_db_url):
    apply_migrations(fresh_db_url, REAL_MIGRATIONS)
    assert apply_migrations(fresh_db_url, REAL_MIGRATIONS) == []


def test_applies_in_numeric_order(fresh_db_url, tmp_path):
    (tmp_path / "0002_add_column.sql").write_text("ALTER TABLE t ADD COLUMN b int;")
    (tmp_path / "0010_insert.sql").write_text("INSERT INTO t (a, b) VALUES (1, 2);")
    (tmp_path / "0001_create.sql").write_text("CREATE TABLE t (a int);")

    applied = apply_migrations(fresh_db_url, tmp_path)

    assert [m.version for m in applied] == [1, 2, 10]


def test_failed_migration_rolls_back_and_is_not_recorded(fresh_db_url, tmp_path):
    (tmp_path / "0001_ok.sql").write_text("CREATE TABLE t (a int);")
    (tmp_path / "0002_broken.sql").write_text("CREATE TABLE u (a int); SELECT no_such_function();")

    with pytest.raises(MigrationError, match="0002_broken"):
        apply_migrations(fresh_db_url, tmp_path)

    with psycopg.connect(fresh_db_url) as conn:
        versions = [r[0] for r in conn.execute("SELECT version FROM schema_migrations")]
        u_exists = conn.execute("SELECT to_regclass('u')").fetchone()[0]
    assert versions == [1]
    assert u_exists is None


def test_edited_applied_migration_is_refused(fresh_db_url, tmp_path):
    first = tmp_path / "0001_create.sql"
    first.write_text("CREATE TABLE t (a int);")
    apply_migrations(fresh_db_url, tmp_path)

    first.write_text("CREATE TABLE t (a bigint);")

    with pytest.raises(MigrationError, match="checksum"):
        apply_migrations(fresh_db_url, tmp_path)


def test_rejects_badly_named_files(tmp_path):
    (tmp_path / "create_tables.sql").write_text("SELECT 1;")
    with pytest.raises(MigrationError, match="create_tables.sql"):
        discover(tmp_path)


def test_rejects_duplicate_versions(tmp_path):
    (tmp_path / "0001_a.sql").write_text("SELECT 1;")
    (tmp_path / "0001_b.sql").write_text("SELECT 1;")
    with pytest.raises(MigrationError, match="duplicate"):
        discover(tmp_path)
