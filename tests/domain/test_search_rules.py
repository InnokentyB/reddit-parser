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
    equivalent["query"] = "  ai   course authoring tools  "
    equivalent["subreddit"] = "r/InstructionalDesign"

    second = build_query_hash(equivalent)

    assert first == second


def test_build_query_hash_stays_stable_for_equivalent_query_definition_inputs(build_query_hash):
    first = build_query_hash(
        {
            "query_mode": "query_definition",
            "query_definition_id": "q-tooling-001",
            "query_cluster": "tooling_ask",
            "query_priority": 1,
            "query": '  title:"adaptive learning"   OR selftext:"adaptive learning" ',
            "subreddits": ["InstructionalDesign", "r/EdTech"],
            "match_must_include_any": ["Adaptive", "Branching"],
            "exclude_if_contains": ["Hiring"],
            "min_score": 5,
            "limit": 50,
            "include_comments": True,
            "enrich": True,
        }
    )

    second = build_query_hash(
        {
            "query_mode": "query_definition",
            "query_definition_id": "q-tooling-001",
            "query_cluster": "tooling_ask",
            "query_priority": 1,
            "query": 'title:"adaptive learning" OR selftext:"adaptive learning"',
            "subreddits": ["r/instructionaldesign", "edtech"],
            "match_must_include_any": ["adaptive", "branching"],
            "exclude_if_contains": ["hiring"],
            "min_score": 5,
            "limit": 50,
            "include_comments": True,
            "enrich": True,
        }
    )

    assert first == second
