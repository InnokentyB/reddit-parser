from __future__ import annotations

import os
from pathlib import Path


DEFAULT_DB_FILENAME = "reddit_insight_collector.db"


def default_database_url() -> str:
    return os.getenv(
        "APP_DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/reddit_insight_collector",
    )
