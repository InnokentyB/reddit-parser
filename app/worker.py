from __future__ import annotations

import argparse
import time

from app.config import default_database_url
from app.db import Base, create_engine_and_sessionmaker
from app.repository import Repository


def process_next(repository: Repository) -> bool:
    claimed = repository.claim_next_queued_run()
    if claimed is None:
        return False
    repository.complete_run(claimed["run_id"], posts_found=0, comments_found=0)
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

    if args.once:
        processed = process_next(repository)
        return 0 if processed or not processed else 1

    while True:
        processed = process_next(repository)
        if not processed:
            time.sleep(args.poll_interval)


if __name__ == "__main__":
    raise SystemExit(main())
