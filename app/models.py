from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SearchJobModel(Base):
    __tablename__ = "search_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(255), index=True)
    query_definition_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    query_intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    query_cluster: Mapped[str | None] = mapped_column(String(128), nullable=True)
    query_priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="reddit")
    subreddits_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_must_include_any_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    exclude_if_contains_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    exclude_regexes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    query_mode: Mapped[str] = mapped_column(String(32), default="simple")
    search_template_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    query_text: Mapped[str] = mapped_column(Text)
    subreddit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    min_score: Mapped[int] = mapped_column(Integer)
    date_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    limit: Mapped[int] = mapped_column(Integer)
    include_comments: Mapped[bool] = mapped_column(Boolean)
    enrich: Mapped[bool] = mapped_column(Boolean)
    query_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32))
    active_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_reddit_fetch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class JobRunModel(Base):
    __tablename__ = "job_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("search_jobs.id"), index=True)
    trigger_type: Mapped[str] = mapped_column(String(32), default="manual")
    status: Mapped[str] = mapped_column(String(32), index=True)
    posts_found: Mapped[int] = mapped_column(Integer, default=0)
    comments_found: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobPostModel(Base):
    __tablename__ = "job_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    search_job_id: Mapped[str] = mapped_column(String(36), ForeignKey("search_jobs.id"), index=True)
    job_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("job_runs.id"), index=True)
    reddit_post_id: Mapped[str] = mapped_column(String(64), ForeignKey("posts.reddit_post_id"), index=True)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdempotencyRecordModel(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String(255), index=True)
    method: Mapped[str] = mapped_column(String(16))
    route: Mapped[str] = mapped_column(String(255))
    idempotency_key: Mapped[str] = mapped_column(String(128), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[str] = mapped_column(Text)
    retention_hours: Mapped[int] = mapped_column(Integer, default=24)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PostModel(Base):
    __tablename__ = "posts"

    reddit_post_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), default="reddit")
    post_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    subreddit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(Text, default="")
    body_text: Mapped[str] = mapped_column(Text, default="")
    body_has_link: Mapped[bool] = mapped_column(Boolean, default=False)
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    post_created_utc: Mapped[int] = mapped_column(Integer, default=0, index=True)
    fetched_at_utc: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[int] = mapped_column(Integer, default=0)
    upvote_ratio: Mapped[float | None] = mapped_column(nullable=True)
    num_comments: Mapped[int] = mapped_column(Integer, default=0)
    is_self_post: Mapped[bool] = mapped_column(Boolean, default=True)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    is_removed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_stickied: Mapped[bool] = mapped_column(Boolean, default=False)
    flair_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_query_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    contract_version: Mapped[str] = mapped_column(String(16), default="1.0")
    author_account_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    author_total_karma: Mapped[int | None] = mapped_column(Integer, nullable=True)
    author_subreddit_karma: Mapped[int | None] = mapped_column(Integer, nullable=True)
    op_replied_in_thread: Mapped[bool] = mapped_column(Boolean, default=False)
    op_reply_count: Mapped[int] = mapped_column(Integer, default=0)
    tools_mentioned_in_thread_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    competitor_mentioned_in_thread: Mapped[bool] = mapped_column(Boolean, default=False)
    previous_seturon_mention_in_thread: Mapped[bool] = mapped_column(Boolean, default=False)
    subreddit_subscribers_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subreddit_active_users_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subreddit_rules_snapshot_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_external_link_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_external_link_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_utc: Mapped[int] = mapped_column(Integer, default=0, index=True)
    permalink: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    inserted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CommentModel(Base):
    __tablename__ = "comments"

    reddit_comment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    reddit_post_id: Mapped[str] = mapped_column(String(64), ForeignKey("posts.reddit_post_id"), index=True)
    parent_comment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body_text: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[int] = mapped_column(Integer, default=0)
    created_utc: Mapped[int] = mapped_column(Integer, default=0)
    permalink: Mapped[str | None] = mapped_column(Text, nullable=True)


class SubredditSnapshotModel(Base):
    __tablename__ = "subreddit_snapshots"

    subreddit: Mapped[str] = mapped_column(String(64), primary_key=True)
    subscribers_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_users_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rules_snapshot_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    rules_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SearchTemplateModel(Base):
    __tablename__ = "search_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(Text)
    query_definition_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    query_payload_json: Mapped[str] = mapped_column(Text)
    source_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_job_id: Mapped[str] = mapped_column(String(36), index=True)
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    schedule_interval_hours: Mapped[int] = mapped_column(Integer, default=24)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
