from __future__ import annotations

import json
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app.domain.jobs import project_search_job_status
from app.models import (
    CommentModel,
    IdempotencyRecordModel,
    JobPostModel,
    JobRunModel,
    PostModel,
    SearchJobModel,
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
                "query": job.query_text,
                "subreddit": job.subreddit,
                "min_score": job.min_score,
                "date_from": job.date_from,
                "date_to": job.date_to,
                "limit": job.limit,
                "include_comments": job.include_comments,
                "enrich": job.enrich,
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
        return {
            "data": [
                {
                    "reddit_post_id": row.reddit_post_id,
                    "subreddit": row.subreddit,
                    "title": row.title,
                    "body_text": row.body_text,
                    "score": row.score,
                    "created_utc": row.created_utc,
                    "author_name": row.author_name,
                    "num_comments": row.num_comments,
                    "permalink": row.permalink,
                    "url": row.url,
                }
                for row in rows
            ],
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
                .limit(3)
            )
            comments = list(session.execute(comments_stmt).scalars())
        return {
            "reddit_post_id": post.reddit_post_id,
            "subreddit": post.subreddit,
            "title": post.title,
            "body_text": post.body_text,
            "score": post.score,
            "created_utc": post.created_utc,
            "author_name": post.author_name,
            "num_comments": post.num_comments,
            "permalink": post.permalink,
            "url": post.url,
            "comments": [
                {
                    "reddit_comment_id": comment.reddit_comment_id,
                    "author_name": comment.author_name,
                    "body_text": comment.body_text,
                    "score": comment.score,
                    "created_utc": comment.created_utc,
                    "permalink": comment.permalink,
                }
                for comment in comments
            ],
            "enrichment": None,
        }

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
                total_posts = len(posts)
                items = [
                    {
                        "reddit_post_id": post.reddit_post_id,
                        "subreddit": post.subreddit,
                        "title": post.title,
                        "body_text": post.body_text,
                        "author_name": post.author_name,
                        "score": post.score,
                        "num_comments": post.num_comments,
                        "created_utc": post.created_utc,
                        "permalink": post.permalink,
                        "url": post.url,
                    }
                    for post in posts
                ]
        latest_run_status = run.status if run is not None else "completed"
        return {
            "job_id": job.id,
            "workspace_id": job.workspace_id,
            "status": "running" if latest_run_status in {"queued", "running"} else job.status,
            "query": {
                "query_text": job.query_text,
                "subreddit": job.subreddit,
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
                    session.add(
                        PostModel(
                            reddit_post_id=payload["reddit_post_id"],
                            subreddit=payload.get("subreddit"),
                            title=payload.get("title", ""),
                            body_text=payload.get("body_text", ""),
                            author_name=payload.get("author_name"),
                            score=int(payload.get("score", 0)),
                            num_comments=int(payload.get("num_comments", 0)),
                            created_utc=int(payload.get("created_utc", 0)),
                            permalink=payload.get("permalink"),
                            url=payload.get("url"),
                        )
                    )
                else:
                    existing.subreddit = payload.get("subreddit")
                    existing.title = payload.get("title", "")
                    existing.body_text = payload.get("body_text", "")
                    existing.author_name = payload.get("author_name")
                    existing.score = int(payload.get("score", 0))
                    existing.num_comments = int(payload.get("num_comments", 0))
                    existing.created_utc = int(payload.get("created_utc", 0))
                    existing.permalink = payload.get("permalink")
                    existing.url = payload.get("url")
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
                            "query_text": job.query_text,
                            "subreddit": job.subreddit,
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
