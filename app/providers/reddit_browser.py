from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import quote_plus, urlparse
import json
import os
import re

import httpx

from app.config import CONTRACT_VERSION, POST_PLATFORM
from app.providers.reddit import RedditConfigurationError, RedditTransientError


HTTP_LINK_PATTERN = re.compile(r"https?://", re.IGNORECASE)
POINTS_PATTERN = re.compile(r"(\d+)")
ISO_DATETIME_FALLBACK = "1970-01-01T00:00:00+00:00"


class RedditBrowserClient:
    def __init__(
        self,
        *,
        headless: bool = True,
        timeout_ms: int = 20000,
        user_agent: str | None = None,
        browser_engine: Any | None = None,
    ) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.user_agent = user_agent or os.getenv(
            "REDDIT_BROWSER_USER_AGENT",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari",
        )
        self._browser_engine = browser_engine
        self._playwright = None
        self._browser = None
        self._http = httpx.Client(
            timeout=max(float(timeout_ms) / 1000.0, 1.0),
            headers={"User-Agent": self.user_agent},
            follow_redirects=True,
        )

    @classmethod
    def from_env(cls) -> "RedditBrowserClient":
        return cls(
            headless=os.getenv("REDDIT_BROWSER_HEADLESS", "true").strip().lower() != "false",
            timeout_ms=int(os.getenv("REDDIT_BROWSER_TIMEOUT_MS", "20000")),
        )

    def search_posts(
        self,
        query: str,
        subreddit: str | None,
        limit: int,
        min_score: int,
        date_from: date | None,
        date_to: date | None,
    ) -> list[dict[str, Any]]:
        page = self._new_page()
        try:
            page.goto(self._search_url(query, subreddit), wait_until="domcontentloaded", timeout=self.timeout_ms)
            self._ensure_not_blocked(page)
            items = page.locator("div.thing.link")
            count = min(items.count(), limit * 3)
            posts: list[dict[str, Any]] = []
            for index in range(count):
                post = self._extract_search_post(items.nth(index))
                if post is None:
                    continue
                created_dt = datetime.fromtimestamp(post["created_utc"], tz=timezone.utc).date()
                if post["score"] < min_score:
                    continue
                if date_from and created_dt < date_from:
                    continue
                if date_to and created_dt > date_to:
                    continue
                posts.append(post)
                if len(posts) >= limit:
                    break
            return posts[:limit]
        except Exception as exc:
            raise RedditTransientError(f"Browser Reddit search failed: {exc}") from exc
        finally:
            page.close()

    def fetch_post_comments(
        self,
        reddit_post_id: str,
        comment_limit_per_post: int,
    ) -> list[dict[str, Any]]:
        page = self._new_page()
        try:
            page.goto(
                f"https://old.reddit.com/comments/{reddit_post_id}/",
                wait_until="domcontentloaded",
                timeout=self.timeout_ms,
            )
            self._ensure_not_blocked(page)
            comments_locator = page.locator("div.thing.comment")
            count = min(comments_locator.count(), comment_limit_per_post * 3)
            comments: list[dict[str, Any]] = []
            for index in range(count):
                payload = self._extract_comment(reddit_post_id, comments_locator.nth(index))
                if payload is None:
                    continue
                comments.append(payload)
                if len(comments) >= comment_limit_per_post:
                    break
            comments.sort(
                key=lambda comment: (
                    -int(comment["score"]),
                    int(comment["created_utc"]),
                    str(comment["reddit_comment_id"]),
                )
            )
            return comments[:comment_limit_per_post]
        except Exception as exc:
            raise RedditTransientError(f"Browser Reddit comments fetch failed: {exc}") from exc
        finally:
            page.close()

    def fetch_author_profile(self, author_username: str | None, subreddit: str | None = None) -> dict[str, Any]:
        del author_username, subreddit
        return {
            "author_account_age_days": None,
            "author_total_karma": None,
            "author_subreddit_karma": None,
        }

    def fetch_subreddit_snapshot(self, subreddit: str) -> dict[str, Any]:
        try:
            response = self._http.get(f"https://www.reddit.com/r/{subreddit}/about.json")
            response.raise_for_status()
            payload = response.json().get("data", {})
        except httpx.HTTPError:
            payload = {}
        return {
            "subreddit": subreddit,
            "subscribers_count": int(payload.get("subscribers", 0)) if payload.get("subscribers") is not None else None,
            "active_users_count": int(payload.get("active_user_count", 0))
            if payload.get("active_user_count") is not None
            else None,
            "rules_snapshot_url": f"https://www.reddit.com/r/{subreddit}/about/rules",
            "rules_json": json.dumps([]),
        }

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
        self._http.close()

    def _new_page(self):
        browser = self._browser_instance()
        context = browser.new_context(user_agent=self.user_agent)
        page = context.new_page()
        page.set_default_timeout(self.timeout_ms)
        return _BrowserPage(page, context)

    def _browser_instance(self):
        if self._browser is not None:
            return self._browser
        engine = self._browser_engine
        if engine is None:
            try:
                from playwright.sync_api import sync_playwright
            except ModuleNotFoundError as exc:
                raise RedditConfigurationError(
                    "REDDIT_PROVIDER=browser requires the 'playwright' package and browser binaries"
                ) from exc
            self._playwright = sync_playwright().start()
            engine = self._playwright.chromium
        self._browser = engine.launch(headless=self.headless)
        return self._browser

    def _ensure_not_blocked(self, page) -> None:
        title = (page.title() or "").strip().lower()
        body_text = ""
        try:
            body_text = (page.locator("body").inner_text(timeout=2000) or "").strip().lower()
        except Exception:
            body_text = ""

        blocked_markers = (
            "whoa there, pardner",
            "your request has been blocked due to a network policy",
        )
        if any(marker in title for marker in blocked_markers) or any(marker in body_text for marker in blocked_markers):
            raise RedditTransientError(
                "Reddit blocked browser-based search from the current network. "
                "Configure valid REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, and REDDIT_USER_AGENT "
                "and switch to REDDIT_PROVIDER=oauth."
            )

    @staticmethod
    def _search_url(query: str, subreddit: str | None) -> str:
        base = f"https://old.reddit.com/r/{subreddit}/search/" if subreddit else "https://old.reddit.com/search/"
        params = [f"q={quote_plus(query)}", "sort=relevance", "t=all"]
        if subreddit:
            params.append("restrict_sr=on")
        return f"{base}?{'&'.join(params)}"

    @staticmethod
    def _extract_search_post(locator) -> dict[str, Any] | None:
        post_id = locator.get_attribute("data-fullname")
        if not post_id or not post_id.startswith("t3_"):
            return None
        reddit_post_id = post_id[3:]
        title = _safe_inner_text(locator.locator("a.title").first)
        permalink = locator.get_attribute("data-permalink") or _extract_path(locator.locator("a.comments").first.get_attribute("href"))
        thread_url = _to_absolute_url(permalink)
        post_url = thread_url
        outbound_url = locator.locator("a.title").first.get_attribute("href")
        external_url = outbound_url if outbound_url and "reddit.com" not in urlparse(outbound_url).netloc else None
        external_domain = urlparse(external_url).netloc if external_url else None
        body_text = _safe_inner_text(locator.locator("div.expando div.usertext-body").first)
        created_utc = _locator_datetime_to_epoch(locator.locator("time").first)
        score = _extract_int(_safe_inner_text(locator.locator("div.score.unvoted").first))
        comments_text = _safe_inner_text(locator.locator("a.comments").first)
        comment_count = _extract_int(comments_text)
        subreddit = locator.get_attribute("data-subreddit")
        author = locator.get_attribute("data-author") or _safe_inner_text(locator.locator("a.author").first) or None
        flair = _safe_inner_text(locator.locator("span.linkflairlabel").first) or None
        thumbnail = locator.locator("a.thumbnail img").first.get_attribute("src")
        body_has_link = bool(HTTP_LINK_PATTERN.search(body_text))
        return {
            "reddit_post_id": reddit_post_id,
            "post_id": reddit_post_id,
            "platform": POST_PLATFORM,
            "post_url": post_url,
            "subreddit": subreddit,
            "title": title,
            "body_text": body_text,
            "body_has_link": body_has_link,
            "author_name": author,
            "author_username": author,
            "post_created_utc": created_utc,
            "fetched_at_utc": int(datetime.now(timezone.utc).timestamp()),
            "score": score,
            "upvote_ratio": None,
            "num_comments": comment_count,
            "is_self_post": external_url is None,
            "is_locked": False,
            "is_archived": False,
            "is_removed": body_text.strip() == "[removed]",
            "is_stickied": False,
            "flair_text": flair,
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
            "post_thumbnail_url": thumbnail if thumbnail and thumbnail.startswith("http") else None,
            "post_external_link_url": external_url,
            "post_external_link_domain": external_domain,
            "created_utc": created_utc,
            "permalink": permalink,
            "url": external_url or thread_url,
        }

    @staticmethod
    def _extract_comment(reddit_post_id: str, locator) -> dict[str, Any] | None:
        comment_id = locator.get_attribute("data-fullname")
        if not comment_id or not comment_id.startswith("t1_"):
            return None
        parent = locator.get_attribute("data-parent-fullname")
        parent_comment_id = parent[3:] if parent and parent.startswith("t1_") else None
        permalink = _extract_path(locator.locator("a.bylink").first.get_attribute("href"))
        return {
            "reddit_comment_id": comment_id[3:],
            "reddit_post_id": reddit_post_id,
            "parent_comment_id": parent_comment_id,
            "author_name": locator.get_attribute("data-author") or _safe_inner_text(locator.locator("a.author").first),
            "body_text": _safe_inner_text(locator.locator("div.usertext-body").first),
            "score": _extract_int(_safe_inner_text(locator.locator("span.score.unvoted").first)),
            "created_utc": _locator_datetime_to_epoch(locator.locator("time").first),
            "permalink": permalink,
        }


class _BrowserPage:
    def __init__(self, page, context) -> None:
        self.page = page
        self.context = context

    def __getattr__(self, item: str):
        return getattr(self.page, item)

    def close(self) -> None:
        try:
            self.page.close()
        finally:
            self.context.close()


def _safe_inner_text(locator) -> str:
    try:
        return (locator.inner_text() or "").strip()
    except Exception:
        return ""


def _extract_int(text: str) -> int:
    match = POINTS_PATTERN.search(text or "")
    return int(match.group(1)) if match else 0


def _extract_path(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    return parsed.path if parsed.scheme and parsed.netloc else url


def _to_absolute_url(path_or_url: str | None) -> str | None:
    if not path_or_url:
        return None
    if path_or_url.startswith("http"):
        return path_or_url
    return f"https://www.reddit.com{path_or_url}"


def _locator_datetime_to_epoch(locator) -> int:
    try:
        raw = locator.get_attribute("datetime") or ISO_DATETIME_FALLBACK
    except Exception:
        raw = ISO_DATETIME_FALLBACK
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = datetime.fromisoformat(ISO_DATETIME_FALLBACK)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())
