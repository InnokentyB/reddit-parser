from __future__ import annotations

from app.worker import process_next
from tests.integration.test_worker_ingestion import FakeRedditClient


def _queue_search_job(client, workspace_headers, valid_search_payload):
    response = client.post("/search", json=valid_search_payload, headers=workspace_headers)
    assert response.status_code == 202
    return response.json()


def test_get_insights_returns_planner_friendly_insight_items(
    app, client, workspace_headers, valid_search_payload
):
    job = _queue_search_job(client, workspace_headers, valid_search_payload)
    fake = FakeRedditClient(
        posts=[
            {
                "reddit_post_id": "abc123",
                "subreddit": "instructionaldesign",
                "title": "Why is onboarding copy so hard?",
                "body_text": "I'm frustrated. What tool should we use instead of Rise?",
                "author_name": "alice",
                "post_created_utc": 1735689600,
                "fetched_at_utc": 1735690000,
                "score": 16,
                "upvote_ratio": 0.94,
                "num_comments": 2,
                "is_self_post": True,
                "is_locked": False,
                "is_archived": False,
                "is_removed": False,
                "is_stickied": False,
                "flair_text": "Question",
                "created_utc": 1735689600,
                "permalink": "/r/instructionaldesign/comments/abc123/onboarding/",
                "url": "https://www.reddit.com/r/instructionaldesign/comments/abc123/onboarding/",
            }
        ],
        comments_by_post={
            "abc123": [
                {
                    "reddit_comment_id": "c1",
                    "reddit_post_id": "abc123",
                    "parent_comment_id": None,
                    "author_name": "bob",
                    "body_text": "We keep hearing the same objection: Rise is too limiting.",
                    "score": 11,
                    "created_utc": 1735689700,
                    "permalink": "/r/instructionaldesign/comments/abc123/_/c1/",
                },
                {
                    "reddit_comment_id": "c2",
                    "reddit_post_id": "abc123",
                    "parent_comment_id": None,
                    "author_name": "carol",
                    "body_text": "People ask for examples and templates every week.",
                    "score": 8,
                    "created_utc": 1735689800,
                    "permalink": "/r/instructionaldesign/comments/abc123/_/c2/",
                },
            ]
        },
    )

    assert process_next(app.state.repository, fake) is True

    response = client.get("/insights?limit=20&offset=0", headers=workspace_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["pagination"]["returned"] >= 1
    assert body["groups"]["pain_points"]
    assert body["groups"]["questions_people_ask"]
    assert body["groups"]["competitor_mentions"]
    first = body["data"][0]
    assert {
        "insight_id",
        "type",
        "title",
        "summary",
        "evidence_count",
        "sample_quotes",
        "source_post_ids",
        "source_comment_ids",
        "subreddits",
        "first_seen_at",
        "last_seen_at",
        "confidence",
        "priority",
    }.issubset(first.keys())


def test_get_summary_for_job_returns_planning_groups(app, client, workspace_headers, valid_search_payload):
    job = _queue_search_job(client, workspace_headers, valid_search_payload)
    fake = FakeRedditClient(
        posts=[
            {
                "reddit_post_id": "abc123",
                "subreddit": "instructionaldesign",
                "title": "People keep asking for onboarding templates",
                "body_text": "We struggle to turn research into weekly topics.",
                "author_name": "alice",
                "post_created_utc": 1735689600,
                "fetched_at_utc": 1735690000,
                "score": 16,
                "upvote_ratio": 0.94,
                "num_comments": 1,
                "is_self_post": True,
                "is_locked": False,
                "is_archived": False,
                "is_removed": False,
                "is_stickied": False,
                "flair_text": "Question",
                "created_utc": 1735689600,
                "permalink": "/r/instructionaldesign/comments/abc123/onboarding/",
                "url": "https://www.reddit.com/r/instructionaldesign/comments/abc123/onboarding/",
            }
        ],
        comments_by_post={
            "abc123": [
                {
                    "reddit_comment_id": "c1",
                    "reddit_post_id": "abc123",
                    "parent_comment_id": None,
                    "author_name": "bob",
                    "body_text": "A weekly content brief from Reddit would help a lot.",
                    "score": 9,
                    "created_utc": 1735689700,
                    "permalink": "/r/instructionaldesign/comments/abc123/_/c1/",
                }
            ]
        },
    )

    assert process_next(app.state.repository, fake) is True

    response = client.get(f"/summaries/{job['job_id']}", headers=workspace_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job["job_id"]
    assert body["workspace_id"] == "test-workspace"
    assert body["latest_run"]["status"] == "completed"
    assert set(body["groups"]) == {
        "topic_candidates",
        "pain_points",
        "questions_people_ask",
        "objections",
        "competitor_mentions",
        "language_patterns",
        "content_opportunities",
    }
    assert isinstance(body["groups"]["content_opportunities"], list)
