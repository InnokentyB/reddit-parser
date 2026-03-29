from __future__ import annotations

import argparse
import time

from app.config import default_comment_limit_per_post, default_database_url
from app.db import Base, create_engine_and_sessionmaker
from app.providers.reddit import RedditAuthError, RedditConfigurationError, RedditOAuthClient, RedditTransientError
from app.repository import Repository


def process_next(
    repository: Repository,
    reddit_client: RedditOAuthClient | object | None = None,
    *,
    comment_limit_per_post: int | None = None,
) -> bool:
    claimed = repository.claim_next_queued_run()
    if claimed is None:
        return False
    run_context = repository.load_job_for_run(claimed["run_id"])
    if run_context is None:
        return False

    comment_limit = comment_limit_per_post or default_comment_limit_per_post()
    client = reddit_client or RedditOAuthClient.from_env()
    posts_found = 0
    comments_found = 0
    downstream_failed = False
    error_code = None
    error_message = None

    try:
        posts = client.search_posts(
            query=run_context["query"],
            subreddit=run_context["subreddit"],
            limit=run_context["limit"],
            min_score=run_context["min_score"],
            date_from=run_context["date_from"],
            date_to=run_context["date_to"],
        )
        repository.upsert_posts(posts)
        repository.link_job_posts(
            job_id=run_context["job_id"],
            run_id=run_context["run_id"],
            post_ids=[post["reddit_post_id"] for post in posts],
        )
        posts_found = len(posts)

        if run_context["include_comments"]:
            for post in posts:
                try:
                    comments = client.fetch_post_comments(
                        post["reddit_post_id"],
                        comment_limit_per_post=comment_limit,
                    )
                    repository.upsert_comments(comments)
                    comments_found += len(comments)
                except Exception as exc:  # comment failures degrade to partial if posts exist
                    downstream_failed = True
                    error_code = "comments_fetch_failed"
                    error_message = str(exc)

        if downstream_failed and posts_found > 0:
            repository.mark_run_partial(
                run_context["run_id"],
                posts_found=posts_found,
                comments_found=comments_found,
                error_code=error_code or "partial_failure",
                error_message=error_message or "One or more downstream fetches failed",
            )
        else:
            repository.complete_run(
                run_context["run_id"],
                posts_found=posts_found,
                comments_found=comments_found,
            )
    except RedditTransientError as exc:
        repository.mark_run_retryable_failed(
            run_context["run_id"],
            error_code="reddit_transient_error",
            error_message=str(exc),
        )
    except (RedditConfigurationError, RedditAuthError) as exc:
        repository.mark_run_failed(
            run_context["run_id"],
            error_code="reddit_configuration_error",
            error_message=str(exc),
        )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Reddit Insight Collector worker.")
    parser.add_argument("--once", action="store_true", help="Process a single queued run and exit.")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Polling interval in seconds.")
    args = parser.parse_args()

    engine, session_factory = create_engine_and_sessionmaker(
        testing=False,
        database_url=default_database_url(),
    )
    Base.metadata.create_all(engine)
    repository = Repository(session_factory)
    reddit_client = RedditOAuthClient.from_env()

    try:
        if args.once:
            processed = process_next(repository, reddit_client)
            return 0 if processed or not processed else 1

        while True:
            processed = process_next(repository, reddit_client)
            if not processed:
                time.sleep(args.poll_interval)
    finally:
        reddit_client.close()


if __name__ == "__main__":
    raise SystemExit(main())
