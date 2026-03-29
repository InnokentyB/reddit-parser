from __future__ import annotations

import os
from pathlib import Path


DEFAULT_DB_FILENAME = "reddit_insight_collector.db"


def default_database_url() -> str:
    return os.getenv("APP_DATABASE_URL", f"sqlite+pysqlite:///{Path.cwd() / DEFAULT_DB_FILENAME}")
