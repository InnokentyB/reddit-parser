from __future__ import annotations


def test_normalize_query_trims_lowercases_and_collapses_whitespace(normalize_query):
    normalized = normalize_query("   AI    Product   Manager   ")

    assert normalized == "ai product manager"


def test_normalize_query_removes_duplicate_tokens_without_reordering(normalize_query):
    normalized = normalize_query("AI ai manager ai product manager")

    assert normalized == "ai manager product"


def test_normalize_subreddit_accepts_plain_name_and_r_prefix(normalize_subreddit):
    assert normalize_subreddit("Programming") == "programming"
    assert normalize_subreddit("r/Programming") == "programming"


def test_normalize_subreddit_rejects_invalid_values(normalize_subreddit):
    try:
        normalize_subreddit("r/Invalid-Name")
    except ValueError as exc:
        assert "subreddit" in str(exc).lower()
    else:
        raise AssertionError("Expected invalid subreddit input to raise ValueError")


def test_build_query_hash_changes_when_filtering_changes(build_query_hash, valid_search_payload):
    first = build_query_hash(valid_search_payload)

    changed = dict(valid_search_payload)
    changed["limit"] = 25

    second = build_query_hash(changed)

    assert first != second


def test_build_query_hash_stays_stable_for_equivalent_normalized_inputs(
    build_query_hash, valid_search_payload
):
    first = build_query_hash(valid_search_payload)

    equivalent = dict(valid_search_payload)
    equivalent["query"] = "  ai   product manager  "
    equivalent["subreddit"] = "r/ProductManagement"

    second = build_query_hash(equivalent)

    assert first == second
