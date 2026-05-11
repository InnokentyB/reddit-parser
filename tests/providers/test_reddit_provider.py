from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest


def test_reddit_client_acquires_oauth_token(create_reddit_client, monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        if request.url.path == "/api/v1/access_token":
            assert request.method == "POST"
            return httpx.Response(200, json={"access_token": "token-123", "expires_in": 3600})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)
    client = create_reddit_client(
        client_id="id",
        client_secret="secret",
        user_agent="agent",
        transport=transport,
    )

    token = client.get_access_token()

    assert token == "token-123"
    assert calls == [("POST", "https://www.reddit.com/api/v1/access_token")]


def test_reddit_client_normalizes_search_posts(create_reddit_client):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.reddit.com":
            return httpx.Response(200, json={"access_token": "token-123", "expires_in": 3600})
        if request.url.path == "/r/programming/search.json":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "children": [
                            {
                                "data": {
                                    "id": "abc123",
                                    "subreddit": "programming",
                                    "title": "Cursor review",
                                    "selftext": "Body",
                                    "author": "alice",
                                    "score": 42,
                                    "upvote_ratio": 0.88,
                                    "num_comments": 7,
                                    "is_self": True,
                                    "locked": False,
                                    "archived": False,
                                    "stickied": False,
                                    "link_flair_text": "Discussion",
                                    "created_utc": 1735689600,
                                    "permalink": "/r/programming/comments/abc123/cursor_review/",
                                    "url": "https://reddit.com/r/programming/comments/abc123/cursor_review/",
                                    "thumbnail": "https://example.com/thumb.jpg",
                                }
                            }
                        ]
                    }
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = create_reddit_client(
        client_id="id",
        client_secret="secret",
        user_agent="agent",
        transport=httpx.MockTransport(handler),
    )

    posts = client.search_posts(
        query="cursor",
        subreddit="programming",
        limit=10,
        min_score=0,
        date_from=None,
        date_to=None,
    )

    assert posts == [
        {
            "reddit_post_id": "abc123",
            "post_id": "abc123",
            "platform": "reddit",
            "post_url": "https://www.reddit.com/r/programming/comments/abc123/cursor_review/",
            "subreddit": "programming",
            "title": "Cursor review",
            "body_text": "Body",
            "body_has_link": False,
            "author_name": "alice",
            "author_username": "alice",
            "post_created_utc": 1735689600,
            "fetched_at_utc": posts[0]["fetched_at_utc"],
            "score": 42,
            "upvote_ratio": 0.88,
            "num_comments": 7,
            "is_self_post": True,
            "is_locked": False,
            "is_archived": False,
            "is_removed": False,
            "is_stickied": False,
            "flair_text": "Discussion",
            "matched_query_id": None,
            "contract_version": "1.0",
            "author_account_age_days": None,
            "author_total_karma": None,
            "author_subreddit_karma": None,
            "op_replied_in_thread": False,
            "op_reply_count": 0,
            "tools_mentioned_in_thread_json": None,
            "competitor_mentioned_in_thread": False,
            "previous_seturon_mention_in_thread": False,
            "subreddit_subscribers_count": None,
            "subreddit_active_users_count": None,
            "subreddit_rules_snapshot_url": None,
            "post_thumbnail_url": "https://example.com/thumb.jpg",
            "post_external_link_url": None,
            "post_external_link_domain": None,
            "created_utc": 1735689600,
            "permalink": "/r/programming/comments/abc123/cursor_review/",
            "url": "https://reddit.com/r/programming/comments/abc123/cursor_review/",
        }
    ]
    assert abs(posts[0]["fetched_at_utc"] - int(datetime.now(timezone.utc).timestamp())) < 10


def test_reddit_client_normalizes_top_comments(create_reddit_client):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.reddit.com":
            return httpx.Response(200, json={"access_token": "token-123", "expires_in": 3600})
        if request.url.path == "/comments/abc123.json":
            return httpx.Response(
                200,
                json=[
                    {"data": {"children": []}},
                    {
                        "data": {
                            "children": [
                                {
                                    "kind": "t1",
                                    "data": {
                                        "id": "c2",
                                        "parent_id": "t3_abc123",
                                        "author": "bob",
                                        "body": "Second",
                                        "score": 10,
                                        "created_utc": 200,
                                        "permalink": "/r/programming/comments/abc123/_/c2/",
                                    },
                                },
                                {
                                    "kind": "t1",
                                    "data": {
                                        "id": "c1",
                                        "parent_id": "t3_abc123",
                                        "author": "alice",
                                        "body": "First",
                                        "score": 10,
                                        "created_utc": 100,
                                        "permalink": "/r/programming/comments/abc123/_/c1/",
                                    },
                                },
                                {"kind": "more", "data": {"count": 12}},
                            ]
                        }
                    },
                ],
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = create_reddit_client(
        client_id="id",
        client_secret="secret",
        user_agent="agent",
        transport=httpx.MockTransport(handler),
    )

    comments = client.fetch_post_comments("abc123", comment_limit_per_post=20)

    assert comments == [
        {
            "reddit_comment_id": "c1",
            "reddit_post_id": "abc123",
            "parent_comment_id": None,
            "author_name": "alice",
            "body_text": "First",
            "score": 10,
            "created_utc": 100,
            "permalink": "/r/programming/comments/abc123/_/c1/",
        },
        {
            "reddit_comment_id": "c2",
            "reddit_post_id": "abc123",
            "parent_comment_id": None,
            "author_name": "bob",
            "body_text": "Second",
            "score": 10,
            "created_utc": 200,
            "permalink": "/r/programming/comments/abc123/_/c2/",
        },
    ]


def test_reddit_client_fetches_author_profile(create_reddit_client):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.reddit.com":
            return httpx.Response(200, json={"access_token": "token-123", "expires_in": 3600})
        if request.url.path == "/user/alice/about.json":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "created_utc": 1704067200,
                        "total_karma": 1234,
                    }
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = create_reddit_client(
        client_id="id",
        client_secret="secret",
        user_agent="agent",
        transport=httpx.MockTransport(handler),
    )

    profile = client.fetch_author_profile("alice", "programming")

    assert profile["author_total_karma"] == 1234
    assert profile["author_subreddit_karma"] is None
    assert profile["author_account_age_days"] is not None


def test_reddit_client_fetches_subreddit_snapshot(create_reddit_client):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.reddit.com":
            return httpx.Response(200, json={"access_token": "token-123", "expires_in": 3600})
        if request.url.path == "/r/programming/about.json":
            return httpx.Response(200, json={"data": {"subscribers": 5000000, "active_user_count": 12000}})
        if request.url.path == "/r/programming/about/rules.json":
            return httpx.Response(200, json={"rules": [{"short_name": "No spam"}]})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = create_reddit_client(
        client_id="id",
        client_secret="secret",
        user_agent="agent",
        transport=httpx.MockTransport(handler),
    )

    snapshot = client.fetch_subreddit_snapshot("programming")

    assert snapshot == {
        "subreddit": "programming",
        "subscribers_count": 5000000,
        "active_users_count": 12000,
        "rules_snapshot_url": "https://www.reddit.com/r/programming/about/rules",
        "rules_json": '[{"short_name": "No spam"}]',
    }


def test_reddit_client_retries_on_429(create_reddit_client, monkeypatch):
    attempts = {"count": 0}
    sleeps = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("app.providers.reddit.time.sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.reddit.com":
            return httpx.Response(200, json={"access_token": "token-123", "expires_in": 3600})
        if request.url.path == "/search.json":
            attempts["count"] += 1
            if attempts["count"] == 1:
                return httpx.Response(429, json={"message": "rate limited"})
            return httpx.Response(200, json={"data": {"children": []}})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = create_reddit_client(
        client_id="id",
        client_secret="secret",
        user_agent="agent",
        transport=httpx.MockTransport(handler),
    )

    posts = client.search_posts("cursor", None, 10, 0, None, None)

    assert posts == []
    assert attempts["count"] == 2
    assert sleeps


def test_reddit_client_retries_on_timeout(create_reddit_client, monkeypatch):
    attempts = {"count": 0}
    sleeps = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("app.providers.reddit.time.sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.reddit.com":
            return httpx.Response(200, json={"access_token": "token-123", "expires_in": 3600})
        if request.url.path == "/search.json":
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise httpx.ReadTimeout("boom")
            return httpx.Response(200, json={"data": {"children": []}})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = create_reddit_client(
        client_id="id",
        client_secret="secret",
        user_agent="agent",
        transport=httpx.MockTransport(handler),
    )

    posts = client.search_posts("cursor", None, 10, 0, None, None)

    assert posts == []
    assert attempts["count"] == 2
    assert sleeps


def test_reddit_client_applies_humanized_request_pause(create_reddit_client, monkeypatch):
    sleeps = []
    monotonic_values = iter([10.0, 10.0, 11.0, 11.0])

    monkeypatch.setattr("app.providers.reddit.random.uniform", lambda _a, _b: 0.0)
    monkeypatch.setattr("app.providers.reddit.time.monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr("app.providers.reddit.time.sleep", lambda seconds: sleeps.append(seconds))

    client = create_reddit_client(
        client_id="id",
        client_secret="secret",
        user_agent="agent",
        request_pause_seconds=2.0,
    )

    client._sleep_before_request()
    client._sleep_before_request()

    assert sleeps == [2.0, 1.0]
