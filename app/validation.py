from __future__ import annotations

from datetime import date
from typing import Any

from app.domain.search import normalize_query, normalize_subreddit
from app.errors import AppError


MAX_QUERY_LENGTH = 200
MAX_LIMIT = 100
MAX_OFFSET = 1000
MAX_MIN_SCORE = 100000
MAX_DATE_SPAN_DAYS = 365


def validate_search_payload(payload: dict[str, Any]) -> dict[str, Any]:
    details: list[dict[str, Any]] = []

    query = payload.get("query")
    if query is None:
        details.append({"field": "query", "code": "required", "message": "query is required"})
    elif not isinstance(query, str):
        details.append({"field": "query", "code": "invalid_type", "message": "query must be a string"})
    else:
        normalized_query = normalize_query(query)
        if not normalized_query:
            details.append(
                {"field": "query", "code": "min_length", "message": "query must not be empty after trimming"}
            )
        if len(query.strip()) > MAX_QUERY_LENGTH:
            details.append(
                {
                    "field": "query",
                    "code": "max_exceeded",
                    "message": f"query must be less than or equal to {MAX_QUERY_LENGTH} characters",
                }
            )
        if len(normalized_query.split()) > 10:
            details.append(
                {
                    "field": "query",
                    "code": "max_keywords_exceeded",
                    "message": "query must contain no more than 10 normalized keywords",
                }
            )

    subreddit = payload.get("subreddit")
    normalized_subreddit = None
    if subreddit is not None:
        try:
            normalized_subreddit = normalize_subreddit(subreddit)
        except ValueError:
            details.append(
                {
                    "field": "subreddit",
                    "code": "invalid_format",
                    "message": "subreddit must match ^[a-z0-9][a-z0-9_]{1,20}$ after normalization",
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
        "query": normalize_query(query),
        "subreddit": normalized_subreddit,
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
