from __future__ import annotations

import json
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import CommentModel, IdempotencyRecordModel, JobRunModel, PostModel, SearchJobModel


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
            "comments": [
                {
                    "reddit_comment_id": comment.reddit_comment_id,
                    "body_text": comment.body_text,
                    "score": comment.score,
                    "created_utc": comment.created_utc,
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
                "total_posts": 0,
                "returned_posts": 0,
                "ordering": "matched_at_desc",
                "items": [],
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
                job.status = "idle"
                job.updated_at = now
            session.commit()

    @staticmethod
    def _parse_optional_date(value: str | None) -> date | None:
        if value is None:
            return None
        return date.fromisoformat(value)
