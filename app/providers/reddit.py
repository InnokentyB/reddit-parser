from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse
import json
import os
import re
import time
from typing import Any

import httpx

from app.config import CONTRACT_VERSION, POST_PLATFORM


HTTP_LINK_PATTERN = re.compile(r"https?://", re.IGNORECASE)


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
            created_utc = int(data.get("created_utc", 0))
            created_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc).date()
            if int(data.get("score", 0)) < min_score:
                continue
            if date_from and created_dt < date_from:
                continue
            if date_to and created_dt > date_to:
                continue
            posts.append(self._normalize_post(data))
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
            comments.append(self._normalize_comment(reddit_post_id, child.get("data", {})))

        comments.sort(
            key=lambda comment: (
                -int(comment["score"]),
                int(comment["created_utc"]),
                str(comment["reddit_comment_id"]),
            )
        )
        return comments[:comment_limit_per_post]

    def fetch_author_profile(self, author_username: str | None, subreddit: str | None = None) -> dict[str, Any]:
        if not author_username or author_username in {"[deleted]", "AutoModerator"}:
            return {
                "author_account_age_days": None,
                "author_total_karma": None,
                "author_subreddit_karma": None,
            }

        payload = self._request_json("GET", f"/user/{author_username}/about.json")
        data = payload.get("data", {})
        created_utc = data.get("created_utc")
        account_age_days = None
        if created_utc is not None:
            created_dt = datetime.fromtimestamp(float(created_utc), tz=timezone.utc)
            account_age_days = max((datetime.now(timezone.utc) - created_dt).days, 0)

        total_karma = int(data.get("total_karma") or data.get("link_karma", 0) + data.get("comment_karma", 0))
        profile = {
            "author_account_age_days": account_age_days,
            "author_total_karma": total_karma,
            "author_subreddit_karma": None,
        }
        if subreddit:
            profile["author_subreddit_karma"] = self._extract_subreddit_karma(data.get("subreddit"), subreddit)
        return profile

    def fetch_subreddit_snapshot(self, subreddit: str) -> dict[str, Any]:
        about_payload = self._request_json("GET", f"/r/{subreddit}/about.json")
        rules_payload = self._request_json("GET", f"/r/{subreddit}/about/rules.json")
        about = about_payload.get("data", {})
        rules = rules_payload.get("rules", [])
        return {
            "subreddit": subreddit,
            "subscribers_count": int(about.get("subscribers", 0)) if about.get("subscribers") is not None else None,
            "active_users_count": int(about.get("active_user_count", 0))
            if about.get("active_user_count") is not None
            else None,
            "rules_snapshot_url": f"https://www.reddit.com/r/{subreddit}/about/rules",
            "rules_json": json.dumps(rules),
        }

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

    @staticmethod
    def _normalize_post(data: dict[str, Any]) -> dict[str, Any]:
        permalink = data.get("permalink")
        post_url = RedditOAuthClient._to_absolute_url(permalink)
        url = data.get("url")
        external_url = None
        external_domain = None
        if isinstance(url, str) and url and not url.startswith("/r/"):
            if "reddit.com" not in urlparse(url).netloc:
                external_url = url
                external_domain = urlparse(url).netloc or None

        body_text = data.get("selftext", "") or ""
        fetched_at_utc = int(datetime.now(timezone.utc).timestamp())
        removed_by_category = data.get("removed_by_category")
        body_has_link = bool(HTTP_LINK_PATTERN.search(body_text))
        thumbnail = data.get("thumbnail")
        thumbnail_url = thumbnail if isinstance(thumbnail, str) and thumbnail.startswith("http") else None
        return {
            "reddit_post_id": str(data["id"]),
            "post_id": str(data["id"]),
            "platform": POST_PLATFORM,
            "post_url": post_url,
            "subreddit": data.get("subreddit"),
            "title": data.get("title", "") or "",
            "body_text": body_text,
            "body_has_link": body_has_link,
            "author_name": data.get("author"),
            "author_username": data.get("author"),
            "post_created_utc": int(data.get("created_utc", 0)),
            "fetched_at_utc": fetched_at_utc,
            "score": int(data.get("score", 0)),
            "upvote_ratio": RedditOAuthClient._coerce_float(data.get("upvote_ratio")),
            "num_comments": int(data.get("num_comments", 0)),
            "is_self_post": bool(data.get("is_self", True)),
            "is_locked": bool(data.get("locked", False)),
            "is_archived": bool(data.get("archived", False)),
            "is_removed": bool(removed_by_category) or body_text.strip() == "[removed]",
            "is_stickied": bool(data.get("stickied", False)),
            "flair_text": data.get("link_flair_text"),
            "matched_query_id": None,
            "contract_version": CONTRACT_VERSION,
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
            "post_thumbnail_url": thumbnail_url,
            "post_external_link_url": external_url,
            "post_external_link_domain": external_domain,
            "created_utc": int(data.get("created_utc", 0)),
            "permalink": permalink,
            "url": url,
        }

    @staticmethod
    def _normalize_comment(reddit_post_id: str, data: dict[str, Any]) -> dict[str, Any]:
        parent_comment_id = None
        parent_id = data.get("parent_id")
        if isinstance(parent_id, str) and parent_id.startswith("t1_"):
            parent_comment_id = parent_id[3:]
        return {
            "reddit_comment_id": str(data["id"]),
            "reddit_post_id": reddit_post_id,
            "parent_comment_id": parent_comment_id,
            "author_name": data.get("author"),
            "body_text": data.get("body", "") or "",
            "score": int(data.get("score", 0)),
            "created_utc": int(data.get("created_utc", 0)),
            "permalink": data.get("permalink"),
        }

    @staticmethod
    def _to_absolute_url(path_or_url: str | None) -> str | None:
        if not path_or_url:
            return None
        if path_or_url.startswith("http"):
            return path_or_url
        return f"https://www.reddit.com{path_or_url}"

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        if value is None:
            return None
        return float(value)

    @staticmethod
    def _extract_subreddit_karma(subreddit_payload: Any, subreddit: str) -> int | None:
        if not isinstance(subreddit_payload, dict):
            return None
        display_name = subreddit_payload.get("display_name")
        if isinstance(display_name, str) and display_name.lower() == subreddit.lower():
            for key in ("subscribers", "accounts_active", "public_description"):
                _ = subreddit_payload.get(key)
        return None
