from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from app.domain.search import build_query_hash, normalize_query, normalize_subreddit


MAX_QUERY_LENGTH = 200
MAX_LIMIT = 100
MAX_OFFSET = 1000
MAX_MIN_SCORE = 100000
MAX_DATE_SPAN_DAYS = 365
IDEMPOTENCY_RETENTION_HOURS = 24


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []
        self.retryable = retryable


@dataclass
class SearchJob:
    id: str
    workspace_id: str
    payload: dict[str, Any]
    query_hash: str
    status: str = "running"
    active_run_id: str | None = None


@dataclass
class JobRun:
    id: str
    job_id: str
    status: str = "queued"


@dataclass
class AppState:
    jobs: dict[str, SearchJob] = field(default_factory=dict)
    runs: dict[str, JobRun] = field(default_factory=dict)
    idempotency: dict[tuple[str, str, str, str], dict[str, Any]] = field(default_factory=dict)


def create_error_response(
    request_id: str,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    retryable: bool = False,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or [],
                "retryable": retryable,
                "request_id": request_id,
            }
        },
    )


def validate_search_payload(payload: dict[str, Any]) -> dict[str, Any]:
    details: list[dict[str, Any]] = []

    query = payload.get("query")
    if query is None:
        details.append(
            {"field": "query", "code": "required", "message": "query is required"}
        )
    elif not isinstance(query, str):
        details.append(
            {"field": "query", "code": "invalid_type", "message": "query must be a string"}
        )
    else:
        normalized_query = normalize_query(query)
        if not normalized_query:
            details.append(
                {
                    "field": "query",
                    "code": "min_length",
                    "message": "query must not be empty after trimming",
                }
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
    if not isinstance(min_score, int) or isinstance(min_score, bool) or not (
        0 <= min_score <= MAX_MIN_SCORE
    ):
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
            details.append(
                {
                    "field": "date_from",
                    "code": "invalid_format",
                    "message": "date_from must be an ISO date",
                }
            )
    if date_to_raw is not None:
        try:
            parsed_date_to = date.fromisoformat(date_to_raw)
        except Exception:
            details.append(
                {
                    "field": "date_to",
                    "code": "invalid_format",
                    "message": "date_to must be an ISO date",
                }
            )
    if parsed_date_from and parsed_date_to:
        if parsed_date_from > parsed_date_to:
            details.append(
                {
                    "field": "date_from",
                    "code": "invalid_range",
                    "message": "date_from must be less than or equal to date_to",
                }
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


def get_workspace_id(request: Request, x_workspace_id: str | None) -> str:
    if x_workspace_id:
        return x_workspace_id
    if request.app.state.testing:
        return "internal-test-workspace"
    raise AppError(
        400,
        "invalid_request",
        "Request validation failed",
        [
            {
                "field": "X-Workspace-Id",
                "code": "required",
                "message": "X-Workspace-Id header is required",
            }
        ],
        False,
    )


def create_app(testing: bool = False) -> FastAPI:
    app = FastAPI()
    app.state.testing = testing
    app.state.store = AppState()

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return create_error_response(
            request_id=request.state.request_id,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
            retryable=exc.retryable,
        )

    @app.get("/posts")
    async def list_posts(
        request: Request,
        limit: int = 25,
        offset: int = 0,
        x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    ):
        get_workspace_id(request, x_workspace_id)
        validated_limit, validated_offset = validate_posts_query(limit=limit, offset=offset)
        return {
            "data": [],
            "pagination": {
                "limit": validated_limit,
                "offset": validated_offset,
                "returned": 0,
                "has_more": False,
            },
            "ordering": "created_utc_desc",
        }

    @app.get("/posts/{reddit_post_id}")
    async def get_post(
        reddit_post_id: str,
        request: Request,
        x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    ):
        get_workspace_id(request, x_workspace_id)
        raise AppError(404, "not_found", f"Post '{reddit_post_id}' was not found", [], False)

    @app.post("/search")
    async def create_search(
        payload: dict[str, Any],
        request: Request,
        x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    ):
        workspace_id = get_workspace_id(request, x_workspace_id)
        normalized_payload = validate_search_payload(payload)
        payload_hash = build_query_hash(normalized_payload)

        key = (
            workspace_id,
            "POST",
            "/search",
            normalized_payload["idempotency_key"],
        )
        existing = app.state.store.idempotency.get(key)
        if existing is not None:
            if existing["payload_hash"] != payload_hash:
                raise AppError(
                    409,
                    "idempotency_payload_mismatch",
                    "idempotency key was reused with a different payload",
                    [],
                    False,
                )
            return JSONResponse(status_code=202, content=existing["response"])

        job_id = str(uuid4())
        run_id = str(uuid4())
        response_body = {"job_id": job_id, "run_id": run_id, "status": "queued"}

        app.state.store.jobs[job_id] = SearchJob(
            id=job_id,
            workspace_id=workspace_id,
            payload=normalized_payload,
            query_hash=payload_hash,
            status="running",
            active_run_id=run_id,
        )
        app.state.store.runs[run_id] = JobRun(id=run_id, job_id=job_id, status="queued")
        app.state.store.idempotency[key] = {
            "payload_hash": payload_hash,
            "response": response_body,
            "retention_hours": IDEMPOTENCY_RETENTION_HOURS,
        }
        return JSONResponse(status_code=202, content=response_body)

    @app.get("/search/{job_id}")
    async def get_search(
        job_id: str,
        request: Request,
        x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    ):
        workspace_id = get_workspace_id(request, x_workspace_id)
        job = app.state.store.jobs.get(job_id)
        if job is None or job.workspace_id != workspace_id:
            raise AppError(404, "not_found", f"Search job '{job_id}' was not found", [], False)

        run = app.state.store.runs.get(job.active_run_id) if job.active_run_id else None
        return {
            "job_id": job.id,
            "workspace_id": job.workspace_id,
            "status": "running" if run else job.status,
            "query": {
                "query_text": job.payload["query"],
                "subreddit": job.payload["subreddit"],
                "min_score": job.payload["min_score"],
                "date_from": job.payload["date_from"],
                "date_to": job.payload["date_to"],
                "limit": job.payload["limit"],
                "include_comments": job.payload["include_comments"],
                "enrich": job.payload["enrich"],
            },
            "latest_run": {
                "run_id": run.id if run else None,
                "status": run.status if run else "completed",
                "trigger_type": "manual",
                "started_at": None,
                "finished_at": None,
                "posts_found": 0,
                "comments_found": 0,
                "partial": False,
                "error_code": None,
                "error_message": None,
            },
            "results": {"total_posts": 0, "returned_posts": 0, "ordering": "matched_at_desc", "items": []},
        }

    @app.post("/refresh/{job_id}")
    async def refresh_search(
        job_id: str,
        payload: dict[str, Any],
        request: Request,
        x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    ):
        workspace_id = get_workspace_id(request, x_workspace_id)
        normalized_payload = validate_refresh_payload(payload)

        job = app.state.store.jobs.get(job_id)
        if job is None or job.workspace_id != workspace_id:
            raise AppError(404, "not_found", f"Search job '{job_id}' was not found", [], False)

        payload_hash = build_query_hash(
            {
                "query": job.payload["query"],
                "subreddit": job.payload["subreddit"],
                "min_score": job.payload["min_score"],
                "date_from": job.payload["date_from"],
                "date_to": job.payload["date_to"],
                "limit": job.payload["limit"],
                "include_comments": job.payload["include_comments"],
                "enrich": job.payload["enrich"],
            }
        )
        key = (
            workspace_id,
            "POST",
            f"/refresh/{job_id}",
            normalized_payload["idempotency_key"],
        )
        existing = app.state.store.idempotency.get(key)
        if existing is not None:
            if existing["payload_hash"] != payload_hash:
                raise AppError(
                    409,
                    "idempotency_payload_mismatch",
                    "idempotency key was reused with a different payload",
                    [],
                    False,
                )
            return JSONResponse(status_code=202, content=existing["response"])

        run_id = str(uuid4())
        response_body = {"job_id": job_id, "run_id": run_id, "status": "queued"}
        job.active_run_id = run_id
        job.status = "running"
        app.state.store.runs[run_id] = JobRun(id=run_id, job_id=job_id, status="queued")
        app.state.store.idempotency[key] = {
            "payload_hash": payload_hash,
            "response": response_body,
            "retention_hours": IDEMPOTENCY_RETENTION_HOURS,
        }
        return JSONResponse(status_code=202, content=response_body)

    return app
