from __future__ import annotations

from datetime import timedelta

from app.models import JobRunModel, SearchTemplateModel
from tests.support import load_symbol
from app.worker import process_next


class FakeRedditClient:
    def __init__(
        self,
        posts=None,
        comments_by_post=None,
        comment_failures=None,
        search_error=None,
        author_profiles=None,
        subreddit_snapshots=None,
        posts_by_subreddit=None,
    ):
        self.posts = posts or []
        self.posts_by_subreddit = posts_by_subreddit or {}
        self.comments_by_post = comments_by_post or {}
        self.comment_failures = comment_failures or set()
        self.search_error = search_error
        self.author_profiles = author_profiles or {}
        self.subreddit_snapshots = subreddit_snapshots or {}

    def search_posts(self, query, subreddit, limit, min_score, date_from, date_to):
        if self.search_error is not None:
            raise self.search_error
        if subreddit in self.posts_by_subreddit:
            return self.posts_by_subreddit[subreddit][:limit]
        return self.posts[:limit]

    def fetch_post_comments(self, reddit_post_id, comment_limit_per_post):
        if reddit_post_id in self.comment_failures:
            raise RuntimeError("comments failed")
        return self.comments_by_post.get(reddit_post_id, [])[:comment_limit_per_post]

    def fetch_author_profile(self, author_username, subreddit=None):
        return self.author_profiles.get(
            author_username,
            {
                "author_account_age_days": None,
                "author_total_karma": None,
                "author_subreddit_karma": None,
            },
        )

    def fetch_subreddit_snapshot(self, subreddit):
        return self.subreddit_snapshots.get(
            subreddit,
            {
                "subreddit": subreddit,
                "subscribers_count": 32000,
                "active_users_count": 87,
                "rules_snapshot_url": f"https://www.reddit.com/r/{subreddit}/about/rules",
                "rules_json": "[]",
            },
        )


def _queue_search_job(client, workspace_headers, valid_search_payload):
    response = client.post("/search", json=valid_search_payload, headers=workspace_headers)
    assert response.status_code == 202
    return response.json()


def _queue_structured_search_job(client, workspace_headers, structured_search_payload):
    response = client.post("/search", json=structured_search_payload, headers=workspace_headers)
    assert response.status_code == 202
    return response.json()


def test_worker_ingests_posts_and_comments(app, client, workspace_headers, valid_search_payload):
    job = _queue_search_job(client, workspace_headers, valid_search_payload)
    fake = FakeRedditClient(
        posts=[
            {
                "reddit_post_id": "abc123",
                "platform": "reddit",
                "post_url": "https://www.reddit.com/r/instructionaldesign/comments/abc123/ai_pm_thread/",
                "subreddit": "instructionaldesign",
                "title": "AI PM thread",
                "body_text": "Need better tools like Articulate Storyline",
                "body_has_link": False,
                "author_name": "alice",
                "post_created_utc": 1735689600,
                "fetched_at_utc": 1735690000,
                "score": 12,
                "upvote_ratio": 0.91,
                "num_comments": 2,
                "is_self_post": True,
                "is_locked": False,
                "is_archived": False,
                "is_removed": False,
                "is_stickied": False,
                "flair_text": "Discussion",
                "created_utc": 1735689600,
                "permalink": "/r/instructionaldesign/comments/abc123/ai_pm_thread/",
                "url": "https://www.reddit.com/r/instructionaldesign/comments/abc123/ai_pm_thread/",
            }
        ],
        comments_by_post={
            "abc123": [
                {
                    "reddit_comment_id": "c1",
                    "reddit_post_id": "abc123",
                    "parent_comment_id": None,
                    "author_name": "bob",
                    "body_text": "Useful comment mentioning Seturon and Rise",
                    "score": 9,
                    "created_utc": 1735689700,
                    "permalink": "/r/instructionaldesign/comments/abc123/_/c1/",
                }
            ]
        },
        author_profiles={
            "alice": {
                "author_account_age_days": 365,
                "author_total_karma": 4200,
                "author_subreddit_karma": None,
            }
        },
    )

    processed = process_next(app.state.repository, fake)

    assert processed is True

    search_view = client.get(f"/search/{job['job_id']}", headers=workspace_headers).json()
    assert search_view["status"] == "idle"
    assert search_view["latest_run"]["status"] == "completed"
    assert search_view["results"]["total_posts"] == 1
    assert search_view["results"]["items"][0]["reddit_post_id"] == "abc123"
    assert search_view["results"]["items"][0]["contract_version"] == "1.0"
    assert search_view["results"]["items"][0]["matched_query_id"] == job["job_id"]
    assert search_view["results"]["items"][0]["tools_mentioned_in_thread"] == ["Articulate Storyline", "Rise"]
    assert search_view["results"]["items"][0]["previous_seturon_mention_in_thread"] is True

    posts = client.get("/posts?limit=25&offset=0", headers=workspace_headers).json()
    assert posts["data"][0]["reddit_post_id"] == "abc123"
    assert posts["data"][0]["post_id"] == "abc123"
    assert posts["data"][0]["author_total_karma"] == 4200

    post_detail = client.get("/posts/abc123", headers=workspace_headers).json()
    assert post_detail["comments"][0]["reddit_comment_id"] == "c1"
    assert post_detail["top_3_comments"][0]["comment_id"] == "c1"
    assert post_detail["subreddit_rules_snapshot_url"].endswith("/r/instructionaldesign/about/rules")


def test_duplicate_worker_delivery_does_not_duplicate_entities(
    app, client, workspace_headers, valid_search_payload
):
    job = _queue_search_job(client, workspace_headers, valid_search_payload)
    fake = FakeRedditClient(
        posts=[
            {
                "reddit_post_id": "abc123",
                "subreddit": "instructionaldesign",
                "title": "AI PM thread",
                "body_text": "Need better tools",
                "author_name": "alice",
                "post_created_utc": 1735689600,
                "fetched_at_utc": 1735690000,
                "score": 12,
                "upvote_ratio": 0.91,
                "num_comments": 1,
                "is_self_post": True,
                "is_locked": False,
                "is_archived": False,
                "is_removed": False,
                "is_stickied": False,
                "flair_text": "Discussion",
                "created_utc": 1735689600,
                "permalink": "/r/instructionaldesign/comments/abc123/ai_pm_thread/",
                "url": "https://www.reddit.com/r/instructionaldesign/comments/abc123/ai_pm_thread/",
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
                    "permalink": "/r/instructionaldesign/comments/abc123/_/c1/",
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
                "subreddit": "instructionaldesign",
                "title": "AI PM thread",
                "body_text": "Need better tools",
                "author_name": "alice",
                "post_created_utc": 1735689600,
                "fetched_at_utc": 1735690000,
                "score": 12,
                "upvote_ratio": 0.91,
                "num_comments": 1,
                "is_self_post": True,
                "is_locked": False,
                "is_archived": False,
                "is_removed": False,
                "is_stickied": False,
                "flair_text": "Discussion",
                "created_utc": 1735689600,
                "permalink": "/r/instructionaldesign/comments/abc123/ai_pm_thread/",
                "url": "https://www.reddit.com/r/instructionaldesign/comments/abc123/ai_pm_thread/",
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
                "subreddit": "instructionaldesign",
                "title": "AI PM thread",
                "body_text": "Need better tools",
                "author_name": "alice",
                "post_created_utc": 1735689600,
                "fetched_at_utc": 1735690000,
                "score": 12,
                "upvote_ratio": 0.91,
                "num_comments": 1,
                "is_self_post": True,
                "is_locked": False,
                "is_archived": False,
                "is_removed": False,
                "is_stickied": False,
                "flair_text": "Discussion",
                "created_utc": 1735689600,
                "permalink": "/r/instructionaldesign/comments/abc123/ai_pm_thread/",
                "url": "https://www.reddit.com/r/instructionaldesign/comments/abc123/ai_pm_thread/",
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
                "subreddit": "instructionaldesign",
                "title": "AI PM thread updated",
                "body_text": "Better tools now",
                "author_name": "alice",
                "post_created_utc": 1735689600,
                "fetched_at_utc": 1735690100,
                "score": 25,
                "upvote_ratio": 0.95,
                "num_comments": 2,
                "is_self_post": True,
                "is_locked": False,
                "is_archived": False,
                "is_removed": False,
                "is_stickied": False,
                "flair_text": "Discussion",
                "created_utc": 1735689600,
                "permalink": "/r/instructionaldesign/comments/abc123/ai_pm_thread/",
                "url": "https://www.reddit.com/r/instructionaldesign/comments/abc123/ai_pm_thread/",
            }
        ]
    )
    assert process_next(app.state.repository, fake_second, query_cooldown_seconds=0) is True

    posts = client.get("/posts?limit=25&offset=0", headers=workspace_headers).json()
    assert len(posts["data"]) == 1
    assert posts["data"][0]["title"] == "AI PM thread updated"
    assert posts["data"][0]["score"] == 25


def test_worker_skips_removed_locked_archived_and_stickied_posts(
    app, client, workspace_headers, valid_search_payload
):
    job = _queue_search_job(client, workspace_headers, valid_search_payload)
    fake = FakeRedditClient(
        posts=[
            {
                "reddit_post_id": "dead1",
                "subreddit": "instructionaldesign",
                "title": "Locked",
                "body_text": "skip",
                "author_name": "alice",
                "post_created_utc": 1735689600,
                "fetched_at_utc": 1735690000,
                "score": 12,
                "upvote_ratio": 0.91,
                "num_comments": 0,
                "is_self_post": True,
                "is_locked": True,
                "is_archived": False,
                "is_removed": False,
                "is_stickied": False,
                "flair_text": "Discussion",
                "created_utc": 1735689600,
                "permalink": "/r/instructionaldesign/comments/dead1/locked/",
                "url": "https://www.reddit.com/r/instructionaldesign/comments/dead1/locked/",
            },
            {
                "reddit_post_id": "live1",
                "subreddit": "instructionaldesign",
                "title": "Live",
                "body_text": "keep",
                "author_name": "alice",
                "post_created_utc": 1735689601,
                "fetched_at_utc": 1735690001,
                "score": 15,
                "upvote_ratio": 0.93,
                "num_comments": 0,
                "is_self_post": True,
                "is_locked": False,
                "is_archived": False,
                "is_removed": False,
                "is_stickied": False,
                "flair_text": "Question",
                "created_utc": 1735689601,
                "permalink": "/r/instructionaldesign/comments/live1/live/",
                "url": "https://www.reddit.com/r/instructionaldesign/comments/live1/live/",
            },
        ]
    )

    assert process_next(app.state.repository, fake) is True

    search_view = client.get(f"/search/{job['job_id']}", headers=workspace_headers).json()
    assert search_view["results"]["total_posts"] == 1
    assert search_view["results"]["items"][0]["reddit_post_id"] == "live1"


def test_worker_accepts_structured_query_definition_and_filters_per_query(
    app, client, workspace_headers, structured_search_payload
):
    job = _queue_structured_search_job(client, workspace_headers, structured_search_payload)
    fake = FakeRedditClient(
        posts_by_subreddit={
            "instructionaldesign": [
                {
                    "reddit_post_id": "keep1",
                    "subreddit": "instructionaldesign",
                    "title": "Adaptive branching tool help",
                    "body_text": "Need an adaptive path tool recommendation",
                    "author_name": "alice",
                    "post_created_utc": 1735689600,
                    "fetched_at_utc": 1735690000,
                    "score": 12,
                    "upvote_ratio": 0.91,
                    "num_comments": 1,
                    "is_self_post": True,
                    "is_locked": False,
                    "is_archived": False,
                    "is_removed": False,
                    "is_stickied": False,
                    "flair_text": "Discussion",
                    "created_utc": 1735689600,
                    "permalink": "/r/instructionaldesign/comments/keep1/adaptive/",
                    "url": "https://www.reddit.com/r/instructionaldesign/comments/keep1/adaptive/",
                }
            ],
            "edtech": [
                {
                    "reddit_post_id": "drop1",
                    "subreddit": "edtech",
                    "title": "Adaptive job posting",
                    "body_text": "Looking for work as a freelancer in adaptive learning",
                    "author_name": "bob",
                    "post_created_utc": 1735689601,
                    "fetched_at_utc": 1735690001,
                    "score": 18,
                    "upvote_ratio": 0.95,
                    "num_comments": 0,
                    "is_self_post": True,
                    "is_locked": False,
                    "is_archived": False,
                    "is_removed": False,
                    "is_stickied": False,
                    "flair_text": "Question",
                    "created_utc": 1735689601,
                    "permalink": "/r/edtech/comments/drop1/job/",
                    "url": "https://www.reddit.com/r/edtech/comments/drop1/job/",
                }
            ],
        }
    )

    assert process_next(app.state.repository, fake) is True

    search_view = client.get(f"/search/{job['job_id']}", headers=workspace_headers).json()
    assert search_view["latest_run"]["status"] == "completed"
    assert search_view["results"]["total_posts"] == 1
    assert search_view["results"]["items"][0]["reddit_post_id"] == "keep1"
    assert search_view["results"]["items"][0]["matched_query_id"] == "q-tooling-001"
    assert search_view["query"]["subreddits"] == ["instructionaldesign", "edtech"]


def test_due_templates_enqueue_daily_refresh_runs(app, client, workspace_headers, query_bank_yaml):
    imported = client.post(
        "/search-templates/import",
        json={
            "yaml_content": query_bank_yaml,
            "schedule_daily": True,
            "limit": 50,
            "min_score": 5,
            "include_comments": True,
            "enrich": True,
            "idempotency_key": "77777777-7777-7777-7777-777777777777",
        },
        headers=workspace_headers,
    ).json()
    template_id = imported["templates"][0]["template_id"]

    with app.state.repository.session_factory() as session:
        template = session.get(SearchTemplateModel, template_id)
        initial_run = session.get(JobRunModel, imported["templates"][0]["run_id"])
        initial_run.status = "completed"
        template.next_run_at = template.next_run_at - timedelta(days=1)
        session.commit()

    created_runs = app.state.repository.enqueue_due_template_runs()

    assert len(created_runs) == 1
    assert created_runs[0]["template_id"] == template_id
