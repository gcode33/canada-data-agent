"""Check the retrieval set against the live StatCan cube list. `make live` only."""

import httpx
import pytest

from canada_agent.evals.lint import RETRIEVAL, load

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def cubes():
    url = "https://www150.statcan.gc.ca/t1/wds/rest/getAllCubesListLite"
    return {c["productId"]: c for c in httpx.get(url, timeout=60).json()}


def test_every_expected_table_exists_and_is_active(cubes):
    for item in load(RETRIEVAL):
        for table in item["expected_tables"]:
            assert table in cubes, f"{item['id']}: table {table} does not exist"
            assert cubes[table]["archived"] == "2", f"{item['id']}: table {table} is archived"


def test_primary_titles_match_statcan(cubes):
    for item in load(RETRIEVAL):
        live = cubes[item["expected_tables"][0]]["cubeTitleEn"]
        assert item["primary_title"] == live, f"{item['id']}: title is {live!r}"
