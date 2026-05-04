from __future__ import annotations

import os
from pathlib import Path


DEFAULT_DB_FILENAME = "reddit_insight_collector.db"
DEFAULT_COMMENT_LIMIT_PER_POST = 20
DEFAULT_QUERY_COOLDOWN_SECONDS = 60
DEFAULT_SUBREDDIT_SNAPSHOT_TTL_DAYS = 7
CONTRACT_VERSION = "1.0"
POST_PLATFORM = "reddit"

ALLOWLIST_SUBREDDITS = {
    "instructionaldesign",
    "edtech",
    "elearning",
    "onlinelearning",
    "teaching",
    "cseducation",
    "highereducation",
    "coursera",
    "udemy",
    "courseware",
    "promotecorporatelearning",
    "indiehackers",
    "saas",
    "startups",
}

TOOLS_KEYWORDS = {
    "Articulate Storyline",
    "Rise",
    "Docebo",
    "Moodle",
    "Canvas",
    "360Learning",
    "TalentLMS",
    "Thinkific",
    "Teachable",
    "Coursera",
    "Udemy",
}

COMPETITOR_KEYWORDS = {
    "articulate",
    "rise",
    "docebo",
    "moodle",
    "talentlms",
    "thinkific",
    "teachable",
    "learnworlds",
}


def default_database_url() -> str:
    return os.getenv(
        "APP_DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/reddit_insight_collector",
    )


def default_comment_limit_per_post() -> int:
    return int(os.getenv("COMMENT_LIMIT_PER_POST", str(DEFAULT_COMMENT_LIMIT_PER_POST)))


def default_query_cooldown_seconds() -> int:
    return int(os.getenv("QUERY_COOLDOWN_SECONDS", str(DEFAULT_QUERY_COOLDOWN_SECONDS)))


def default_subreddit_snapshot_ttl_days() -> int:
    return int(os.getenv("SUBREDDIT_SNAPSHOT_TTL_DAYS", str(DEFAULT_SUBREDDIT_SNAPSHOT_TTL_DAYS)))
