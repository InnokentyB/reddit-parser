from __future__ import annotations

import argparse
import time

from app.config import default_database_schema, default_database_url
from app.db import create_engine_and_sessionmaker, initialize_database
from app.repository import Repository


def enqueue_due_templates(repository: Repository) -> int:
    return len(repository.enqueue_due_template_runs())


def main() -> int:
    parser = argparse.ArgumentParser(description="Enqueue due daily search-template runs.")
    parser.add_argument("--once", action="store_true", help="Run a single enqueue pass and exit.")
    parser.add_argument("--poll-interval", type=float, default=60.0, help="Polling interval in seconds.")
    args = parser.parse_args()

    engine, session_factory = create_engine_and_sessionmaker(
        testing=False,
        database_url=default_database_url(),
        database_schema=default_database_schema(),
    )
    initialize_database(engine, default_database_schema())
    repository = Repository(session_factory)

    if args.once:
        enqueue_due_templates(repository)
        return 0

    while True:
        enqueue_due_templates(repository)
        time.sleep(args.poll_interval)


if __name__ == "__main__":
    raise SystemExit(main())
