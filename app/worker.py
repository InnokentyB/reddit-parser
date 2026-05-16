from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone

from app.config import (
    ALLOWLIST_SUBREDDITS,
    COMPETITOR_KEYWORDS,
    CONTRACT_VERSION,
    SOURCE_INDIE_HACKERS,
    SOURCE_REDDIT,
    POST_PLATFORM,
    TOOLS_KEYWORDS,
    default_comment_limit_per_post,
    default_database_url,
    default_query_cooldown_seconds,
    default_subreddit_snapshot_ttl_days,
)
from app.db import Base, create_engine_and_sessionmaker, ensure_runtime_schema
from app.providers.indie_hackers import IndieHackersFeedClient, IndieHackersTransientError
from app.providers.reddit_factory import create_reddit_client_from_env
from app.providers.reddit import RedditAuthError, RedditConfigurationError, RedditOAuthClient, RedditTransientError
from app.repository import Repository


def process_next(
    repository: Repository,
    reddit_client: RedditOAuthClient | object | None = None,
    indie_hackers_client: IndieHackersFeedClient | object | None = None,
    *,
    comment_limit_per_post: int | None = None,
    query_cooldown_seconds: int | None = None,
    subreddit_snapshot_ttl_days: int | None = None,
) -> bool:
    claimed = repository.claim_next_queued_run()
    if claimed is None:
        return False
    run_context = repository.load_job_for_run(claimed["run_id"])
    if run_context is None:
        return False

    comment_limit = (
        comment_limit_per_post if comment_limit_per_post is not None else default_comment_limit_per_post()
    )
    cooldown_seconds = (
        query_cooldown_seconds if query_cooldown_seconds is not None else default_query_cooldown_seconds()
    )
    snapshot_ttl_days = (
        subreddit_snapshot_ttl_days
        if subreddit_snapshot_ttl_days is not None
        else default_subreddit_snapshot_ttl_days()
    )
    source = run_context.get("source", SOURCE_REDDIT)
    client = _resolve_source_client(source, reddit_client, indie_hackers_client)
    posts_found = 0
    comments_found = 0
    downstream_failed = False
    error_code = None
    error_message = None

    try:
        if repository.is_query_cooldown_active(run_context["job_id"], cooldown_seconds):
            repository.mark_run_retryable_failed(
                run_context["run_id"],
                error_code="query_cooldown_active",
                error_message=f"Query cooldown active for {cooldown_seconds} seconds",
            )
            return True

        target_subreddits = _resolve_target_subreddits(
            source,
            run_context["subreddit"],
            run_context.get("subreddits", []),
        )
        raw_posts = _search_posts_for_targets(client, run_context, target_subreddits)
        repository.touch_job_fetch_timestamp(run_context["job_id"])

        kept_posts = []
        for post in raw_posts:
            if _should_skip_post(post):
                continue
            if not _passes_query_filters(
                post,
                run_context.get("match_must_include_any", []),
                run_context.get("exclude_if_contains", []),
                run_context.get("exclude_regexes", []),
            ):
                continue
            post["platform"] = post.get("platform") or (POST_PLATFORM if source == SOURCE_REDDIT else source)
            post["contract_version"] = CONTRACT_VERSION
            post["matched_query_id"] = run_context.get("query_definition_id") or run_context["job_id"]

            author_profile = client.fetch_author_profile(post.get("author_name"), post.get("subreddit"))
            post.update(author_profile)

            subreddit = post.get("subreddit")
            if source == SOURCE_REDDIT and subreddit:
                snapshot = repository.get_subreddit_snapshot(subreddit)
                if snapshot is None or _snapshot_is_stale(snapshot.last_fetched_at, snapshot_ttl_days):
                    snapshot_payload = client.fetch_subreddit_snapshot(subreddit)
                    repository.upsert_subreddit_snapshot(snapshot_payload)
                    snapshot = repository.get_subreddit_snapshot(subreddit)
                if snapshot is not None:
                    post["subreddit_subscribers_count"] = snapshot.subscribers_count
                    post["subreddit_active_users_count"] = snapshot.active_users_count
                    post["subreddit_rules_snapshot_url"] = snapshot.rules_snapshot_url

            thread_comments = []
            if run_context["include_comments"] and source == SOURCE_REDDIT:
                try:
                    thread_comments = client.fetch_post_comments(
                        post["reddit_post_id"],
                        comment_limit_per_post=comment_limit,
                    )
                    repository.upsert_comments(thread_comments)
                    comments_found += len(thread_comments)
                except Exception as exc:
                    downstream_failed = True
                    error_code = "comments_fetch_failed"
                    error_message = str(exc)

            _enrich_post_from_thread(post, thread_comments)
            kept_posts.append(post)

        repository.upsert_posts(kept_posts)
        repository.link_job_posts(
            job_id=run_context["job_id"],
            run_id=run_context["run_id"],
            post_ids=[post["reddit_post_id"] for post in kept_posts],
        )
        posts_found = len(kept_posts)

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
    except (RedditTransientError, IndieHackersTransientError) as exc:
        repository.mark_run_retryable_failed(
            run_context["run_id"],
            error_code=f"{source}_transient_error",
            error_message=str(exc),
        )
    except (RedditConfigurationError, RedditAuthError) as exc:
        repository.mark_run_failed(
            run_context["run_id"],
            error_code="reddit_configuration_error",
            error_message=str(exc),
        )
    except ValueError as exc:
        repository.mark_run_failed(
            run_context["run_id"],
            error_code="search_policy_violation",
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
    ensure_runtime_schema(engine)
    repository = Repository(session_factory)
    reddit_client = create_reddit_client_from_env()
    indie_hackers_client = IndieHackersFeedClient()

    try:
        if args.once:
            repository.enqueue_due_template_runs()
            process_next(repository, reddit_client, indie_hackers_client)
            return 0

        while True:
            repository.enqueue_due_template_runs()
            processed = process_next(repository, reddit_client, indie_hackers_client)
            if not processed:
                time.sleep(args.poll_interval)
    finally:
        reddit_client.close()
        indie_hackers_client.close()


def _resolve_source_client(
    source: str,
    reddit_client: RedditOAuthClient | object | None,
    indie_hackers_client: IndieHackersFeedClient | object | None,
) -> object:
    if source == SOURCE_REDDIT:
        return reddit_client or create_reddit_client_from_env()
    if source == SOURCE_INDIE_HACKERS:
        return indie_hackers_client or IndieHackersFeedClient()
    raise ValueError(f"Source '{source}' is not supported")


def _resolve_target_subreddits(source: str, subreddit: str | None, subreddits: list[str] | None = None) -> list[str]:
    if source == SOURCE_INDIE_HACKERS:
        return [None]
    normalized_subreddits = [item for item in (subreddits or []) if item]
    if normalized_subreddits:
        for item in normalized_subreddits:
            if item not in ALLOWLIST_SUBREDDITS:
                raise ValueError(f"Subreddit '{item}' is not in the allow-list")
        return normalized_subreddits
    if subreddit is None:
        return sorted(ALLOWLIST_SUBREDDITS)
    if subreddit not in ALLOWLIST_SUBREDDITS:
        raise ValueError(f"Subreddit '{subreddit}' is not in the allow-list")
    return [subreddit]


def _search_posts_for_targets(client: object, run_context: dict, target_subreddits: list[str | None]) -> list[dict]:
    deduped: dict[str, dict] = {}
    for subreddit in target_subreddits:
        posts = client.search_posts(
            query=run_context["query"],
            subreddit=subreddit,
            limit=run_context["limit"],
            min_score=run_context["min_score"],
            date_from=run_context["date_from"],
            date_to=run_context["date_to"],
        )
        for post in posts:
            deduped[post["reddit_post_id"]] = post
    ordered = sorted(
        deduped.values(),
        key=lambda post: (-int(post.get("post_created_utc", post.get("created_utc", 0))), str(post["reddit_post_id"])),
    )
    return ordered[: run_context["limit"]]


def _should_skip_post(post: dict) -> bool:
    return bool(
        post.get("is_removed")
        or post.get("is_locked")
        or post.get("is_archived")
        or post.get("is_stickied")
    )


def _passes_query_filters(
    post: dict,
    match_must_include_any: list[str],
    exclude_if_contains: list[str],
    exclude_regexes: list[str],
) -> bool:
    haystack = _thread_text(post, [])
    if match_must_include_any:
        required_matches = [term.lower() for term in match_must_include_any if term]
        if required_matches and not any(term in haystack for term in required_matches):
            return False
    excluded_matches = [term.lower() for term in exclude_if_contains if term]
    if excluded_matches and any(term in haystack for term in excluded_matches):
        return False
    for pattern in exclude_regexes:
        try:
            if re.search(pattern, haystack):
                return False
        except re.error:
            continue
    return True


def _snapshot_is_stale(last_fetched_at: datetime, ttl_days: int) -> bool:
    if last_fetched_at.tzinfo is None:
        last_fetched_at = last_fetched_at.replace(tzinfo=timezone.utc)
    age_seconds = (datetime.now(timezone.utc) - last_fetched_at).total_seconds()
    return age_seconds > ttl_days * 86400


def _enrich_post_from_thread(post: dict, comments: list[dict]) -> None:
    op_author = post.get("author_name")
    op_reply_count = 0
    tools_found: set[str] = set()
    competitor_mentioned = False
    seturon_mentioned = _contains_keyword(_thread_text(post, []), {"seturon"})

    for comment in comments:
        if comment.get("author_name") == op_author:
            op_reply_count += 1
        comment_text = str(comment.get("body_text", ""))
        tools_found.update(_find_keywords(comment_text, TOOLS_KEYWORDS))
        if _contains_keyword(comment_text, COMPETITOR_KEYWORDS):
            competitor_mentioned = True
        if _contains_keyword(comment_text, {"seturon"}):
            seturon_mentioned = True

    initial_text = _thread_text(post, comments)
    tools_found.update(_find_keywords(initial_text, TOOLS_KEYWORDS))
    if _contains_keyword(initial_text, COMPETITOR_KEYWORDS):
        competitor_mentioned = True

    post["op_replied_in_thread"] = op_reply_count > 0
    post["op_reply_count"] = op_reply_count
    post["tools_mentioned_in_thread_json"] = json.dumps(sorted(tools_found)) if tools_found else None
    post["competitor_mentioned_in_thread"] = competitor_mentioned
    post["previous_seturon_mention_in_thread"] = seturon_mentioned


def _thread_text(post: dict, comments: list[dict]) -> str:
    parts = [
        str(post.get("title", "")),
        str(post.get("body_text", "")),
    ]
    parts.extend(str(comment.get("body_text", "")) for comment in comments)
    return " ".join(parts).lower()


def _find_keywords(text: str, keywords: set[str]) -> set[str]:
    lowered = text.lower()
    found = set()
    for keyword in keywords:
        if keyword.lower() in lowered:
            found.add(keyword)
    return found


def _contains_keyword(text: str, keywords: set[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


if __name__ == "__main__":
    raise SystemExit(main())
