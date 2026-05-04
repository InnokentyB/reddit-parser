from __future__ import annotations

from datetime import date
from typing import Any

from app.config import ALLOWLIST_SUBREDDITS
from app.domain.search import normalize_query, normalize_search_expression, normalize_subreddit
from app.errors import AppError


MAX_QUERY_LENGTH = 200
MAX_QUERY_DEFINITION_LENGTH = 1000
MAX_LIMIT = 100
MAX_OFFSET = 1000
MAX_MIN_SCORE = 100000
MAX_DATE_SPAN_DAYS = 365
MAX_SUBREDDITS_PER_QUERY = 20


def validate_search_payload(payload: dict[str, Any]) -> dict[str, Any]:
    details: list[dict[str, Any]] = []
    is_query_definition = isinstance(payload.get("subreddits"), list)

    query = payload.get("query")
    if query is None:
        details.append({"field": "query", "code": "required", "message": "query is required"})
    elif not isinstance(query, str):
        details.append({"field": "query", "code": "invalid_type", "message": "query must be a string"})
    else:
        normalized_query = normalize_search_expression(query) if is_query_definition else normalize_query(query)
        if not normalized_query:
            details.append(
                {"field": "query", "code": "min_length", "message": "query must not be empty after trimming"}
            )
        max_query_length = MAX_QUERY_DEFINITION_LENGTH if is_query_definition else MAX_QUERY_LENGTH
        if len(query.strip()) > max_query_length:
            details.append(
                {
                    "field": "query",
                    "code": "max_exceeded",
                    "message": f"query must be less than or equal to {max_query_length} characters",
                }
            )
        if not is_query_definition and len(normalized_query.split()) > 10:
            details.append(
                {
                    "field": "query",
                    "code": "max_keywords_exceeded",
                    "message": "query must contain no more than 10 normalized keywords",
                }
            )

    subreddit = payload.get("subreddit")
    normalized_subreddit = None
    normalized_subreddits: list[str] = []
    if subreddit is not None:
        try:
            normalized_subreddit = normalize_subreddit(subreddit)
            if normalized_subreddit not in ALLOWLIST_SUBREDDITS:
                details.append(
                    {
                        "field": "subreddit",
                        "code": "not_allowed",
                        "message": "subreddit must be in the configured allow-list",
                    }
                )
        except ValueError:
            details.append(
                {
                    "field": "subreddit",
                    "code": "invalid_format",
                    "message": "subreddit must match ^[a-z0-9][a-z0-9_]{1,20}$ after normalization",
                }
            )

    subreddits = payload.get("subreddits")
    if subreddits is not None:
        if not isinstance(subreddits, list) or not subreddits:
            details.append(
                {
                    "field": "subreddits",
                    "code": "invalid_type",
                    "message": "subreddits must be a non-empty list",
                }
            )
        elif len(subreddits) > MAX_SUBREDDITS_PER_QUERY:
            details.append(
                {
                    "field": "subreddits",
                    "code": "max_exceeded",
                    "message": f"subreddits must contain no more than {MAX_SUBREDDITS_PER_QUERY} items",
                }
            )
        else:
            for value in subreddits:
                try:
                    normalized_value = normalize_subreddit(value)
                except ValueError:
                    details.append(
                        {
                            "field": "subreddits",
                            "code": "invalid_format",
                            "message": "every subreddit must match ^[a-z0-9][a-z0-9_]{1,20}$ after normalization",
                        }
                    )
                    continue
                if normalized_value not in ALLOWLIST_SUBREDDITS:
                    details.append(
                        {
                            "field": "subreddits",
                            "code": "not_allowed",
                            "message": "every subreddit must be in the configured allow-list",
                        }
                    )
                    continue
                normalized_subreddits.append(normalized_value)

    query_definition_id = payload.get("id")
    query_intent = payload.get("intent")
    query_cluster = payload.get("cluster")
    query_priority = payload.get("priority")
    match_must_include_any = payload.get("match_must_include_any", [])
    exclude_if_contains = payload.get("exclude_if_contains", [])
    exclude_regexes = payload.get("exclude_regexes", [])

    if is_query_definition:
        if not isinstance(query_definition_id, str) or not query_definition_id.strip():
            details.append(
                {"field": "id", "code": "required", "message": "id is required for query definition payloads"}
            )
        if not isinstance(query_intent, str) or not query_intent.strip():
            details.append(
                {"field": "intent", "code": "required", "message": "intent is required for query definition payloads"}
            )
        if not isinstance(query_cluster, str) or not query_cluster.strip():
            details.append(
                {"field": "cluster", "code": "required", "message": "cluster is required for query definition payloads"}
            )
        if not isinstance(query_priority, int) or isinstance(query_priority, bool) or query_priority < 1:
            details.append(
                {
                    "field": "priority",
                    "code": "invalid_range",
                    "message": "priority must be an integer greater than or equal to 1",
                }
            )
        if match_must_include_any and (
            not isinstance(match_must_include_any, list)
            or any(not isinstance(item, str) or not item.strip() for item in match_must_include_any)
        ):
            details.append(
                {
                    "field": "match_must_include_any",
                    "code": "invalid_type",
                    "message": "match_must_include_any must be a list of non-empty strings",
                }
            )
        if exclude_if_contains and (
            not isinstance(exclude_if_contains, list)
            or any(not isinstance(item, str) or not item.strip() for item in exclude_if_contains)
        ):
            details.append(
                {
                    "field": "exclude_if_contains",
                    "code": "invalid_type",
                    "message": "exclude_if_contains must be a list of non-empty strings",
                }
            )
        if exclude_regexes and (
            not isinstance(exclude_regexes, list)
            or any(not isinstance(item, str) or not item.strip() for item in exclude_regexes)
        ):
            details.append(
                {
                    "field": "exclude_regexes",
                    "code": "invalid_type",
                    "message": "exclude_regexes must be a list of non-empty strings",
                }
            )

    limit = payload.get("limit", 25)
    if not isinstance(limit, int) or isinstance(limit, bool) or not (1 <= limit <= MAX_LIMIT):
        details.append(
            {
                "field": "limit",
                "code": "max_exceeded" if isinstance(limit, int) and limit > MAX_LIMIT else "invalid",
                "message": f"limit must be less than or equal to {MAX_LIMIT}",
            }
        )

    min_score = payload.get("min_score", 0)
    if not isinstance(min_score, int) or isinstance(min_score, bool) or not (0 <= min_score <= MAX_MIN_SCORE):
        details.append(
            {
                "field": "min_score",
                "code": "invalid_range",
                "message": f"min_score must be between 0 and {MAX_MIN_SCORE}",
            }
        )

    include_comments = bool(payload.get("include_comments", False))
    enrich = bool(payload.get("enrich", False))

    date_from_raw = payload.get("date_from")
    date_to_raw = payload.get("date_to")
    parsed_date_from: date | None = None
    parsed_date_to: date | None = None
    if date_from_raw is not None:
        try:
            parsed_date_from = date.fromisoformat(date_from_raw)
        except Exception:
            details.append({"field": "date_from", "code": "invalid_format", "message": "date_from must be an ISO date"})
    if date_to_raw is not None:
        try:
            parsed_date_to = date.fromisoformat(date_to_raw)
        except Exception:
            details.append({"field": "date_to", "code": "invalid_format", "message": "date_to must be an ISO date"})
    if parsed_date_from and parsed_date_to:
        if parsed_date_from > parsed_date_to:
            details.append(
                {"field": "date_from", "code": "invalid_range", "message": "date_from must be less than or equal to date_to"}
            )
        elif (parsed_date_to - parsed_date_from).days > MAX_DATE_SPAN_DAYS:
            details.append(
                {
                    "field": "date_to",
                    "code": "max_span_exceeded",
                    "message": f"date span must be less than or equal to {MAX_DATE_SPAN_DAYS} days",
                }
            )

    idempotency_key = payload.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        details.append(
            {
                "field": "idempotency_key",
                "code": "required",
                "message": "idempotency_key is required",
            }
        )

    if details:
        raise AppError(400, "invalid_request", "Request validation failed", details, False)

    return {
        "query_mode": "query_definition" if is_query_definition else "simple",
        "query": normalize_search_expression(query) if is_query_definition else normalize_query(query),
        "subreddit": normalized_subreddit,
        "subreddits": normalized_subreddits,
        "query_definition_id": query_definition_id.strip() if isinstance(query_definition_id, str) else None,
        "query_intent": query_intent.strip() if isinstance(query_intent, str) else None,
        "query_cluster": query_cluster.strip() if isinstance(query_cluster, str) else None,
        "query_priority": query_priority if isinstance(query_priority, int) and not isinstance(query_priority, bool) else None,
        "match_must_include_any": [item.strip() for item in match_must_include_any] if isinstance(match_must_include_any, list) else [],
        "exclude_if_contains": [item.strip() for item in exclude_if_contains] if isinstance(exclude_if_contains, list) else [],
        "exclude_regexes": [item.strip() for item in exclude_regexes] if isinstance(exclude_regexes, list) else [],
        "limit": limit,
        "min_score": min_score,
        "date_from": date_from_raw,
        "date_to": date_to_raw,
        "include_comments": include_comments,
        "enrich": enrich,
        "idempotency_key": idempotency_key,
    }


def validate_refresh_payload(payload: dict[str, Any]) -> dict[str, str]:
    idempotency_key = payload.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise AppError(
            400,
            "invalid_request",
            "Request validation failed",
            [
                {
                    "field": "idempotency_key",
                    "code": "required",
                    "message": "idempotency_key is required",
                }
            ],
            False,
        )
    return {"idempotency_key": idempotency_key}


def validate_template_import_payload(payload: dict[str, Any]) -> dict[str, Any]:
    details: list[dict[str, Any]] = []
    yaml_content = payload.get("yaml_content")
    query_bank = payload.get("query_bank")
    if yaml_content is None and query_bank is None:
        details.append(
            {
                "field": "yaml_content",
                "code": "required",
                "message": "yaml_content or query_bank is required",
            }
        )
    if yaml_content is not None and not isinstance(yaml_content, str):
        details.append(
            {
                "field": "yaml_content",
                "code": "invalid_type",
                "message": "yaml_content must be a string",
            }
        )
    if query_bank is not None and not isinstance(query_bank, dict):
        details.append(
            {
                "field": "query_bank",
                "code": "invalid_type",
                "message": "query_bank must be an object",
            }
        )

    idempotency_key = payload.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        details.append(
            {
                "field": "idempotency_key",
                "code": "required",
                "message": "idempotency_key is required",
            }
        )

    schedule_daily = payload.get("schedule_daily", True)
    if not isinstance(schedule_daily, bool):
        details.append(
            {
                "field": "schedule_daily",
                "code": "invalid_type",
                "message": "schedule_daily must be a boolean",
            }
        )

    limit = payload.get("limit", 50)
    if not isinstance(limit, int) or isinstance(limit, bool) or not (1 <= limit <= MAX_LIMIT):
        details.append(
            {
                "field": "limit",
                "code": "invalid_range",
                "message": f"limit must be between 1 and {MAX_LIMIT}",
            }
        )

    min_score = payload.get("min_score", 0)
    if not isinstance(min_score, int) or isinstance(min_score, bool) or not (0 <= min_score <= MAX_MIN_SCORE):
        details.append(
            {
                "field": "min_score",
                "code": "invalid_range",
                "message": f"min_score must be between 0 and {MAX_MIN_SCORE}",
            }
        )

    if details:
        raise AppError(400, "invalid_request", "Request validation failed", details, False)

    return {
        "yaml_content": yaml_content,
        "query_bank": query_bank,
        "schedule_daily": schedule_daily,
        "limit": limit,
        "min_score": min_score,
        "include_comments": bool(payload.get("include_comments", True)),
        "enrich": bool(payload.get("enrich", True)),
        "date_from": payload.get("date_from"),
        "date_to": payload.get("date_to"),
        "idempotency_key": idempotency_key,
    }


def validate_posts_query(limit: int = 25, offset: int = 0) -> tuple[int, int]:
    details: list[dict[str, Any]] = []
    if not (0 < limit <= MAX_LIMIT):
        details.append(
            {
                "field": "limit",
                "code": "max_exceeded" if limit > MAX_LIMIT else "invalid_range",
                "message": f"limit must be less than or equal to {MAX_LIMIT}",
            }
        )
    if not (0 <= offset <= MAX_OFFSET):
        details.append(
            {
                "field": "offset",
                "code": "max_exceeded" if offset > MAX_OFFSET else "invalid_range",
                "message": f"offset must be less than or equal to {MAX_OFFSET}",
            }
        )
    if details:
        raise AppError(400, "invalid_request", "Request validation failed", details, False)
    return limit, offset
