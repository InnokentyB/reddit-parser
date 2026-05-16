from __future__ import annotations

import json
from datetime import date
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.config import default_database_url
from app.db import Base, create_engine_and_sessionmaker, ensure_runtime_schema
from app.domain.search import build_query_hash
from app.creator_api import create_creator_app
from app.errors import AppError, create_error_response
from app.query_bank import parse_query_bank_yaml
from app.repository import Repository
from app.schemas import (
    ErrorResponse,
    HealthResponse,
    InsightsResponse,
    PostDetailResponse,
    PostsListResponse,
    QueueResponse,
    RefreshRequest,
    SearchRequest,
    SearchViewResponse,
    SummaryResponse,
    TemplateImportRequest,
    TemplateImportResponse,
    TemplateResponse as SearchTemplateResponse,
    TemplateRunResponse,
    TemplatesListResponse,
    UiJobsResponse,
    UiTemplatesResponse,
)
from app.validation import (
    validate_posts_query,
    validate_refresh_payload,
    validate_search_payload,
    validate_template_import_payload,
)


IDEMPOTENCY_RETENTION_HOURS = 24
templates = Jinja2Templates(directory="templates")
STANDARD_ERROR_RESPONSES = {
    400: {"model": ErrorResponse, "description": "Validation error"},
    404: {"model": ErrorResponse, "description": "Resource not found"},
    409: {"model": ErrorResponse, "description": "Idempotency or state conflict"},
    429: {"model": ErrorResponse, "description": "Rate limited"},
    503: {"model": ErrorResponse, "description": "Dependency or capacity issue"},
}


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
    app = FastAPI(
        title="Reddit Insight Collector API",
        version="0.2.0",
        summary="Async Reddit research service for planner integrations.",
        description=(
            "Collect Reddit posts and comments into workspace-scoped research jobs, "
            "then expose normalized posts, planner-friendly insights, and job summaries."
        ),
        contact={"name": "InnokentyB", "url": "https://github.com/InnokentyB/reddit-parser"},
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        openapi_tags=[
            {"name": "health", "description": "Operational health and readiness."},
            {"name": "search", "description": "Create, poll, and refresh async Reddit research jobs."},
            {"name": "posts", "description": "Read normalized Reddit posts and comments."},
            {"name": "insights", "description": "Planner-friendly insight extraction and aggregated summaries."},
            {"name": "templates", "description": "Saved query templates, YAML import, and scheduled reruns."},
            {"name": "ui", "description": "Basic inspection and debugging UI endpoints."},
        ],
    )
    app.state.testing = testing
    engine, session_factory = create_engine_and_sessionmaker(
        testing=testing,
        database_url=None if testing else default_database_url(),
    )
    Base.metadata.create_all(engine)
    ensure_runtime_schema(engine)
    app.state.engine = engine
    app.state.repository = Repository(session_factory)
    app.mount("/creator-api", create_creator_app(app.state.repository, testing=testing))

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

    @app.get("/health", response_model=HealthResponse, tags=["health"], summary="Health check")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def home(
        request: Request,
        workspace_id: str = Query("test-workspace"),
    ):
        jobs = app.state.repository.list_recent_jobs(workspace_id=workspace_id, limit=20)
        saved_templates = app.state.repository.list_templates(workspace_id=workspace_id, limit=100)
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "workspace_id": workspace_id,
                "jobs": jobs,
                "templates": saved_templates,
            },
        )

    @app.get("/ui/jobs", response_model=UiJobsResponse, tags=["ui"], summary="List recent jobs for the UI")
    async def ui_jobs(
        workspace_id: str = Query(...),
    ):
        jobs = app.state.repository.list_recent_jobs(workspace_id=workspace_id, limit=20)
        return {"jobs": jobs}

    @app.get(
        "/ui/templates",
        response_model=UiTemplatesResponse,
        tags=["ui"],
        summary="List templates for the UI",
    )
    async def ui_templates(
        workspace_id: str = Query(...),
    ):
        templates = app.state.repository.list_templates(workspace_id=workspace_id, limit=100)
        return {"templates": templates}

    @app.get(
        "/posts",
        response_model=PostsListResponse,
        tags=["posts"],
        summary="List normalized Reddit posts for a workspace",
        responses=STANDARD_ERROR_RESPONSES,
    )
    async def list_posts(
        request: Request,
        limit: int = 25,
        offset: int = 0,
        x_workspace_id: str | None = Header(
            default=None,
            alias="X-Workspace-Id",
            description="Workspace or project isolation key.",
        ),
    ):
        workspace_id = get_workspace_id(request, x_workspace_id)
        validated_limit, validated_offset = validate_posts_query(limit=limit, offset=offset)
        return app.state.repository.list_posts(validated_limit, validated_offset, workspace_id)

    @app.get(
        "/posts/{reddit_post_id}",
        response_model=PostDetailResponse,
        tags=["posts"],
        summary="Get one normalized post with comments",
        responses=STANDARD_ERROR_RESPONSES,
    )
    async def get_post(
        reddit_post_id: str,
        request: Request,
        x_workspace_id: str | None = Header(
            default=None,
            alias="X-Workspace-Id",
            description="Workspace or project isolation key.",
        ),
    ):
        workspace_id = get_workspace_id(request, x_workspace_id)
        result = app.state.repository.get_post(reddit_post_id, workspace_id)
        if result is None:
            raise AppError(404, "not_found", f"Post '{reddit_post_id}' was not found", [], False)
        return result

    @app.get(
        "/insights",
        response_model=InsightsResponse,
        tags=["insights"],
        summary="List planner-friendly insights",
        responses=STANDARD_ERROR_RESPONSES,
    )
    async def list_insights(
        request: Request,
        limit: int = 25,
        offset: int = 0,
        job_id: str | None = None,
        insight_type: str | None = Query(default=None, alias="type"),
        x_workspace_id: str | None = Header(
            default=None,
            alias="X-Workspace-Id",
            description="Workspace or project isolation key.",
        ),
    ):
        workspace_id = get_workspace_id(request, x_workspace_id)
        validated_limit, validated_offset = validate_posts_query(limit=limit, offset=offset)
        return app.state.repository.get_insights(
            workspace_id=workspace_id,
            limit=validated_limit,
            offset=validated_offset,
            job_id=job_id,
            insight_type=insight_type,
        )

    @app.post(
        "/search",
        response_model=QueueResponse,
        status_code=202,
        tags=["search"],
        summary="Create and queue a Reddit search job",
        responses=STANDARD_ERROR_RESPONSES,
    )
    async def create_search(
        payload: SearchRequest,
        request: Request,
        x_workspace_id: str | None = Header(
            default=None,
            alias="X-Workspace-Id",
            description="Workspace or project isolation key.",
        ),
    ):
        workspace_id = get_workspace_id(request, x_workspace_id)
        normalized_payload = validate_search_payload(payload.model_dump(exclude_none=True))
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

    @app.post(
        "/search-templates/import",
        response_model=TemplateImportResponse,
        status_code=202,
        tags=["templates"],
        summary="Import a YAML or JSON query bank as saved templates",
        responses=STANDARD_ERROR_RESPONSES,
    )
    async def import_search_templates(
        payload: TemplateImportRequest,
        request: Request,
        x_workspace_id: str | None = Header(
            default=None,
            alias="X-Workspace-Id",
            description="Workspace or project isolation key.",
        ),
    ):
        workspace_id = get_workspace_id(request, x_workspace_id)
        normalized_payload = validate_template_import_payload(payload.model_dump(exclude_none=True))
        repository = app.state.repository
        payload_hash = build_query_hash(
            {
                "query_mode": "template_import",
                "query": normalized_payload.get("yaml_content") or json.dumps(normalized_payload.get("query_bank"), sort_keys=True),
                "limit": normalized_payload["limit"],
                "min_score": normalized_payload["min_score"],
                "include_comments": normalized_payload["include_comments"],
                "enrich": normalized_payload["enrich"],
            }
        )
        key = (
            workspace_id,
            "POST",
            "/search-templates/import",
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

        try:
            query_bank = (
                parse_query_bank_yaml(normalized_payload["yaml_content"])
                if normalized_payload["yaml_content"] is not None
                else normalized_payload["query_bank"]
            )
        except ValueError as exc:
            raise AppError(400, "invalid_request", str(exc), [], False) from exc

        queries = query_bank.get("queries", [])
        if not isinstance(queries, list) or not queries:
            raise AppError(400, "invalid_request", "Query bank must contain at least one query", [], False)

        global_exclude_regexes = []
        for item in query_bank.get("global_exclude_if_any_match", []):
            if isinstance(item, dict) and isinstance(item.get("regex"), str):
                global_exclude_regexes.append(item["regex"])

        results = []
        for index, query_item in enumerate(queries, start=1):
            if not isinstance(query_item, dict):
                raise AppError(400, "invalid_request", f"Query item #{index} must be an object", [], False)
            search_payload = {
                "id": query_item.get("id"),
                "intent": query_item.get("intent"),
                "cluster": query_item.get("cluster"),
                "priority": query_item.get("priority"),
                "subreddits": query_item.get("subreddits", []),
                "query": query_item.get("query"),
                "match_must_include_any": query_item.get("match_must_include_any", []),
                "exclude_if_contains": query_item.get("exclude_if_contains", []),
                "exclude_regexes": global_exclude_regexes,
                "limit": normalized_payload["limit"],
                "min_score": normalized_payload["min_score"],
                "date_from": normalized_payload["date_from"],
                "date_to": normalized_payload["date_to"],
                "include_comments": normalized_payload["include_comments"],
                "enrich": normalized_payload["enrich"],
                "idempotency_key": f"{normalized_payload['idempotency_key']}:{index}",
            }
            normalized_search_payload = validate_search_payload(search_payload)
            search_payload_hash = build_query_hash(normalized_search_payload)
            job_response = repository.create_search_job(workspace_id, normalized_search_payload, search_payload_hash)
            template_response = repository.create_search_template(
                workspace_id=workspace_id,
                name=query_item.get("intent") or query_item.get("id") or f"Query {index}",
                query_definition_id=normalized_search_payload.get("query_definition_id"),
                source_version=query_bank.get("version"),
                query_payload=normalized_search_payload,
                source_metadata={
                    "query_bank_version": query_bank.get("version"),
                    "last_updated": query_bank.get("last_updated"),
                    "default_time_filter": query_bank.get("default_time_filter"),
                    "default_sort": query_bank.get("default_sort"),
                    "scraper_cadence": query_bank.get("scraper_cadence"),
                    "author_blocklist": query_bank.get("author_blocklist"),
                },
                search_job_id=job_response["job_id"],
                schedule_enabled=normalized_payload["schedule_daily"],
                schedule_interval_hours=24 if normalized_payload["schedule_daily"] else 0,
            )
            results.append({**job_response, **template_response})

        response_body = {
            "status": "queued",
            "imported_templates": len(results),
            "templates": results,
        }
        repository.put_idempotency_record(
            workspace_id=workspace_id,
            method="POST",
            route="/search-templates/import",
            idempotency_key=normalized_payload["idempotency_key"],
            payload_hash=payload_hash,
            response_body=response_body,
            retention_hours=IDEMPOTENCY_RETENTION_HOURS,
        )
        return JSONResponse(status_code=202, content=response_body)

    @app.get(
        "/search-templates",
        response_model=TemplatesListResponse,
        tags=["templates"],
        summary="List saved search templates",
        responses=STANDARD_ERROR_RESPONSES,
    )
    async def list_search_templates(
        request: Request,
        x_workspace_id: str | None = Header(
            default=None,
            alias="X-Workspace-Id",
            description="Workspace or project isolation key.",
        ),
    ):
        workspace_id = get_workspace_id(request, x_workspace_id)
        return {"templates": app.state.repository.list_templates(workspace_id=workspace_id, limit=100)}

    @app.get(
        "/search-templates/{template_id}",
        response_model=SearchTemplateResponse,
        tags=["templates"],
        summary="Get one saved search template",
        responses=STANDARD_ERROR_RESPONSES,
    )
    async def get_search_template(
        template_id: str,
        request: Request,
        x_workspace_id: str | None = Header(
            default=None,
            alias="X-Workspace-Id",
            description="Workspace or project isolation key.",
        ),
    ):
        workspace_id = get_workspace_id(request, x_workspace_id)
        template = app.state.repository.get_template(template_id, workspace_id)
        if template is None:
            raise AppError(404, "not_found", f"Search template '{template_id}' was not found", [], False)
        return template

    @app.post(
        "/search-templates/{template_id}/run",
        response_model=TemplateRunResponse,
        status_code=202,
        tags=["templates"],
        summary="Queue an immediate run for a saved template",
        responses=STANDARD_ERROR_RESPONSES,
    )
    async def run_search_template(
        template_id: str,
        payload: RefreshRequest,
        request: Request,
        x_workspace_id: str | None = Header(
            default=None,
            alias="X-Workspace-Id",
            description="Workspace or project isolation key.",
        ),
    ):
        workspace_id = get_workspace_id(request, x_workspace_id)
        normalized_payload = validate_refresh_payload(payload.model_dump(exclude_none=True))
        repository = app.state.repository
        key = (
            workspace_id,
            "POST",
            f"/search-templates/{template_id}/run",
            normalized_payload["idempotency_key"],
        )
        payload_hash = build_query_hash({"query_mode": "template_run", "query": template_id})
        existing = repository.get_idempotency_record(*key)
        if existing is not None:
            if existing.payload_hash != payload_hash:
                raise AppError(409, "idempotency_payload_mismatch", "idempotency key was reused with a different payload", [], False)
            return JSONResponse(status_code=202, content=json.loads(existing.response_json))
        result = repository.run_template_now(template_id, workspace_id)
        if result is None:
            raise AppError(404, "not_found", f"Search template '{template_id}' was not found", [], False)
        repository.put_idempotency_record(
            workspace_id=workspace_id,
            method="POST",
            route=f"/search-templates/{template_id}/run",
            idempotency_key=normalized_payload["idempotency_key"],
            payload_hash=payload_hash,
            response_body=result,
            retention_hours=IDEMPOTENCY_RETENTION_HOURS,
        )
        return JSONResponse(status_code=202, content=result)

    @app.get(
        "/search/{job_id}",
        response_model=SearchViewResponse,
        tags=["search"],
        summary="Get search job status and matched posts",
        responses=STANDARD_ERROR_RESPONSES,
    )
    async def get_search(
        job_id: str,
        request: Request,
        x_workspace_id: str | None = Header(
            default=None,
            alias="X-Workspace-Id",
            description="Workspace or project isolation key.",
        ),
    ):
        workspace_id = get_workspace_id(request, x_workspace_id)
        result = app.state.repository.get_search_view(job_id, workspace_id)
        if result is None:
            raise AppError(404, "not_found", f"Search job '{job_id}' was not found", [], False)
        return result

    @app.get(
        "/summaries/{job_id}",
        response_model=SummaryResponse,
        tags=["insights"],
        summary="Get planning summary groups for one completed or partial job",
        responses=STANDARD_ERROR_RESPONSES,
    )
    async def get_summary(
        job_id: str,
        request: Request,
        x_workspace_id: str | None = Header(
            default=None,
            alias="X-Workspace-Id",
            description="Workspace or project isolation key.",
        ),
    ):
        workspace_id = get_workspace_id(request, x_workspace_id)
        result = app.state.repository.get_summary(workspace_id=workspace_id, job_id=job_id)
        if result is None:
            raise AppError(404, "not_found", f"Search job '{job_id}' was not found", [], False)
        return result

    @app.post(
        "/refresh/{job_id}",
        response_model=QueueResponse,
        status_code=202,
        tags=["search"],
        summary="Queue a refresh run for an existing search job",
        responses=STANDARD_ERROR_RESPONSES,
    )
    async def refresh_search(
        job_id: str,
        payload: RefreshRequest,
        request: Request,
        x_workspace_id: str | None = Header(
            default=None,
            alias="X-Workspace-Id",
            description="Workspace or project isolation key.",
        ),
    ):
        workspace_id = get_workspace_id(request, x_workspace_id)
        normalized_payload = validate_refresh_payload(payload.model_dump(exclude_none=True))
        repository = app.state.repository
        job = repository.get_job(job_id, workspace_id)
        if job is None:
            raise AppError(404, "not_found", f"Search job '{job_id}' was not found", [], False)

        payload_hash = build_query_hash(
            {
                "query_mode": job.query_mode,
                "query_definition_id": job.query_definition_id,
                "query_cluster": job.query_cluster,
                "query_priority": job.query_priority,
                "query": job.query_text,
                "subreddit": job.subreddit,
                "subreddits": app.state.repository._parse_json_list(job.subreddits_json),
                "match_must_include_any": app.state.repository._parse_json_list(job.match_must_include_any_json),
                "exclude_if_contains": app.state.repository._parse_json_list(job.exclude_if_contains_json),
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
