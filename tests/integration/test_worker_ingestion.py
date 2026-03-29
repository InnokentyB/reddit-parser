from __future__ import annotations

from tests.support import load_symbol
from app.worker import process_next


class FakeRedditClient:
    def __init__(self, posts=None, comments_by_post=None, comment_failures=None, search_error=None):
        self.posts = posts or []
        self.comments_by_post = comments_by_post or {}
        self.comment_failures = comment_failures or set()
        self.search_error = search_error

    def search_posts(self, query, subreddit, limit, min_score, date_from, date_to):
        if self.search_error is not None:
            raise self.search_error
        return self.posts[:limit]

    def fetch_post_comments(self, reddit_post_id, comment_limit_per_post):
        if reddit_post_id in self.comment_failures:
            raise RuntimeError("comments failed")
        return self.comments_by_post.get(reddit_post_id, [])[:comment_limit_per_post]


def _queue_search_job(client, workspace_headers, valid_search_payload):
    response = client.post("/search", json=valid_search_payload, headers=workspace_headers)
    assert response.status_code == 202
    return response.json()


def test_worker_ingests_posts_and_comments(app, client, workspace_headers, valid_search_payload):
    job = _queue_search_job(client, workspace_headers, valid_search_payload)
    fake = FakeRedditClient(
        posts=[
            {
                "reddit_post_id": "abc123",
                "subreddit": "productmanagement",
                "title": "AI PM thread",
                "body_text": "Need better tools",
                "author_name": "alice",
                "score": 12,
                "num_comments": 2,
                "created_utc": 1735689600,
                "permalink": "/r/productmanagement/comments/abc123/ai_pm_thread/",
                "url": "https://reddit.com/r/productmanagement/comments/abc123/ai_pm_thread/",
            }
        ],
        comments_by_post={
            "abc123": [
                {
                    "reddit_comment_id": "c1",
                    "reddit_post_id": "abc123",
                    "parent_comment_id": None,
                    "author_name": "bob",
                    "body_text": "Useful comment",
                    "score": 9,
                    "created_utc": 1735689700,
                    "permalink": "/r/productmanagement/comments/abc123/_/c1/",
                }
            ]
        },
    )

    processed = process_next(app.state.repository, fake)

    assert processed is True

    search_view = client.get(f"/search/{job['job_id']}", headers=workspace_headers).json()
    assert search_view["status"] == "idle"
    assert search_view["latest_run"]["status"] == "completed"
    assert search_view["results"]["total_posts"] == 1
    assert search_view["results"]["items"][0]["reddit_post_id"] == "abc123"

    posts = client.get("/posts?limit=25&offset=0", headers=workspace_headers).json()
    assert posts["data"][0]["reddit_post_id"] == "abc123"

    post_detail = client.get("/posts/abc123", headers=workspace_headers).json()
    assert post_detail["comments"][0]["reddit_comment_id"] == "c1"


def test_duplicate_worker_delivery_does_not_duplicate_entities(
    app, client, workspace_headers, valid_search_payload
):
    job = _queue_search_job(client, workspace_headers, valid_search_payload)
    fake = FakeRedditClient(
        posts=[
            {
                "reddit_post_id": "abc123",
                "subreddit": "productmanagement",
                "title": "AI PM thread",
                "body_text": "Need better tools",
                "author_name": "alice",
                "score": 12,
                "num_comments": 1,
                "created_utc": 1735689600,
                "permalink": "/r/productmanagement/comments/abc123/ai_pm_thread/",
                "url": "https://reddit.com/r/productmanagement/comments/abc123/ai_pm_thread/",
            }
        ],
        comments_by_post={
            "abc123": [
                {
                    "reddit_comment_id": "c1",
                    "reddit_post_id": "abc123",
                    "parent_comment_id": None,
                    "author_name": "bob",
                    "body_text": "Useful comment",
                    "score": 9,
                    "created_utc": 1735689700,
                    "permalink": "/r/productmanagement/comments/abc123/_/c1/",
                }
            ]
        },
    )

    assert process_next(app.state.repository, fake) is True
    assert process_next(app.state.repository, fake) is False

    search_view = client.get(f"/search/{job['job_id']}", headers=workspace_headers).json()
    assert search_view["results"]["total_posts"] == 1
    assert len(search_view["results"]["items"]) == 1


def test_partial_comment_failure_marks_run_partial(
    app, client, workspace_headers, valid_search_payload
):
    job = _queue_search_job(client, workspace_headers, valid_search_payload)
    fake = FakeRedditClient(
        posts=[
            {
                "reddit_post_id": "abc123",
                "subreddit": "productmanagement",
                "title": "AI PM thread",
                "body_text": "Need better tools",
                "author_name": "alice",
                "score": 12,
                "num_comments": 1,
                "created_utc": 1735689600,
                "permalink": "/r/productmanagement/comments/abc123/ai_pm_thread/",
                "url": "https://reddit.com/r/productmanagement/comments/abc123/ai_pm_thread/",
            }
        ],
        comment_failures={"abc123"},
    )

    assert process_next(app.state.repository, fake) is True

    search_view = client.get(f"/search/{job['job_id']}", headers=workspace_headers).json()
    assert search_view["status"] == "partial"
    assert search_view["latest_run"]["status"] == "partial"
    assert search_view["results"]["total_posts"] == 1


def test_transient_search_failure_marks_retryable_failed(
    app, client, workspace_headers, valid_search_payload
):
    transient_error = load_symbol("app.providers.reddit", "RedditTransientError")("boom")
    job = _queue_search_job(client, workspace_headers, valid_search_payload)
    fake = FakeRedditClient(search_error=transient_error)

    assert process_next(app.state.repository, fake) is True

    search_view = client.get(f"/search/{job['job_id']}", headers=workspace_headers).json()
    assert search_view["status"] == "error"
    assert search_view["latest_run"]["status"] == "retryable_failed"


def test_refresh_updates_existing_post_without_duplicates(
    app, client, workspace_headers, valid_search_payload
):
    created = _queue_search_job(client, workspace_headers, valid_search_payload)
    fake_first = FakeRedditClient(
        posts=[
            {
                "reddit_post_id": "abc123",
                "subreddit": "productmanagement",
                "title": "AI PM thread",
                "body_text": "Need better tools",
                "author_name": "alice",
                "score": 12,
                "num_comments": 1,
                "created_utc": 1735689600,
                "permalink": "/r/productmanagement/comments/abc123/ai_pm_thread/",
                "url": "https://reddit.com/r/productmanagement/comments/abc123/ai_pm_thread/",
            }
        ]
    )
    assert process_next(app.state.repository, fake_first) is True

    refresh = client.post(
        f"/refresh/{created['job_id']}",
        json={"idempotency_key": "99999999-9999-9999-9999-999999999999"},
        headers=workspace_headers,
    )
    assert refresh.status_code == 202

    fake_second = FakeRedditClient(
        posts=[
            {
                "reddit_post_id": "abc123",
                "subreddit": "productmanagement",
                "title": "AI PM thread updated",
                "body_text": "Better tools now",
                "author_name": "alice",
                "score": 25,
                "num_comments": 2,
                "created_utc": 1735689600,
                "permalink": "/r/productmanagement/comments/abc123/ai_pm_thread/",
                "url": "https://reddit.com/r/productmanagement/comments/abc123/ai_pm_thread/",
            }
        ]
    )
    assert process_next(app.state.repository, fake_second) is True

    posts = client.get("/posts?limit=25&offset=0", headers=workspace_headers).json()
    assert len(posts["data"]) == 1
    assert posts["data"][0]["title"] == "AI PM thread updated"
    assert posts["data"][0]["score"] == 25
