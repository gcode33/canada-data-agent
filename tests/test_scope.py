from canada_agent.index.scope import load_scope, select


def cube(pid, subjects, archived="2"):
    return {
        "productId": pid,
        "cubeTitleEn": f"t{pid}",
        "subjectCode": subjects,
        "archived": archived,
    }


def test_committed_scope_has_the_six_v1_subjects():
    assert set(load_scope()) == {"11", "14", "17", "18", "34", "46"}


def test_selects_by_two_digit_prefix_of_any_subject_code():
    cubes = [cube(1, ["18"]), cube(2, ["1802"]), cube(3, ["36", "46"]), cube(4, ["36"])]
    selected, excluded = select(cubes, {"18": "Prices", "46": "Housing"})
    assert [c["productId"] for c in selected] == [1, 2, 3]
    assert excluded["out_of_scope"] == [4]


def test_archived_and_subjectless_tables_are_excluded_and_reported():
    cubes = [cube(1, ["18"], archived="1"), cube(2, None), cube(3, []), cube(4, ["18"])]
    selected, excluded = select(cubes, {"18": "Prices"})
    assert [c["productId"] for c in selected] == [4]
    assert excluded["archived"] == [1]
    assert excluded["no_subject"] == [2, 3]
