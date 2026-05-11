from __future__ import annotations

from collections import defaultdict

from fastapi import FastAPI, Header, Query, Request

from app.errors import AppError, create_error_response
from app.schemas import ErrorResponse

STANDARD_ERROR_RESPONSES = {
    400: {"model": ErrorResponse, "description": "Validation error"},
    404: {"model": ErrorResponse, "description": "Resource not found"},
    409: {"model": ErrorResponse, "description": "Idempotency or state conflict"},
    429: {"model": ErrorResponse, "description": "Rate limited"},
    503: {"model": ErrorResponse, "description": "Dependency or capacity issue"},
}
from app.repository import Repository
from app.schemas import CreatorOpportunitiesResponse, CreatorPerformanceResponse, CreatorTrendsResponse, ErrorResponse


def _workspace(request: Request, x_workspace_id: str | None) -> str:
    if x_workspace_id:
        return x_workspace_id
    if request.app.state.testing:
        return "internal-test-workspace"
    raise AppError(400, "invalid_request", "Request validation failed", [{"field": "X-Workspace-Id", "code": "required", "message": "X-Workspace-Id header is required"}], False)


def create_creator_app(repository: Repository, testing: bool = False) -> FastAPI:
    app = FastAPI(
        title="Creator Signals API",
        version="0.1.0",
        summary="Content trend and engagement signals service.",
    )
    app.state.testing = testing
    app.state.repository = repository

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        request_id = getattr(request.state, "request_id", "creator-api")
        return create_error_response(
            request_id=request_id,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
            retryable=exc.retryable,
        )

    @app.get("/trends", response_model=CreatorTrendsResponse, responses=STANDARD_ERROR_RESPONSES)
    async def trends(
        request: Request,
        limit: int = Query(10, ge=1, le=100),
        x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    ):
        workspace_id = _workspace(request, x_workspace_id)
        posts = app.state.repository.list_posts(limit=500, offset=0, workspace_id=workspace_id)["data"]
        buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"posts": 0, "score": 0, "comments": 0})
        for post in posts:
            topic = post.get("subreddit") or "unknown"
            buckets[topic]["posts"] += 1
            buckets[topic]["score"] += int(post.get("score", 0))
            buckets[topic]["comments"] += int(post.get("num_comments", 0))

        items = [
            {
                "topic": topic,
                "posts": values["posts"],
                "avg_score": round(values["score"] / values["posts"], 2) if values["posts"] else 0.0,
                "avg_comments": round(values["comments"] / values["posts"], 2) if values["posts"] else 0.0,
                "trend_score": values["score"] + values["comments"] * 2,
            }
            for topic, values in buckets.items()
        ]
        items.sort(key=lambda i: i["trend_score"], reverse=True)
        return {"data": items[:limit]}

    @app.get("/opportunities", response_model=CreatorOpportunitiesResponse, responses=STANDARD_ERROR_RESPONSES)
    async def opportunities(
        request: Request,
        limit: int = Query(10, ge=1, le=100),
        x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    ):
        workspace_id = _workspace(request, x_workspace_id)
        posts = app.state.repository.list_posts(limit=200, offset=0, workspace_id=workspace_id)["data"]
        sorted_posts = sorted(posts, key=lambda p: (int(p.get("num_comments", 0)) * 3 + int(p.get("score", 0))), reverse=True)
        return {
            "data": [
                {
                    "reddit_post_id": post["reddit_post_id"],
                    "title": post["title"],
                    "subreddit": post.get("subreddit"),
                    "score": post.get("score", 0),
                    "num_comments": post.get("num_comments", 0),
                    "opportunity_score": int(post.get("num_comments", 0)) * 3 + int(post.get("score", 0)),
                }
                for post in sorted_posts[:limit]
            ]
        }

    @app.get("/me/performance", response_model=CreatorPerformanceResponse, responses=STANDARD_ERROR_RESPONSES)
    async def my_performance(
        request: Request,
        author: str = Query(..., min_length=1),
        x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    ):
        workspace_id = _workspace(request, x_workspace_id)
        posts = app.state.repository.list_posts(limit=500, offset=0, workspace_id=workspace_id)["data"]
        mine = [p for p in posts if (p.get("author_name") or "").lower() == author.lower()]
        total_posts = len(mine)
        total_score = sum(int(p.get("score", 0)) for p in mine)
        total_comments = sum(int(p.get("num_comments", 0)) for p in mine)
        return {
            "author": author,
            "total_posts": total_posts,
            "total_score": total_score,
            "total_comments": total_comments,
            "avg_score": round(total_score / total_posts, 2) if total_posts else 0.0,
            "avg_comments": round(total_comments / total_posts, 2) if total_posts else 0.0,
        }

    return app
