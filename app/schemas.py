from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SchemaBase(BaseModel):
    model_config = ConfigDict(extra="allow")


class ErrorDetail(SchemaBase):
    field: str | None = None
    code: str
    message: str


class ErrorBody(SchemaBase):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)
    retryable: bool
    request_id: str


class ErrorResponse(SchemaBase):
    error: ErrorBody


class HealthResponse(SchemaBase):
    status: Literal["ok"]


class SearchRequest(SchemaBase):
    query: str | None = Field(default=None, examples=["AI course authoring tools"])
    subreddit: str | None = Field(default=None, examples=["instructionaldesign"])
    subreddits: list[str] | None = Field(default=None, examples=[["instructionaldesign", "edtech"]])
    id: str | None = Field(default=None, description="Structured query definition id")
    intent: str | None = None
    cluster: str | None = None
    priority: int | None = None
    match_must_include_any: list[str] | None = None
    exclude_if_contains: list[str] | None = None
    exclude_regexes: list[str] | None = None
    limit: int = 25
    min_score: int = 0
    date_from: str | None = None
    date_to: str | None = None
    include_comments: bool = False
    enrich: bool = False
    idempotency_key: str | None = Field(
        default=None,
        examples=["11111111-1111-1111-1111-111111111111"],
    )


class RefreshRequest(SchemaBase):
    idempotency_key: str | None = None


class TemplateImportRequest(SchemaBase):
    yaml_content: str | None = None
    query_bank: dict[str, Any] | None = None
    schedule_daily: bool = True
    limit: int = 50
    min_score: int = 0
    date_from: str | None = None
    date_to: str | None = None
    include_comments: bool = True
    enrich: bool = True
    idempotency_key: str | None = None


class QueueResponse(SchemaBase):
    job_id: str
    run_id: str
    status: Literal["queued"]


class TopCommentResponse(SchemaBase):
    comment_id: str
    author_username: str | None = None
    body_text_truncated_500: str
    score: int
    is_op_comment: bool
    created_utc: int


class CommentResponse(SchemaBase):
    reddit_comment_id: str
    comment_id: str
    reddit_post_id: str
    parent_id: str | None = None
    author_name: str | None = None
    author_username: str | None = None
    body: str
    body_text: str
    created_at: int
    created_utc: int
    score: int
    permalink: str | None = None
    is_op_comment: bool


class PostResponse(SchemaBase):
    reddit_post_id: str
    post_id: str
    workspace_id: str | None = None
    subreddit: str | None = None
    title: str
    body: str
    body_text: str
    author_name: str | None = None
    created_at: int
    created_utc: int
    score: int
    num_comments: int
    permalink: str | None = None
    url: str | None = None
    is_removed: bool
    is_locked: bool
    is_archived: bool
    matched_query_id: str | None = None
    flair: str | None = None
    external_links: list[str] = Field(default_factory=list)
    top_3_comments: list[TopCommentResponse] = Field(default_factory=list)


class PostDetailResponse(PostResponse):
    comments: list[CommentResponse] = Field(default_factory=list)
    enrichment: dict[str, Any] | None = None


class PaginationResponse(SchemaBase):
    limit: int
    offset: int
    returned: int
    has_more: bool


class PostsListResponse(SchemaBase):
    data: list[PostResponse]
    pagination: PaginationResponse
    ordering: str


class LatestRunResponse(SchemaBase):
    run_id: str | None = None
    status: str
    trigger_type: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    posts_found: int
    comments_found: int
    partial: bool | None = None
    error_code: str | None = None
    error_message: str | None = None


class SearchQueryResponse(SchemaBase):
    query_definition_id: str | None = None
    intent: str | None = None
    cluster: str | None = None
    priority: int | None = None
    query_mode: str
    query_text: str
    subreddit: str | None = None
    subreddits: list[str] = Field(default_factory=list)
    match_must_include_any: list[str] = Field(default_factory=list)
    exclude_if_contains: list[str] = Field(default_factory=list)
    exclude_regexes: list[str] = Field(default_factory=list)
    min_score: int
    date_from: str | None = None
    date_to: str | None = None
    limit: int
    include_comments: bool
    enrich: bool


class SearchResultsResponse(SchemaBase):
    total_posts: int
    returned_posts: int
    ordering: str
    items: list[PostResponse] = Field(default_factory=list)


class SearchViewResponse(SchemaBase):
    job_id: str
    workspace_id: str
    status: str
    query: SearchQueryResponse
    latest_run: LatestRunResponse
    results: SearchResultsResponse


class InsightResponse(SchemaBase):
    insight_id: str
    type: str
    title: str
    summary: str
    evidence_count: int
    sample_quotes: list[str] = Field(default_factory=list)
    source_post_ids: list[str] = Field(default_factory=list)
    source_comment_ids: list[str] = Field(default_factory=list)
    subreddits: list[str] = Field(default_factory=list)
    first_seen_at: int | None = None
    last_seen_at: int | None = None
    confidence: float
    priority: int


class InsightGroupsResponse(SchemaBase):
    topic_candidates: list[InsightResponse] = Field(default_factory=list)
    pain_points: list[InsightResponse] = Field(default_factory=list)
    questions_people_ask: list[InsightResponse] = Field(default_factory=list)
    objections: list[InsightResponse] = Field(default_factory=list)
    competitor_mentions: list[InsightResponse] = Field(default_factory=list)
    language_patterns: list[InsightResponse] = Field(default_factory=list)
    content_opportunities: list[InsightResponse] = Field(default_factory=list)


class InsightsResponse(SchemaBase):
    data: list[InsightResponse] = Field(default_factory=list)
    groups: InsightGroupsResponse
    pagination: PaginationResponse
    ordering: str


class SummaryResponse(SchemaBase):
    job_id: str
    workspace_id: str
    status: str
    latest_run: LatestRunResponse
    generated_from_posts: int
    groups: InsightGroupsResponse


class TemplateResponse(SchemaBase):
    template_id: str
    name: str
    query_definition_id: str | None = None
    source_version: str | None = None
    search_job_id: str
    schedule_enabled: bool
    schedule_interval_hours: int
    last_run_at: str | None = None
    next_run_at: str | None = None
    query_payload: dict[str, Any] = Field(default_factory=dict)
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class TemplatesListResponse(SchemaBase):
    templates: list[TemplateResponse]


class TemplateRunResponse(SchemaBase):
    template_id: str
    job_id: str
    run_id: str
    status: Literal["queued"]


class TemplateImportItemResponse(QueueResponse):
    template_id: str
    search_job_id: str
    schedule_enabled: bool
    schedule_interval_hours: int
    next_run_at: str | None = None


class TemplateImportResponse(SchemaBase):
    status: Literal["queued"]
    imported_templates: int
    templates: list[TemplateImportItemResponse]


class UiJobsResponse(SchemaBase):
    jobs: list[dict[str, Any]]


class UiTemplatesResponse(SchemaBase):
    templates: list[TemplateResponse]
