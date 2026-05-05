from __future__ import annotations


def test_get_posts_rejects_limit_above_cap(client, workspace_headers):
    response = client.get("/posts?limit=101", headers=workspace_headers)

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert any(detail["field"] == "limit" for detail in body["error"]["details"])


def test_get_posts_rejects_offset_above_cap(client, workspace_headers):
    response = client.get("/posts?offset=1001", headers=workspace_headers)

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert any(detail["field"] == "offset" for detail in body["error"]["details"])


def test_get_post_unknown_or_unauthorized_id_returns_404(client, workspace_headers):
    response = client.get("/posts/t3_missing", headers=workspace_headers)

    assert response.status_code == 404


def test_all_error_responses_use_standard_error_envelope(client, workspace_headers):
    response = client.get("/posts?limit=101", headers=workspace_headers)

    assert response.status_code == 400
    body = response.json()
    assert set(body["error"]) == {"code", "message", "details", "retryable", "request_id"}
    assert isinstance(body["error"]["details"], list)


def test_get_posts_and_post_detail_include_planner_alias_fields(app, client, workspace_headers):
    repository = app.state.repository
    repository.upsert_posts(
        [
            {
                "reddit_post_id": "abc123",
                "subreddit": "instructionaldesign",
                "title": "Need better onboarding content",
                "body_text": "People keep asking how to structure course intros",
                "author_name": "alice",
                "post_created_utc": 1735689600,
                "fetched_at_utc": 1735690000,
                "score": 14,
                "num_comments": 1,
                "is_removed": False,
                "is_locked": False,
                "is_archived": False,
                "matched_query_id": "job-alpha",
                "created_utc": 1735689600,
                "permalink": "/r/instructionaldesign/comments/abc123/onboarding/",
                "url": "https://www.reddit.com/r/instructionaldesign/comments/abc123/onboarding/",
            }
        ]
    )
    repository.upsert_comments(
        [
            {
                "reddit_comment_id": "c1",
                "reddit_post_id": "abc123",
                "parent_comment_id": None,
                "author_name": "bob",
                "body_text": "We struggle with hooks and positioning.",
                "score": 7,
                "created_utc": 1735689700,
                "permalink": "/r/instructionaldesign/comments/abc123/_/c1/",
            }
        ]
    )
    search = repository.create_search_job(
        "test-workspace",
        {
            "query_mode": "simple",
            "query": "onboarding content",
            "subreddit": "instructionaldesign",
            "subreddits": [],
            "match_must_include_any": [],
            "exclude_if_contains": [],
            "exclude_regexes": [],
            "min_score": 0,
            "date_from": None,
            "date_to": None,
            "limit": 25,
            "include_comments": True,
            "enrich": False,
        },
        "hash-alpha",
    )
    repository.link_job_posts(search["job_id"], search["run_id"], ["abc123"])
    repository.complete_run(search["run_id"], posts_found=1, comments_found=1)

    posts_response = client.get("/posts?limit=25&offset=0", headers=workspace_headers)
    assert posts_response.status_code == 200
    post = posts_response.json()["data"][0]
    assert post["body"] == "People keep asking how to structure course intros"
    assert post["created_at"] == 1735689600
    assert post["workspace_id"] == "test-workspace"

    detail_response = client.get("/posts/abc123", headers=workspace_headers)
    assert detail_response.status_code == 200
    body = detail_response.json()
    assert body["body"] == "People keep asking how to structure course intros"
    assert body["workspace_id"] == "test-workspace"
    assert body["comments"][0]["body"] == "We struggle with hooks and positioning."
    assert body["comments"][0]["created_at"] == 1735689700
    assert body["comments"][0]["parent_id"] is None


def test_get_posts_and_post_detail_are_workspace_scoped(app, client):
    repository = app.state.repository
    repository.upsert_posts(
        [
            {
                "reddit_post_id": "abc123",
                "subreddit": "instructionaldesign",
                "title": "Need better onboarding content",
                "body_text": "Body text",
                "author_name": "alice",
                "post_created_utc": 1735689600,
                "fetched_at_utc": 1735690000,
                "score": 14,
                "num_comments": 0,
                "is_removed": False,
                "is_locked": False,
                "is_archived": False,
                "matched_query_id": "job-alpha",
                "created_utc": 1735689600,
                "permalink": "/r/instructionaldesign/comments/abc123/onboarding/",
                "url": "https://www.reddit.com/r/instructionaldesign/comments/abc123/onboarding/",
            }
        ]
    )
    search = repository.create_search_job(
        "workspace-a",
        {
            "query_mode": "simple",
            "query": "onboarding content",
            "subreddit": "instructionaldesign",
            "subreddits": [],
            "match_must_include_any": [],
            "exclude_if_contains": [],
            "exclude_regexes": [],
            "min_score": 0,
            "date_from": None,
            "date_to": None,
            "limit": 25,
            "include_comments": False,
            "enrich": False,
        },
        "hash-alpha",
    )
    repository.link_job_posts(search["job_id"], search["run_id"], ["abc123"])
    repository.complete_run(search["run_id"], posts_found=1, comments_found=0)

    other_headers = {"X-Workspace-Id": "workspace-b"}
    list_response = client.get("/posts?limit=25&offset=0", headers=other_headers)
    assert list_response.status_code == 200
    assert list_response.json()["data"] == []

    detail_response = client.get("/posts/abc123", headers=other_headers)
    assert detail_response.status_code == 404
