# Reddit Insight Collector (MVP)

Minimal FastAPI + SQLite + worker scaffold for collecting and processing Reddit insight jobs.

## What is included

- FastAPI API with request validation and stable error envelopes
- SQLite persistence through SQLAlchemy
- background worker process that consumes queued job runs
- pytest test suite for API contracts and domain rules

## Local run

### 1. Start the API

```bash
python3 -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

### 2. Start the worker

Continuous mode:

```bash
python3 -m app.worker
```

Single-cycle mode:

```bash
python3 -m app.worker --once
```

## Tests

```bash
python3 -m pytest -q
```

## Example requests

### Create a search

```bash
curl -X POST 'http://127.0.0.1:8000/search' \
  -H 'Content-Type: application/json' \
  -H 'X-Workspace-Id: test-workspace' \
  -d '{
    "query": "AI product manager",
    "subreddit": "productmanagement",
    "limit": 50,
    "min_score": 5,
    "date_from": "2025-01-01",
    "date_to": "2025-03-01",
    "include_comments": true,
    "enrich": true,
    "idempotency_key": "11111111-1111-1111-1111-111111111111"
  }'
```

### Poll a job

```bash
curl -H 'X-Workspace-Id: test-workspace' \
  'http://127.0.0.1:8000/search/<job_id>'
```

### List stored posts

```bash
curl -H 'X-Workspace-Id: test-workspace' \
  'http://127.0.0.1:8000/posts?limit=25&offset=0'
```

## Notes

- Default database file: `reddit_insight_collector.db` in the project root
- Tests use an isolated in-memory SQLite database
- The current worker is intentionally minimal: it moves queued runs to `completed` without external Reddit ingestion yet
