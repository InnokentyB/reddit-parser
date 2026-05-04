# Reddit Insight Collector (MVP)

Minimal FastAPI + Postgres + worker scaffold for collecting and processing Reddit insight jobs, with a built-in UI, saved query templates, and a cron-friendly scheduler entrypoint.

## What is included

- FastAPI API with request validation and stable error envelopes
- Postgres persistence through SQLAlchemy
- background worker process that consumes queued job runs
- simple browser UI for creating jobs, importing YAML query banks, and running saved templates
- saved search templates with daily rerun scheduling
- separate scheduler process for cron-style template enqueueing
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

### 3. Start the scheduler

For local cron-style template scheduling:

```bash
python3 -m app.scheduler
```

Single enqueue pass:

```bash
python3 -m app.scheduler --once
```

### 4. Postgres connection for local non-Docker runs

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
    "query": "AI course authoring tools",
    "subreddit": "instructionaldesign",
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

The UI now supports:
- one-off search creation
- YAML query bank import from pasted text or a `.yaml` file
- inspecting saved templates
- running a template immediately

### List stored posts

```bash
curl -H 'X-Workspace-Id: test-workspace' \
  'http://127.0.0.1:8000/posts?limit=25&offset=0'
```

### Import a query bank as daily templates

```bash
curl -X POST 'http://127.0.0.1:8000/search-templates/import' \
  -H 'Content-Type: application/json' \
  -H 'X-Workspace-Id: test-workspace' \
  -d '{
    "yaml_content": "version: \"1.0\"\n- id: q-tooling-001\n  intent: \"Adaptive tool request\"\n  cluster: tooling_ask\n  priority: 1\n  subreddits: [instructionaldesign]\n  query: \"title:\\\"adaptive\\\"\"\n",
    "schedule_daily": true,
    "limit": 50,
    "min_score": 5,
    "include_comments": true,
    "enrich": true,
    "idempotency_key": "44444444-4444-4444-4444-444444444444"
  }'
```

### List templates

```bash
curl -H 'X-Workspace-Id: test-workspace' \
  'http://127.0.0.1:8000/search-templates'
```

### Run a template now

```bash
curl -X POST 'http://127.0.0.1:8000/search-templates/<template_id>/run' \
  -H 'Content-Type: application/json' \
  -H 'X-Workspace-Id: test-workspace' \
  -d '{"idempotency_key":"66666666-6666-6666-6666-666666666666"}'
```

## Notes

- Default runtime database: local Postgres on `127.0.0.1:5432`
- Tests use an isolated in-memory SQLite database
- `app.worker` handles Reddit ingestion and refresh runs
- `app.scheduler` is the clean Render Cron / cronjob entrypoint for daily template reruns
- `docker-compose.yml` is intended for local development; Render should provide `APP_DATABASE_URL` from its managed Postgres instance
