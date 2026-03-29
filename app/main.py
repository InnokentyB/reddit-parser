from __future__ import annotations

import json
from datetime import date
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.config import default_database_url
from app.db import Base, create_engine_and_sessionmaker
from app.domain.search import build_query_hash
from app.errors import AppError, create_error_response
from app.repository import Repository
from app.validation import validate_posts_query, validate_refresh_payload, validate_search_payload


IDEMPOTENCY_RETENTION_HOURS = 24
templates = Jinja2Templates(directory="templates")


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
    engine, session_factory = create_engine_and_sessionmaker(
        testing=testing,
        database_url=None if testing else default_database_url(),
    )
    Base.metadata.create_all(engine)
    app.state.engine = engine
    app.state.repository = Repository(session_factory)

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

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def home(
        request: Request,
        workspace_id: str = Query("test-workspace"),
    ):
        jobs = app.state.repository.list_recent_jobs(workspace_id=workspace_id, limit=20)
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "workspace_id": workspace_id,
                "jobs": jobs,
            },
        )

    @app.get("/ui/jobs")
    async def ui_jobs(
        workspace_id: str = Query(...),
    ):
        jobs = app.state.repository.list_recent_jobs(workspace_id=workspace_id, limit=20)
        return {"jobs": jobs}

    @app.get("/posts")
    async def list_posts(
        request: Request,
        limit: int = 25,
        offset: int = 0,
        x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    ):
        get_workspace_id(request, x_workspace_id)
        validated_limit, validated_offset = validate_posts_query(limit=limit, offset=offset)
        return app.state.repository.list_posts(validated_limit, validated_offset)

    @app.get("/posts/{reddit_post_id}")
    async def get_post(
        reddit_post_id: str,
        request: Request,
        x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    ):
        get_workspace_id(request, x_workspace_id)
        result = app.state.repository.get_post(reddit_post_id)
        if result is None:
            raise AppError(404, "not_found", f"Post '{reddit_post_id}' was not found", [], False)
        return result

    @app.post("/search")
    async def create_search(
        payload: dict[str, Any],
        request: Request,
        x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    ):
        workspace_id = get_workspace_id(request, x_workspace_id)
        normalized_payload = validate_search_payload(payload)
        payload_hash = build_query_hash(normalized_payload)
        repository = app.state.repository

        key = (
            workspace_id,
            "POST",
            "/search",
            normalized_payload["idempotency_key"],
        )
        existing = repository.get_idempotency_record(*key)
        if existing is not None:
            if existing.payload_hash != payload_hash:
                raise AppError(
                    409,
                    "idempotency_payload_mismatch",
                    "idempotency key was reused with a different payload",
                    [],
                    False,
                )
            return JSONResponse(status_code=202, content=json.loads(existing.response_json))

        response_body = repository.create_search_job(workspace_id, normalized_payload, payload_hash)
        repository.put_idempotency_record(
            workspace_id=workspace_id,
            method="POST",
            route="/search",
            idempotency_key=normalized_payload["idempotency_key"],
            payload_hash=payload_hash,
            response_body=response_body,
            retention_hours=IDEMPOTENCY_RETENTION_HOURS,
        )
        return JSONResponse(status_code=202, content=response_body)

    @app.get("/search/{job_id}")
    async def get_search(
        job_id: str,
        request: Request,
        x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    ):
        workspace_id = get_workspace_id(request, x_workspace_id)
        result = app.state.repository.get_search_view(job_id, workspace_id)
        if result is None:
            raise AppError(404, "not_found", f"Search job '{job_id}' was not found", [], False)
        return result

    @app.post("/refresh/{job_id}")
    async def refresh_search(
        job_id: str,
        payload: dict[str, Any],
        request: Request,
        x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    ):
        workspace_id = get_workspace_id(request, x_workspace_id)
        normalized_payload = validate_refresh_payload(payload)
        repository = app.state.repository
        job = repository.get_job(job_id, workspace_id)
        if job is None:
            raise AppError(404, "not_found", f"Search job '{job_id}' was not found", [], False)

        payload_hash = build_query_hash(
            {
                "query": job.query_text,
                "subreddit": job.subreddit,
                "min_score": job.min_score,
                "date_from": job.date_from.isoformat() if job.date_from else None,
                "date_to": job.date_to.isoformat() if job.date_to else None,
                "limit": job.limit,
                "include_comments": job.include_comments,
                "enrich": job.enrich,
            }
        )
        key = (
            workspace_id,
            "POST",
            f"/refresh/{job_id}",
            normalized_payload["idempotency_key"],
        )
        existing = repository.get_idempotency_record(*key)
        if existing is not None:
            if existing.payload_hash != payload_hash:
                raise AppError(
                    409,
                    "idempotency_payload_mismatch",
                    "idempotency key was reused with a different payload",
                    [],
                    False,
                )
            return JSONResponse(status_code=202, content=json.loads(existing.response_json))

        response_body = repository.create_refresh_run(job_id)
        repository.put_idempotency_record(
            workspace_id=workspace_id,
            method="POST",
            route=f"/refresh/{job_id}",
            idempotency_key=normalized_payload["idempotency_key"],
            payload_hash=payload_hash,
            response_body=response_body,
            retention_hours=IDEMPOTENCY_RETENTION_HOURS,
        )
        return JSONResponse(status_code=202, content=response_body)

    return app
