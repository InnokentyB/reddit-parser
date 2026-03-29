# Reddit Insight Collector (MVP)

Minimal FastAPI + Postgres + worker scaffold for collecting and processing Reddit insight jobs, with a simple built-in UI.

## What is included

- FastAPI API with request validation and stable error envelopes
- Postgres persistence through SQLAlchemy
- background worker process that consumes queued job runs
- simple browser UI for creating and inspecting jobs
- pytest test suite for API contracts and domain rules

## Local run

### Docker-first local setup

Start Postgres, API, and worker together:

```bash
docker compose up --build
```

Then open:

```text
http://127.0.0.1:8000
```

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

### 3. Postgres connection for local non-Docker runs

By default, the app now expects:

```bash
export APP_DATABASE_URL=postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/reddit_insight_collector
```

If you want to point to Render later, use its Postgres connection string in `APP_DATABASE_URL`.

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

### UI

Open:

```text
http://127.0.0.1:8000/?workspace_id=test-workspace
```

### List stored posts

```bash
curl -H 'X-Workspace-Id: test-workspace' \
  'http://127.0.0.1:8000/posts?limit=25&offset=0'
```

## Notes

- Default runtime database: local Postgres on `127.0.0.1:5432`
- Tests use an isolated in-memory SQLite database
- The current worker is intentionally minimal: it moves queued runs to `completed` without external Reddit ingestion yet
- `docker-compose.yml` is intended for local development; Render should provide `APP_DATABASE_URL` from its managed Postgres instance
