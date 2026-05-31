from __future__ import annotations

from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit
from xml.etree import ElementTree
import re

import httpx

from app.config import CONTRACT_VERSION, INDIE_HACKERS_FEED_URL, SOURCE_INDIE_HACKERS


TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")


class IndieHackersError(Exception):
    """Base Indie Hackers provider error."""


class IndieHackersTransientError(IndieHackersError):
    """Retryable Indie Hackers feed error."""


class IndieHackersFeedClient:
    def __init__(
        self,
        *,
        feed_url: str = INDIE_HACKERS_FEED_URL,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.feed_url = feed_url
        self._client = httpx.Client(timeout=timeout, transport=transport, follow_redirects=True)

    def search_posts(
        self,
        query: str,
        subreddit: str | None,
        limit: int,
        min_score: int,
        date_from: date | None,
        date_to: date | None,
    ) -> list[dict]:
        del subreddit, min_score
        try:
            response = self._client.get(self._search_feed_url(query))
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise IndieHackersTransientError(f"Indie Hackers feed request failed: {exc}") from exc

        try:
            root = ElementTree.fromstring(response.text)
        except ElementTree.ParseError as exc:
            raise IndieHackersTransientError(f"Indie Hackers feed payload was invalid XML: {exc}") from exc

        normalized_terms = [term for term in query.lower().split(" ") if term]
        items: list[dict] = []
        for item in root.findall("./channel/item"):
            normalized = self._normalize_item(item)
            if normalized is None:
                continue
            created_date = datetime.fromtimestamp(normalized["created_utc"], tz=timezone.utc).date()
            if date_from and created_date < date_from:
                continue
            if date_to and created_date > date_to:
                continue
            haystack = f"{normalized['title']} {normalized['body_text']}".lower()
            if normalized_terms and not all(term in haystack for term in normalized_terms):
                continue
            items.append(normalized)

        items.sort(key=lambda post: (-int(post["created_utc"]), str(post["reddit_post_id"])))
        return items[:limit]

    def _search_feed_url(self, query: str) -> str:
        if not query.strip():
            return self.feed_url

        parts = urlsplit(self.feed_url)
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        params["q"] = query
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))

    def fetch_post_comments(self, reddit_post_id: str, comment_limit_per_post: int) -> list[dict]:
        del reddit_post_id, comment_limit_per_post
        return []

    def fetch_author_profile(self, author_username: str | None, subreddit: str | None = None) -> dict[str, None]:
        del author_username, subreddit
        return {
            "author_account_age_days": None,
            "author_total_karma": None,
            "author_subreddit_karma": None,
        }

    def close(self) -> None:
        self._client.close()

    def _normalize_item(self, item: ElementTree.Element) -> dict | None:
        link = self._text(item.find("link"))
        guid = self._text(item.find("guid"))
        identifier = guid or link
        if not identifier:
            return None

        title = self._text(item.find("title"))
        description = self._text(item.find("description"))
        creator = self._creator_name(item)
        published_at = self._published_at(item)
        permalink = urlparse(link).path if link else None
        external_link_domain = urlparse(link).netloc or None if link else None
        body_text = self._clean_text(description)
        return {
            "reddit_post_id": self._build_post_id(identifier),
            "platform": SOURCE_INDIE_HACKERS,
            "post_url": link,
            "subreddit": None,
            "title": title,
            "body_text": body_text,
            "body_has_link": bool(link),
            "author_name": creator,
            "post_created_utc": int(published_at.timestamp()),
            "fetched_at_utc": int(datetime.now(timezone.utc).timestamp()),
            "score": 0,
            "upvote_ratio": None,
            "num_comments": 0,
            "is_self_post": True,
            "is_locked": False,
            "is_archived": False,
            "is_removed": False,
            "is_stickied": False,
            "flair_text": None,
            "created_utc": int(published_at.timestamp()),
            "permalink": permalink,
            "url": link,
            "contract_version": CONTRACT_VERSION,
            "post_external_link_url": link,
            "post_external_link_domain": external_link_domain,
        }

    @staticmethod
    def _text(node: ElementTree.Element | None) -> str:
        if node is None or node.text is None:
            return ""
        return node.text.strip()

    def _published_at(self, item: ElementTree.Element) -> datetime:
        pub_date = self._text(item.find("pubDate"))
        if not pub_date:
            return datetime.now(timezone.utc)
        published_at = parsedate_to_datetime(pub_date)
        if published_at.tzinfo is None:
            return published_at.replace(tzinfo=timezone.utc)
        return published_at.astimezone(timezone.utc)

    def _creator_name(self, item: ElementTree.Element) -> str | None:
        creator = item.find("{http://purl.org/dc/elements/1.1/}creator")
        value = self._text(creator)
        return value or None

    @staticmethod
    def _build_post_id(identifier: str) -> str:
        digest = sha256(identifier.encode("utf-8")).hexdigest()[:24]
        return f"ih_{digest}"

    @staticmethod
    def _clean_text(value: str) -> str:
        without_tags = TAG_PATTERN.sub(" ", unescape(value))
        return WHITESPACE_PATTERN.sub(" ", without_tags).strip()
