from __future__ import annotations

from hashlib import sha256
import re
import unicodedata
from typing import Any


SUBREDDIT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{1,20}$")


def normalize_query(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    normalized = " ".join(normalized.strip().lower().split())
    if not normalized:
        return ""

    seen: set[str] = set()
    ordered_tokens: list[str] = []
    for token in normalized.split(" "):
        if token not in seen:
            seen.add(token)
            ordered_tokens.append(token)
    return " ".join(ordered_tokens)


def normalize_subreddit(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    if normalized.startswith("r/"):
        normalized = normalized[2:]

    if not normalized or not SUBREDDIT_PATTERN.fullmatch(normalized):
        raise ValueError("Invalid subreddit value")
    return normalized


def build_query_hash(payload: dict[str, Any]) -> str:
    normalized_payload = {
        "query": normalize_query(str(payload.get("query", ""))),
        "subreddit": normalize_subreddit(payload.get("subreddit")),
        "min_score": int(payload.get("min_score", 0)),
        "date_from": payload.get("date_from"),
        "date_to": payload.get("date_to"),
        "limit": int(payload.get("limit", 25)),
        "include_comments": bool(payload.get("include_comments", False)),
        "enrich": bool(payload.get("enrich", False)),
    }
    digest_input = repr(normalized_payload).encode("utf-8")
    return sha256(digest_input).hexdigest()
