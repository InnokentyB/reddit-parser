from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import os
import time
from typing import Any

import httpx


class RedditError(Exception):
    """Base Reddit provider error."""


class RedditTransientError(RedditError):
    """Transient retryable Reddit provider error."""


class RedditConfigurationError(RedditError):
    """Missing or invalid Reddit configuration."""


class RedditAuthError(RedditError):
    """Permanent Reddit authentication error."""


@dataclass
class OAuthToken:
    access_token: str
    expires_at: datetime


class RedditOAuthClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_agent: str,
        *,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_base_seconds: float = 0.25,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not client_id or not client_secret or not user_agent:
            raise RedditConfigurationError(
                "REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, and REDDIT_USER_AGENT are required"
            )
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self._token: OAuthToken | None = None
        self._oauth_client = httpx.Client(
            base_url="https://www.reddit.com",
            timeout=self.timeout,
            headers={"User-Agent": self.user_agent},
            transport=transport,
        )
        self._api_client = httpx.Client(
            base_url="https://oauth.reddit.com",
            timeout=self.timeout,
            headers={"User-Agent": self.user_agent},
            transport=transport,
        )

    @classmethod
    def from_env(cls) -> "RedditOAuthClient":
        return cls(
            client_id=os.getenv("REDDIT_CLIENT_ID", ""),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET", ""),
            user_agent=os.getenv("REDDIT_USER_AGENT", ""),
        )

    def get_access_token(self) -> str:
        now = datetime.now(timezone.utc)
        if self._token is not None and self._token.expires_at > now + timedelta(seconds=30):
            return self._token.access_token

        try:
            response = self._oauth_client.post(
                "/api/v1/access_token",
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
            )
        except httpx.HTTPError as exc:
            raise RedditTransientError(f"OAuth token request failed: {exc}") from exc

        if response.status_code in {401, 403}:
            raise RedditAuthError("Reddit OAuth credentials were rejected")
        if response.status_code >= 500 or response.status_code == 429:
            raise RedditTransientError(f"OAuth token request failed with status {response.status_code}")
        response.raise_for_status()

        payload = response.json()
        expires_in = int(payload.get("expires_in", 3600))
        token = str(payload["access_token"])
        self._token = OAuthToken(
            access_token=token,
            expires_at=now + timedelta(seconds=expires_in),
        )
        return token

    def search_posts(
        self,
        query: str,
        subreddit: str | None,
        limit: int,
        min_score: int,
        date_from: date | None,
        date_to: date | None,
    ) -> list[dict[str, Any]]:
        path = f"/r/{subreddit}/search.json" if subreddit else "/search.json"
        params = {
            "q": query,
            "limit": min(limit, 100),
            "restrict_sr": "true" if subreddit else "false",
            "sort": "new",
            "type": "link",
        }
        payload = self._request_json("GET", path, params=params)
        posts: list[dict[str, Any]] = []
        for child in payload.get("data", {}).get("children", []):
            data = child.get("data", {})
            created_dt = datetime.fromtimestamp(int(data.get("created_utc", 0)), tz=timezone.utc).date()
            if int(data.get("score", 0)) < min_score:
                continue
            if date_from and created_dt < date_from:
                continue
            if date_to and created_dt > date_to:
                continue
            posts.append(
                {
                    "reddit_post_id": str(data["id"]),
                    "subreddit": data.get("subreddit"),
                    "title": data.get("title", ""),
                    "body_text": data.get("selftext", ""),
                    "author_name": data.get("author"),
                    "score": int(data.get("score", 0)),
                    "num_comments": int(data.get("num_comments", 0)),
                    "created_utc": int(data.get("created_utc", 0)),
                    "permalink": data.get("permalink"),
                    "url": data.get("url"),
                }
            )
        return posts[:limit]

    def fetch_post_comments(
        self,
        reddit_post_id: str,
        comment_limit_per_post: int,
    ) -> list[dict[str, Any]]:
        payload = self._request_json(
            "GET",
            f"/comments/{reddit_post_id}.json",
            params={"limit": comment_limit_per_post, "sort": "top"},
        )
        if not isinstance(payload, list) or len(payload) < 2:
            return []

        comments: list[dict[str, Any]] = []
        for child in payload[1].get("data", {}).get("children", []):
            if child.get("kind") != "t1":
                continue
            data = child.get("data", {})
            parent_comment_id = None
            parent_id = data.get("parent_id")
            if isinstance(parent_id, str) and parent_id.startswith("t1_"):
                parent_comment_id = parent_id[3:]
            comments.append(
                {
                    "reddit_comment_id": str(data["id"]),
                    "reddit_post_id": reddit_post_id,
                    "parent_comment_id": parent_comment_id,
                    "author_name": data.get("author"),
                    "body_text": data.get("body", ""),
                    "score": int(data.get("score", 0)),
                    "created_utc": int(data.get("created_utc", 0)),
                    "permalink": data.get("permalink"),
                }
            )

        comments.sort(
            key=lambda comment: (
                -int(comment["score"]),
                int(comment["created_utc"]),
                str(comment["reddit_comment_id"]),
            )
        )
        return comments[:comment_limit_per_post]

    def close(self) -> None:
        self._oauth_client.close()
        self._api_client.close()

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        token = self.get_access_token()
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._api_client.request(
                    method,
                    path,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self.max_retries:
                    raise RedditTransientError(f"Reddit request failed after retries: {exc}") from exc
                self._sleep(attempt)
                continue

            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt >= self.max_retries:
                    raise RedditTransientError(
                        f"Reddit request failed after retries with status {response.status_code}"
                    )
                self._sleep(attempt)
                continue
            if response.status_code in {401, 403}:
                raise RedditAuthError(f"Reddit request rejected with status {response.status_code}")
            response.raise_for_status()
            return response.json()

        raise RedditTransientError("Reddit request failed unexpectedly")

    def _sleep(self, attempt: int) -> None:
        time.sleep(self.backoff_base_seconds * attempt)
