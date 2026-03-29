from __future__ import annotations

from typing import Any


def select_api_comments(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sorted_comments = sorted(
        comments,
        key=lambda comment: (
            -int(comment["score"]),
            int(comment["created_utc"]),
            str(comment["reddit_comment_id"]),
        ),
    )
    return sorted_comments[:3]
