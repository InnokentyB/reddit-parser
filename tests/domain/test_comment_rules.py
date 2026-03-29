from __future__ import annotations


def test_select_api_comments_returns_top_three_by_score_with_stable_tie_break(select_api_comments):
    comments = [
        {"reddit_comment_id": "c3", "score": 9, "created_utc": 300},
        {"reddit_comment_id": "c2", "score": 10, "created_utc": 200},
        {"reddit_comment_id": "c1", "score": 10, "created_utc": 100},
        {"reddit_comment_id": "c4", "score": 10, "created_utc": 100},
        {"reddit_comment_id": "c5", "score": 2, "created_utc": 500},
    ]

    selected = select_api_comments(comments)

    assert [comment["reddit_comment_id"] for comment in selected] == ["c1", "c4", "c2"]


def test_select_api_comments_returns_all_comments_when_fewer_than_three(select_api_comments):
    comments = [
        {"reddit_comment_id": "c2", "score": 10, "created_utc": 200},
        {"reddit_comment_id": "c1", "score": 10, "created_utc": 100},
    ]

    selected = select_api_comments(comments)

    assert [comment["reddit_comment_id"] for comment in selected] == ["c1", "c2"]
