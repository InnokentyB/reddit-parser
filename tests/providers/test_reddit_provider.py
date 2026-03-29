from __future__ import annotations

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
                                    "num_comments": 7,
                                    "created_utc": 1735689600,
                                    "permalink": "/r/programming/comments/abc123/cursor_review/",
                                    "url": "https://reddit.com/r/programming/comments/abc123/cursor_review/",
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
            "subreddit": "programming",
            "title": "Cursor review",
            "body_text": "Body",
            "author_name": "alice",
            "score": 42,
            "num_comments": 7,
            "created_utc": 1735689600,
            "permalink": "/r/programming/comments/abc123/cursor_review/",
            "url": "https://reddit.com/r/programming/comments/abc123/cursor_review/",
        }
    ]


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
