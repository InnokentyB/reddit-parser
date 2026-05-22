# Reddit Insight Collector (MVP)

Minimal FastAPI + Postgres + worker scaffold for collecting and processing Reddit insight jobs, with a built-in UI, saved query templates, a creator-signals subservice API, and a cron-friendly scheduler entrypoint.

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

API docs are also available at:

```text
http://127.0.0.1:8000/docs
http://127.0.0.1:8000/redoc
http://127.0.0.1:8000/openapi.json
```

The repository also contains an exported OpenAPI YAML snapshot at:

```text
docs/openapi.yaml
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
export PARSER_DB_SCHEMA=parser
```

If you want to point to Railway or another hosted Postgres later, use its connection string in `APP_DATABASE_URL` or `DATABASE_URL`.


### Creator signals subservice (same monorepo)

The API now includes a separate creator-focused service mounted at `/creator-api`:

- `GET /creator-api/trends` — aggregate topic trends by subreddit
- `GET /creator-api/opportunities` — rank active threads for comment opportunities
- `GET /creator-api/me/performance?author=<name>` — summarize post performance for one author

All endpoints are workspace-scoped and use the same `X-Workspace-Id` header.

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

### Get planner-friendly insights

```bash
curl -H 'X-Workspace-Id: test-workspace' \
  'http://127.0.0.1:8000/insights?limit=25&offset=0'
```

### Get planning summary for one job

```bash
curl -H 'X-Workspace-Id: test-workspace' \
  'http://127.0.0.1:8000/summaries/<job_id>'
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
- Default Postgres schema: `parser`
- Tests use an isolated in-memory SQLite database
- `app.worker` handles Reddit ingestion and refresh runs
- `app.scheduler` is the clean cron-job entrypoint for daily template reruns
- `docker-compose.yml` is intended for local development; Railway should provide `APP_DATABASE_URL` from its managed Postgres instance
- `GET /posts`, `GET /posts/{reddit_post_id}`, `GET /insights`, and `GET /summaries/{job_id}` are workspace-scoped and require `X-Workspace-Id`

## Deploy on Railway

This repo is now ready to deploy to Railway with one shared image and three service roles:

- `api` for the public FastAPI app
- `worker` for continuous background ingestion
- `scheduler` for one-shot cron execution of due templates

The container entrypoint is:

```bash
./bin/start <role>
```

### Railway config-as-code files

Railway config-as-code applies to a single deployment at a time, not to an entire multi-service project, so this repo includes one config file per service:

- API: [railway/api.toml](/Users/innokentyb/Documents/Reddit%20scrapper/railway/api.toml:1)
- Worker: [railway/worker.toml](/Users/innokentyb/Documents/Reddit%20scrapper/railway/worker.toml:1)
- Scheduler: [railway/scheduler.toml](/Users/innokentyb/Documents/Reddit%20scrapper/railway/scheduler.toml:1)

In Railway, each service should point at the same repository, but use a different `Config as Code` path:

- `api` service: `/railway/api.toml`
- `worker` service: `/railway/worker.toml`
- `scheduler` service: `/railway/scheduler.toml`

### Recommended Railway layout

Create these services in one Railway project:

1. `postgres`
2. `api`
3. `worker`
4. `scheduler`

### 1. Provision Postgres

Add Railway PostgreSQL to the project.

The official Railway Postgres service exposes `DATABASE_URL`, which this app can consume directly or via `APP_DATABASE_URL`.

### 2. Deploy the API service

Use this repository as the source for the `api` service.

Start command:

```bash
./bin/start api
```

Healthcheck path:

```text
/health
```

Required variables:

```bash
APP_DATABASE_URL=${{Postgres.DATABASE_URL}}
PARSER_DB_SCHEMA=parser
REDDIT_PROVIDER=oauth
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
REDDIT_USER_AGENT=...
```

Notes:

- Railway injects `PORT`, and the API now listens on that port automatically.
- If you only want Indie Hackers RSS ingestion, Reddit OAuth variables are not needed for those specific jobs.
- If you want Reddit through headless browser instead of OAuth, set `REDDIT_PROVIDER=browser` and you can omit `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, and `REDDIT_USER_AGENT`.

### 3. Deploy the worker service

Create a second Railway service from the same repo.

Config path:

```text
/railway/worker.toml
```

Effective start command:

```bash
./bin/start worker
```

Required variables:

```bash
APP_DATABASE_URL=${{Postgres.DATABASE_URL}}
PARSER_DB_SCHEMA=parser
REDDIT_PROVIDER=oauth
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
REDDIT_USER_AGENT=...
```

This service should stay always on.

If you switch to browser mode instead:

```bash
APP_DATABASE_URL=${{Postgres.DATABASE_URL}}
PARSER_DB_SCHEMA=parser
REDDIT_PROVIDER=browser
REDDIT_BROWSER_HEADLESS=true
REDDIT_BROWSER_TIMEOUT_MS=20000
```

### 4. Deploy the scheduler service

Create a third Railway service from the same repo.

Config path:

```text
/railway/scheduler.toml
```

Effective start command:

```bash
./bin/start scheduler
```

Required variables:

```bash
APP_DATABASE_URL=${{Postgres.DATABASE_URL}}
PARSER_DB_SCHEMA=parser
```

The default cron schedule in the checked-in config is every 6 hours:

```text
0 */6 * * *
```

The scheduler role intentionally runs `python -m app.scheduler --once` and exits, which matches Railway Cron Job expectations.

### Reddit provider switch

The app supports two Reddit backends:

- `REDDIT_PROVIDER=oauth` for the official Reddit API
- `REDDIT_PROVIDER=browser` for headless browser collection via Playwright

Browser mode variables:

```bash
REDDIT_PROVIDER=browser
REDDIT_BROWSER_HEADLESS=true
REDDIT_BROWSER_TIMEOUT_MS=20000
REDDIT_BROWSER_USER_AGENT=Mozilla/5.0
```

OAuth mode variables:

```bash
REDDIT_PROVIDER=oauth
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
REDDIT_USER_AGENT=linux:com.yourname.redditinsight:1.0 (by /u/your_reddit_username)
```

### Smoke test after deploy

Open:

```text
https://<your-api-domain>/health
https://<your-api-domain>/docs
```

Then submit a test search:

```bash
curl -X POST 'https://<your-api-domain>/search' \
  -H 'Content-Type: application/json' \
  -H 'X-Workspace-Id: test-workspace' \
  -d '{
    "source": "indie_hackers",
    "query": "bootstrapped saas pricing",
    "limit": 10,
    "min_score": 0,
    "include_comments": false,
    "enrich": false,
    "idempotency_key": "99999999-9999-9999-9999-999999999999"
  }'
```
