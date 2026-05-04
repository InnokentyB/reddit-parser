from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app.domain.comments import select_api_comments
from app.domain.jobs import project_search_job_status
from app.models import (
    CommentModel,
    IdempotencyRecordModel,
    JobPostModel,
    JobRunModel,
    PostModel,
    SearchJobModel,
    SearchTemplateModel,
    SubredditSnapshotModel,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Repository:
    def __init__(self, session_factory: sessionmaker):
        self.session_factory = session_factory

    def get_idempotency_record(
        self, workspace_id: str, method: str, route: str, idempotency_key: str
    ) -> IdempotencyRecordModel | None:
        with self.session_factory() as session:
            stmt = select(IdempotencyRecordModel).where(
                IdempotencyRecordModel.workspace_id == workspace_id,
                IdempotencyRecordModel.method == method,
                IdempotencyRecordModel.route == route,
                IdempotencyRecordModel.idempotency_key == idempotency_key,
            )
            return session.execute(stmt).scalar_one_or_none()

    def put_idempotency_record(
        self,
        workspace_id: str,
        method: str,
        route: str,
        idempotency_key: str,
        payload_hash: str,
        response_body: dict,
        retention_hours: int,
    ) -> None:
        with self.session_factory() as session:
            session.add(
                IdempotencyRecordModel(
                    workspace_id=workspace_id,
                    method=method,
                    route=route,
                    idempotency_key=idempotency_key,
                    payload_hash=payload_hash,
                    response_json=json.dumps(response_body),
                    retention_hours=retention_hours,
                )
            )
            session.commit()

    def create_search_job(self, workspace_id: str, payload: dict, payload_hash: str) -> dict:
        job_id = str(uuid4())
        run_id = str(uuid4())
        now = utcnow()
        with self.session_factory() as session:
            job = SearchJobModel(
                id=job_id,
                workspace_id=workspace_id,
                query_definition_id=payload.get("query_definition_id"),
                query_intent=payload.get("query_intent"),
                query_cluster=payload.get("query_cluster"),
                query_priority=payload.get("query_priority"),
                subreddits_json=json.dumps(payload.get("subreddits", [])),
                match_must_include_any_json=json.dumps(payload.get("match_must_include_any", [])),
                exclude_if_contains_json=json.dumps(payload.get("exclude_if_contains", [])),
                exclude_regexes_json=json.dumps(payload.get("exclude_regexes", [])),
                query_mode=payload.get("query_mode", "simple"),
                search_template_id=payload.get("search_template_id"),
                query_text=payload["query"],
                subreddit=payload["subreddit"],
                min_score=payload["min_score"],
                date_from=self._parse_optional_date(payload["date_from"]),
                date_to=self._parse_optional_date(payload["date_to"]),
                limit=payload["limit"],
                include_comments=payload["include_comments"],
                enrich=payload["enrich"],
                query_hash=payload_hash,
                status="running",
                active_run_id=run_id,
                created_at=now,
                updated_at=now,
            )
            run = JobRunModel(
                id=run_id,
                job_id=job_id,
                trigger_type="manual",
                status="queued",
                created_at=now,
            )
            session.add(job)
            session.add(run)
            session.commit()
        return {"job_id": job_id, "run_id": run_id, "status": "queued"}

    def get_job(self, job_id: str, workspace_id: str) -> SearchJobModel | None:
        with self.session_factory() as session:
            stmt = select(SearchJobModel).where(
                SearchJobModel.id == job_id,
                SearchJobModel.workspace_id == workspace_id,
            )
            return session.execute(stmt).scalar_one_or_none()

    def load_job_for_run(self, run_id: str) -> dict | None:
        with self.session_factory() as session:
            run = session.get(JobRunModel, run_id)
            if run is None:
                return None
            job = session.get(SearchJobModel, run.job_id)
            if job is None:
                return None
            return {
                "run_id": run.id,
                "job_id": job.id,
                "workspace_id": job.workspace_id,
                "query_definition_id": job.query_definition_id,
                "query_intent": job.query_intent,
                "query_cluster": job.query_cluster,
                "query_priority": job.query_priority,
                "subreddits": self._parse_json_list(job.subreddits_json),
                "match_must_include_any": self._parse_json_list(job.match_must_include_any_json),
                "exclude_if_contains": self._parse_json_list(job.exclude_if_contains_json),
                "exclude_regexes": self._parse_json_list(job.exclude_regexes_json),
                "query_mode": job.query_mode,
                "query": job.query_text,
                "subreddit": job.subreddit,
                "min_score": job.min_score,
                "date_from": job.date_from,
                "date_to": job.date_to,
                "limit": job.limit,
                "include_comments": job.include_comments,
                "enrich": job.enrich,
                "last_reddit_fetch_at": job.last_reddit_fetch_at,
            }

    def get_run(self, run_id: str | None) -> JobRunModel | None:
        if run_id is None:
            return None
        with self.session_factory() as session:
            stmt = select(JobRunModel).where(JobRunModel.id == run_id)
            return session.execute(stmt).scalar_one_or_none()

    def create_refresh_run(self, job_id: str) -> dict:
        run_id = str(uuid4())
        now = utcnow()
        with self.session_factory() as session:
            job = session.get(SearchJobModel, job_id)
            if job is None:
                raise ValueError(f"Unknown job_id: {job_id}")
            job.active_run_id = run_id
            job.status = "running"
            job.updated_at = now
            session.add(
                JobRunModel(
                    id=run_id,
                    job_id=job_id,
                    trigger_type="manual",
                    status="queued",
                    created_at=now,
                )
            )
            session.commit()
        return {"job_id": job_id, "run_id": run_id, "status": "queued"}

    def list_posts(self, limit: int, offset: int) -> dict:
        with self.session_factory() as session:
            stmt = (
                select(PostModel)
                .order_by(PostModel.created_utc.desc(), PostModel.reddit_post_id.asc())
                .limit(limit)
                .offset(offset)
            )
            rows = list(session.execute(stmt).scalars())
            comments_map = self._load_comments_map(session, [row.reddit_post_id for row in rows])
        return {
            "data": [self._serialize_post(row, comments_map.get(row.reddit_post_id, [])) for row in rows],
            "pagination": {
                "limit": limit,
                "offset": offset,
                "returned": len(rows),
                "has_more": len(rows) == limit,
            },
            "ordering": "created_utc_desc",
        }

    def get_post(self, reddit_post_id: str) -> dict | None:
        with self.session_factory() as session:
            post = session.get(PostModel, reddit_post_id)
            if post is None:
                return None
            comments_stmt = (
                select(CommentModel)
                .where(CommentModel.reddit_post_id == reddit_post_id)
                .order_by(CommentModel.score.desc(), CommentModel.created_utc.asc(), CommentModel.reddit_comment_id.asc())
            )
            comments = list(session.execute(comments_stmt).scalars())
        payload = self._serialize_post(post, comments)
        payload["comments"] = [self._serialize_comment(comment, post.author_name) for comment in comments]
        payload["enrichment"] = None
        return payload

    def get_search_view(self, job_id: str, workspace_id: str) -> dict | None:
        with self.session_factory() as session:
            job = session.execute(
                select(SearchJobModel).where(
                    SearchJobModel.id == job_id,
                    SearchJobModel.workspace_id == workspace_id,
                )
            ).scalar_one_or_none()
            if job is None:
                return None
            run = session.get(JobRunModel, job.active_run_id) if job.active_run_id else None
            items: list[dict] = []
            total_posts = 0
            if run is not None:
                post_stmt = (
                    select(PostModel)
                    .join(JobPostModel, JobPostModel.reddit_post_id == PostModel.reddit_post_id)
                    .where(JobPostModel.job_run_id == run.id)
                    .order_by(JobPostModel.matched_at.desc(), PostModel.reddit_post_id.asc())
                )
                posts = list(session.execute(post_stmt).scalars())
                comments_map = self._load_comments_map(session, [post.reddit_post_id for post in posts])
                total_posts = len(posts)
                items = [self._serialize_post(post, comments_map.get(post.reddit_post_id, [])) for post in posts]
        latest_run_status = run.status if run is not None else "completed"
        return {
            "job_id": job.id,
            "workspace_id": job.workspace_id,
            "status": "running" if latest_run_status in {"queued", "running"} else job.status,
            "query": {
                "query_definition_id": job.query_definition_id,
                "intent": job.query_intent,
                "cluster": job.query_cluster,
                "priority": job.query_priority,
                "query_mode": job.query_mode,
                "query_text": job.query_text,
                "subreddit": job.subreddit,
                "subreddits": self._parse_json_list(job.subreddits_json),
                "match_must_include_any": self._parse_json_list(job.match_must_include_any_json),
                "exclude_if_contains": self._parse_json_list(job.exclude_if_contains_json),
                "exclude_regexes": self._parse_json_list(job.exclude_regexes_json),
                "min_score": job.min_score,
                "date_from": job.date_from.isoformat() if job.date_from else None,
                "date_to": job.date_to.isoformat() if job.date_to else None,
                "limit": job.limit,
                "include_comments": job.include_comments,
                "enrich": job.enrich,
            },
            "latest_run": {
                "run_id": run.id if run else None,
                "status": latest_run_status,
                "trigger_type": run.trigger_type if run else "manual",
                "started_at": run.started_at.isoformat() if run and run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run and run.finished_at else None,
                "posts_found": run.posts_found if run else 0,
                "comments_found": run.comments_found if run else 0,
                "partial": latest_run_status == "partial",
                "error_code": run.error_code if run else None,
                "error_message": run.error_message if run else None,
            },
            "results": {
                "total_posts": total_posts,
                "returned_posts": len(items),
                "ordering": "matched_at_desc",
                "items": items,
            },
        }

    def claim_next_queued_run(self) -> dict | None:
        with self.session_factory() as session:
            stmt = select(JobRunModel).where(JobRunModel.status == "queued").order_by(JobRunModel.created_at.asc())
            run = session.execute(stmt).scalars().first()
            if run is None:
                return None
            run.status = "running"
            run.started_at = utcnow()
            job = session.get(SearchJobModel, run.job_id)
            if job is not None:
                job.status = "running"
                job.updated_at = utcnow()
            session.commit()
            return {"run_id": run.id, "job_id": run.job_id}

    def complete_run(self, run_id: str, posts_found: int = 0, comments_found: int = 0) -> None:
        now = utcnow()
        with self.session_factory() as session:
            run = session.get(JobRunModel, run_id)
            if run is None:
                return
            run.status = "completed"
            run.posts_found = posts_found
            run.comments_found = comments_found
            run.finished_at = now
            job = session.get(SearchJobModel, run.job_id)
            if job is not None:
                job.status = project_search_job_status(run.status, schedule_enabled=True)
                job.updated_at = now
            session.commit()

    def mark_run_partial(
        self,
        run_id: str,
        *,
        posts_found: int,
        comments_found: int,
        error_code: str,
        error_message: str,
    ) -> None:
        now = utcnow()
        with self.session_factory() as session:
            run = session.get(JobRunModel, run_id)
            if run is None:
                return
            run.status = "partial"
            run.posts_found = posts_found
            run.comments_found = comments_found
            run.error_code = error_code
            run.error_message = error_message
            run.finished_at = now
            job = session.get(SearchJobModel, run.job_id)
            if job is not None:
                job.status = "partial"
                job.updated_at = now
            session.commit()

    def mark_run_retryable_failed(self, run_id: str, *, error_code: str, error_message: str) -> None:
        self._mark_run_failed(run_id, "retryable_failed", error_code, error_message)

    def mark_run_failed(self, run_id: str, *, error_code: str, error_message: str) -> None:
        self._mark_run_failed(run_id, "failed", error_code, error_message)

    def upsert_posts(self, posts: list[dict]) -> None:
        if not posts:
            return
        with self.session_factory() as session:
            for payload in posts:
                existing = session.get(PostModel, payload["reddit_post_id"])
                if existing is None:
                    session.add(PostModel(**self._build_post_model_payload(payload)))
                else:
                    for field, value in self._build_post_model_payload(payload).items():
                        setattr(existing, field, value)
            session.commit()

    def upsert_comments(self, comments: list[dict]) -> None:
        if not comments:
            return
        with self.session_factory() as session:
            for payload in comments:
                existing = session.get(CommentModel, payload["reddit_comment_id"])
                if existing is None:
                    session.add(
                        CommentModel(
                            reddit_comment_id=payload["reddit_comment_id"],
                            reddit_post_id=payload["reddit_post_id"],
                            parent_comment_id=payload.get("parent_comment_id"),
                            author_name=payload.get("author_name"),
                            body_text=payload.get("body_text", ""),
                            score=int(payload.get("score", 0)),
                            created_utc=int(payload.get("created_utc", 0)),
                            permalink=payload.get("permalink"),
                        )
                    )
                else:
                    existing.reddit_post_id = payload["reddit_post_id"]
                    existing.parent_comment_id = payload.get("parent_comment_id")
                    existing.author_name = payload.get("author_name")
                    existing.body_text = payload.get("body_text", "")
                    existing.score = int(payload.get("score", 0))
                    existing.created_utc = int(payload.get("created_utc", 0))
                    existing.permalink = payload.get("permalink")
            session.commit()

    def link_job_posts(self, job_id: str, run_id: str, post_ids: list[str]) -> None:
        with self.session_factory() as session:
            session.execute(delete(JobPostModel).where(JobPostModel.job_run_id == run_id))
            for post_id in post_ids:
                session.add(JobPostModel(search_job_id=job_id, job_run_id=run_id, reddit_post_id=post_id))
            session.commit()

    def list_recent_jobs(self, workspace_id: str, limit: int = 20) -> list[dict]:
        with self.session_factory() as session:
            stmt = (
                select(SearchJobModel)
                .where(SearchJobModel.workspace_id == workspace_id)
                .order_by(SearchJobModel.created_at.desc(), SearchJobModel.id.asc())
                .limit(limit)
            )
            jobs = list(session.execute(stmt).scalars())
            results: list[dict] = []
            for job in jobs:
                run = session.get(JobRunModel, job.active_run_id) if job.active_run_id else None
                results.append(
                    {
                        "job_id": job.id,
                        "workspace_id": job.workspace_id,
                        "status": job.status,
                        "query": {
                            "query_definition_id": job.query_definition_id,
                            "intent": job.query_intent,
                            "cluster": job.query_cluster,
                            "priority": job.query_priority,
                            "query_mode": job.query_mode,
                            "query_text": job.query_text,
                            "subreddit": job.subreddit,
                            "subreddits": self._parse_json_list(job.subreddits_json),
                            "match_must_include_any": self._parse_json_list(job.match_must_include_any_json),
                            "exclude_if_contains": self._parse_json_list(job.exclude_if_contains_json),
                            "exclude_regexes": self._parse_json_list(job.exclude_regexes_json),
                            "min_score": job.min_score,
                            "date_from": job.date_from.isoformat() if job.date_from else None,
                            "date_to": job.date_to.isoformat() if job.date_to else None,
                            "limit": job.limit,
                            "include_comments": job.include_comments,
                            "enrich": job.enrich,
                        },
                        "latest_run": {
                            "run_id": run.id if run else None,
                            "status": run.status if run else "completed",
                            "posts_found": run.posts_found if run else 0,
                            "comments_found": run.comments_found if run else 0,
                        },
                    }
                )
            return results

    def is_query_cooldown_active(self, job_id: str, cooldown_seconds: int) -> bool:
        with self.session_factory() as session:
            job = session.get(SearchJobModel, job_id)
            if job is None or job.last_reddit_fetch_at is None:
                return False
            last_fetch = self._ensure_aware(job.last_reddit_fetch_at)
            return utcnow() < last_fetch + timedelta(seconds=cooldown_seconds)

    def create_search_template(
        self,
        *,
        workspace_id: str,
        name: str,
        query_definition_id: str | None,
        source_version: str | None,
        query_payload: dict,
        source_metadata: dict | None,
        search_job_id: str,
        schedule_enabled: bool,
        schedule_interval_hours: int,
    ) -> dict:
        template_id = str(uuid4())
        now = utcnow()
        next_run_at = now + timedelta(hours=schedule_interval_hours) if schedule_enabled else None
        with self.session_factory() as session:
            session.add(
                SearchTemplateModel(
                    id=template_id,
                    workspace_id=workspace_id,
                    name=name,
                    query_definition_id=query_definition_id,
                    source_version=source_version,
                    query_payload_json=json.dumps(query_payload),
                    source_metadata_json=json.dumps(source_metadata or {}),
                    search_job_id=search_job_id,
                    schedule_enabled=schedule_enabled,
                    schedule_interval_hours=schedule_interval_hours,
                    last_run_at=now,
                    next_run_at=next_run_at,
                    created_at=now,
                    updated_at=now,
                )
            )
            job = session.get(SearchJobModel, search_job_id)
            if job is not None:
                job.search_template_id = template_id
                job.updated_at = now
            session.commit()
        return {
            "template_id": template_id,
            "search_job_id": search_job_id,
            "schedule_enabled": schedule_enabled,
            "schedule_interval_hours": schedule_interval_hours,
            "next_run_at": next_run_at.isoformat() if next_run_at else None,
        }

    def list_templates(self, workspace_id: str, limit: int = 100) -> list[dict]:
        with self.session_factory() as session:
            stmt = (
                select(SearchTemplateModel)
                .where(SearchTemplateModel.workspace_id == workspace_id)
                .order_by(SearchTemplateModel.created_at.desc(), SearchTemplateModel.id.asc())
                .limit(limit)
            )
            templates = list(session.execute(stmt).scalars())
            return [self._serialize_template(row) for row in templates]

    def get_template(self, template_id: str, workspace_id: str) -> dict | None:
        with self.session_factory() as session:
            stmt = select(SearchTemplateModel).where(
                SearchTemplateModel.id == template_id,
                SearchTemplateModel.workspace_id == workspace_id,
            )
            template = session.execute(stmt).scalar_one_or_none()
            if template is None:
                return None
            return self._serialize_template(template)

    def run_template_now(self, template_id: str, workspace_id: str) -> dict | None:
        with self.session_factory() as session:
            stmt = select(SearchTemplateModel).where(
                SearchTemplateModel.id == template_id,
                SearchTemplateModel.workspace_id == workspace_id,
            )
            template = session.execute(stmt).scalar_one_or_none()
            if template is None:
                return None
            now = utcnow()
            run_id = str(uuid4())
            job = session.get(SearchJobModel, template.search_job_id)
            if job is None:
                return None
            job.active_run_id = run_id
            job.status = "running"
            job.updated_at = now
            template.last_run_at = now
            template.next_run_at = now + timedelta(hours=template.schedule_interval_hours) if template.schedule_enabled else None
            template.updated_at = now
            session.add(
                JobRunModel(
                    id=run_id,
                    job_id=template.search_job_id,
                    trigger_type="template_manual",
                    status="queued",
                    created_at=now,
                )
            )
            session.commit()
            return {"template_id": template.id, "job_id": template.search_job_id, "run_id": run_id, "status": "queued"}

    def enqueue_due_template_runs(self, now: datetime | None = None) -> list[dict]:
        current_time = now or utcnow()
        created_runs: list[dict] = []
        with self.session_factory() as session:
            stmt = select(SearchTemplateModel).where(
                SearchTemplateModel.schedule_enabled.is_(True),
                SearchTemplateModel.next_run_at.is_not(None),
                SearchTemplateModel.next_run_at <= current_time,
            )
            templates = list(session.execute(stmt).scalars())
            for template in templates:
                job = session.get(SearchJobModel, template.search_job_id)
                if job is None:
                    continue
                active_run = session.get(JobRunModel, job.active_run_id) if job.active_run_id else None
                if active_run is not None and active_run.status in {"queued", "running"}:
                    template.next_run_at = current_time + timedelta(hours=template.schedule_interval_hours)
                    template.updated_at = current_time
                    continue
                run_id = str(uuid4())
                job.active_run_id = run_id
                job.status = "running"
                job.updated_at = current_time
                template.last_run_at = current_time
                template.next_run_at = current_time + timedelta(hours=template.schedule_interval_hours)
                template.updated_at = current_time
                session.add(
                    JobRunModel(
                        id=run_id,
                        job_id=template.search_job_id,
                        trigger_type="template_daily",
                        status="queued",
                        created_at=current_time,
                    )
                )
                created_runs.append(
                    {
                        "template_id": template.id,
                        "job_id": template.search_job_id,
                        "run_id": run_id,
                        "status": "queued",
                    }
                )
            session.commit()
        return created_runs

    def touch_job_fetch_timestamp(self, job_id: str) -> None:
        with self.session_factory() as session:
            job = session.get(SearchJobModel, job_id)
            if job is None:
                return
            now = utcnow()
            job.last_reddit_fetch_at = now
            job.updated_at = now
            session.commit()

    def get_subreddit_snapshot(self, subreddit: str) -> SubredditSnapshotModel | None:
        with self.session_factory() as session:
            return session.get(SubredditSnapshotModel, subreddit)

    def upsert_subreddit_snapshot(self, payload: dict) -> None:
        subreddit = payload["subreddit"]
        with self.session_factory() as session:
            existing = session.get(SubredditSnapshotModel, subreddit)
            if existing is None:
                session.add(
                    SubredditSnapshotModel(
                        subreddit=subreddit,
                        subscribers_count=payload.get("subscribers_count"),
                        active_users_count=payload.get("active_users_count"),
                        rules_snapshot_url=payload.get("rules_snapshot_url"),
                        rules_json=payload.get("rules_json"),
                        last_fetched_at=utcnow(),
                    )
                )
            else:
                existing.subscribers_count = payload.get("subscribers_count")
                existing.active_users_count = payload.get("active_users_count")
                existing.rules_snapshot_url = payload.get("rules_snapshot_url")
                existing.rules_json = payload.get("rules_json")
                existing.last_fetched_at = utcnow()
            session.commit()

    @staticmethod
    def _parse_optional_date(value: str | None) -> date | None:
        if value is None:
            return None
        return date.fromisoformat(value)

    def _mark_run_failed(self, run_id: str, status: str, error_code: str, error_message: str) -> None:
        now = utcnow()
        with self.session_factory() as session:
            run = session.get(JobRunModel, run_id)
            if run is None:
                return
            run.status = status
            run.error_code = error_code
            run.error_message = error_message
            run.finished_at = now
            job = session.get(SearchJobModel, run.job_id)
            if job is not None:
                job.status = "error"
                job.updated_at = now
            session.commit()

    @staticmethod
    def _build_post_model_payload(payload: dict) -> dict:
        return {
            "reddit_post_id": payload["reddit_post_id"],
            "platform": payload.get("platform", "reddit"),
            "post_url": payload.get("post_url"),
            "subreddit": payload.get("subreddit"),
            "title": payload.get("title", ""),
            "body_text": payload.get("body_text", ""),
            "body_has_link": bool(payload.get("body_has_link", False)),
            "author_name": payload.get("author_name"),
            "post_created_utc": int(payload.get("post_created_utc", payload.get("created_utc", 0))),
            "fetched_at_utc": int(payload.get("fetched_at_utc", 0)),
            "score": int(payload.get("score", 0)),
            "upvote_ratio": payload.get("upvote_ratio"),
            "num_comments": int(payload.get("num_comments", 0)),
            "is_self_post": bool(payload.get("is_self_post", True)),
            "is_locked": bool(payload.get("is_locked", False)),
            "is_archived": bool(payload.get("is_archived", False)),
            "is_removed": bool(payload.get("is_removed", False)),
            "is_stickied": bool(payload.get("is_stickied", False)),
            "flair_text": payload.get("flair_text"),
            "matched_query_id": payload.get("matched_query_id"),
            "contract_version": payload.get("contract_version", "1.0"),
            "author_account_age_days": payload.get("author_account_age_days"),
            "author_total_karma": payload.get("author_total_karma"),
            "author_subreddit_karma": payload.get("author_subreddit_karma"),
            "op_replied_in_thread": bool(payload.get("op_replied_in_thread", False)),
            "op_reply_count": int(payload.get("op_reply_count", 0)),
            "tools_mentioned_in_thread_json": payload.get("tools_mentioned_in_thread_json"),
            "competitor_mentioned_in_thread": bool(payload.get("competitor_mentioned_in_thread", False)),
            "previous_seturon_mention_in_thread": bool(payload.get("previous_seturon_mention_in_thread", False)),
            "subreddit_subscribers_count": payload.get("subreddit_subscribers_count"),
            "subreddit_active_users_count": payload.get("subreddit_active_users_count"),
            "subreddit_rules_snapshot_url": payload.get("subreddit_rules_snapshot_url"),
            "post_thumbnail_url": payload.get("post_thumbnail_url"),
            "post_external_link_url": payload.get("post_external_link_url"),
            "post_external_link_domain": payload.get("post_external_link_domain"),
            "created_utc": int(payload.get("created_utc", payload.get("post_created_utc", 0))),
            "permalink": payload.get("permalink"),
            "url": payload.get("url"),
        }

    def _load_comments_map(self, session, post_ids: list[str]) -> dict[str, list[CommentModel]]:
        if not post_ids:
            return {}
        stmt = (
            select(CommentModel)
            .where(CommentModel.reddit_post_id.in_(post_ids))
            .order_by(CommentModel.score.desc(), CommentModel.created_utc.asc(), CommentModel.reddit_comment_id.asc())
        )
        rows = list(session.execute(stmt).scalars())
        comments_map: dict[str, list[CommentModel]] = {post_id: [] for post_id in post_ids}
        for row in rows:
            comments_map.setdefault(row.reddit_post_id, []).append(row)
        return comments_map

    def _serialize_post(self, post: PostModel, comments: list[CommentModel]) -> dict:
        top_comments = select_api_comments(
            [
                {
                    "reddit_comment_id": comment.reddit_comment_id,
                    "author_name": comment.author_name,
                    "body_text": comment.body_text,
                    "score": comment.score,
                    "created_utc": comment.created_utc,
                    "permalink": comment.permalink,
                }
                for comment in comments
            ]
        )
        tools_mentioned = []
        if post.tools_mentioned_in_thread_json:
            try:
                tools_mentioned = json.loads(post.tools_mentioned_in_thread_json)
            except json.JSONDecodeError:
                tools_mentioned = []
        return {
            "reddit_post_id": post.reddit_post_id,
            "post_id": post.reddit_post_id,
            "platform": post.platform,
            "post_url": post.post_url,
            "subreddit": post.subreddit,
            "title": post.title,
            "body_text": post.body_text,
            "body_has_link": post.body_has_link,
            "author_name": post.author_name,
            "author_username": post.author_name,
            "post_created_utc": post.post_created_utc,
            "fetched_at_utc": post.fetched_at_utc,
            "score": post.score,
            "upvote_ratio": post.upvote_ratio,
            "num_comments": post.num_comments,
            "is_self_post": post.is_self_post,
            "is_locked": post.is_locked,
            "is_archived": post.is_archived,
            "is_removed": post.is_removed,
            "is_stickied": post.is_stickied,
            "flair_text": post.flair_text,
            "matched_query_id": post.matched_query_id,
            "contract_version": post.contract_version,
            "author_account_age_days": post.author_account_age_days,
            "author_total_karma": post.author_total_karma,
            "author_subreddit_karma": post.author_subreddit_karma,
            "op_replied_in_thread": post.op_replied_in_thread,
            "op_reply_count": post.op_reply_count,
            "tools_mentioned_in_thread": tools_mentioned,
            "competitor_mentioned_in_thread": post.competitor_mentioned_in_thread,
            "previous_seturon_mention_in_thread": post.previous_seturon_mention_in_thread,
            "subreddit_subscribers_count": post.subreddit_subscribers_count,
            "subreddit_active_users_count": post.subreddit_active_users_count,
            "subreddit_rules_snapshot_url": post.subreddit_rules_snapshot_url,
            "post_thumbnail_url": post.post_thumbnail_url,
            "post_external_link_url": post.post_external_link_url,
            "post_external_link_domain": post.post_external_link_domain,
            "created_utc": post.created_utc,
            "permalink": post.permalink,
            "url": post.url,
            "top_3_comments": [
                {
                    "comment_id": comment["reddit_comment_id"],
                    "author_username": comment["author_name"],
                    "body_text_truncated_500": str(comment["body_text"])[:500],
                    "score": comment["score"],
                    "is_op_comment": comment["author_name"] == post.author_name,
                    "created_utc": comment["created_utc"],
                }
                for comment in top_comments
            ],
        }

    @staticmethod
    def _serialize_comment(comment: CommentModel, op_author_name: str | None) -> dict:
        return {
            "reddit_comment_id": comment.reddit_comment_id,
            "comment_id": comment.reddit_comment_id,
            "author_name": comment.author_name,
            "author_username": comment.author_name,
            "body_text": comment.body_text,
            "score": comment.score,
            "created_utc": comment.created_utc,
            "permalink": comment.permalink,
            "is_op_comment": comment.author_name == op_author_name,
        }

    @staticmethod
    def _ensure_aware(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @staticmethod
    def _parse_json_list(value: str | None) -> list[str]:
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [str(item) for item in parsed]

    def _serialize_template(self, template: SearchTemplateModel) -> dict:
        query_payload = {}
        source_metadata = {}
        try:
            query_payload = json.loads(template.query_payload_json)
        except json.JSONDecodeError:
            query_payload = {}
        if template.source_metadata_json:
            try:
                source_metadata = json.loads(template.source_metadata_json)
            except json.JSONDecodeError:
                source_metadata = {}
        return {
            "template_id": template.id,
            "name": template.name,
            "query_definition_id": template.query_definition_id,
            "source_version": template.source_version,
            "search_job_id": template.search_job_id,
            "schedule_enabled": template.schedule_enabled,
            "schedule_interval_hours": template.schedule_interval_hours,
            "last_run_at": template.last_run_at.isoformat() if template.last_run_at else None,
            "next_run_at": template.next_run_at.isoformat() if template.next_run_at else None,
            "query_payload": query_payload,
            "source_metadata": source_metadata,
        }
