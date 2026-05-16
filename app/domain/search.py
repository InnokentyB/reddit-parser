from __future__ import annotations

from hashlib import sha256
import json
import re
import unicodedata
from typing import Any

from app.config import SOURCE_REDDIT


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


def normalize_search_expression(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    return " ".join(normalized.strip().split())


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
    query_mode = str(payload.get("query_mode", "simple"))
    if query_mode == "query_definition":
        normalized_query = normalize_search_expression(str(payload.get("query", "")))
    else:
        normalized_query = normalize_query(str(payload.get("query", "")))

    subreddits = payload.get("subreddits") or []
    normalized_subreddits = [normalize_subreddit(item) for item in subreddits]
    match_must_include_any = [str(item).strip().lower() for item in payload.get("match_must_include_any", [])]
    exclude_if_contains = [str(item).strip().lower() for item in payload.get("exclude_if_contains", [])]
    exclude_regexes = [str(item).strip() for item in payload.get("exclude_regexes", [])]
    normalized_payload = {
        "source": str(payload.get("source", SOURCE_REDDIT)).strip().lower() or SOURCE_REDDIT,
        "query_mode": query_mode,
        "query": normalized_query,
        "subreddit": normalize_subreddit(payload.get("subreddit")),
        "query_definition_id": payload.get("query_definition_id") or payload.get("id"),
        "query_cluster": payload.get("query_cluster") or payload.get("cluster"),
        "query_priority": payload.get("query_priority") or payload.get("priority"),
        "subreddits": normalized_subreddits,
        "match_must_include_any": match_must_include_any,
        "exclude_if_contains": exclude_if_contains,
        "exclude_regexes": exclude_regexes,
        "min_score": int(payload.get("min_score", 0)),
        "date_from": payload.get("date_from"),
        "date_to": payload.get("date_to"),
        "limit": int(payload.get("limit", 25)),
        "include_comments": bool(payload.get("include_comments", False)),
        "enrich": bool(payload.get("enrich", False)),
    }
    digest_input = json.dumps(normalized_payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return sha256(digest_input).hexdigest()
