Product name

Reddit Insight Collector (MVP)

1. Product goal

Create an MVP service that collects Reddit posts and comments for specified topics, stores them in a structured form, and returns results as a list with basic filtering and enrichment.

The product must prioritize:
- reliability under partial failure;
- compliance with rate limits and platform rules;
- low risk of account/IP blocking;
- clear ownership and access boundaries for stored jobs and results;
- safe operation under retries, duplicate deliveries, and future multi-user growth.

The MVP must avoid aggressive scraping and use official or lower-risk sources first.

---

2. Problem statement

Users want to:
- search Reddit discussions by topic, keyword, subreddit, and period;
- retrieve both posts and comments in one place;
- avoid manual browsing through many threads;
- later use the collected data for research, product discovery, pain-point analysis, and content generation.

Existing scripts often fail because they:
- rely on fragile scraping;
- do not store data properly;
- do not support incremental updates;
- do not provide filtering, deduplication, or summaries;
- get blocked due to poor request strategy;
- do not handle retries, rate limits, or dependency failures safely.

---

3. MVP scope

Included in MVP
- Search Reddit by keywords.
- Optional subreddit filter.
- Fetch posts list.
- Fetch comments for matched posts.
- Store posts and comments in database.
- Deduplicate posts/comments by Reddit IDs.
- Return structured results via API.
- Basic filtering by:
  - keyword
  - subreddit
  - date range
  - score/upvotes
- Simple enrichment:
  - short summary per post
  - extraction of top comments
- Scheduler for periodic refresh.
- Logging, observability, and rate-limit protection.
- Idempotent job creation and refresh.
- Safe degraded behavior when Reddit or enrichment providers are unavailable.

Excluded from MVP
- Full UI dashboard.
- Advanced semantic search.
- Multi-source ingestion beyond Reddit.
- Proxy rotation infrastructure.
- Anti-detect browser automation.
- Full trend analytics and clustering.
- Billing and user accounts.
- Browser scraping in the default production flow.

---

4. Core use cases

UC-1. One-time topic search

User submits a keyword like "best note taking app".
System returns a list of matching posts and top comments.

UC-2. Search inside a subreddit

User searches for "cursor" only in `r/programming`.
System returns matching discussions from that subreddit.

UC-3. Historical collection refresh

System periodically reruns saved queries and updates comments/scores.

UC-4. Insight extraction

User requests a structured response with:
- post title
- subreddit
- score
- top comments
- brief summary

UC-5. Safe retry

If the client retries the same search request, the system must not create duplicate active jobs or duplicate stored records.

UC-6. Partial success

If post fetch succeeds but comment fetch or enrichment fails, the system should still return available post results with a partial status.

---

5. Functional requirements

5.1 Search input

System must accept:
- one or more keywords;
- optional subreddit;
- optional date range;
- optional limit for number of posts;
- optional minimum score;
- optional flags for `include_comments` and `enrich`;
- an idempotency key for create/refresh operations.

System must validate:
- query length of 1 to 200 UTF-8 characters after trimming;
- keyword count of 1 to 10 after normalization;
- subreddit format via allowlisted pattern;
- date range validity with a maximum span of 365 days;
- limit with a hard upper bound of 100;
- offset with a hard upper bound of 1000 on list endpoints;
- min score as an integer between 0 and 100000.

5.2 Data collection

System must:
- collect posts matching query;
- collect comments for each matched post;
- preserve Reddit identifiers;
- preserve source URL/permalink;
- store timestamps and scores;
- support incremental updates;
- track source, fetch time, and run identifier for each ingestion cycle;
- tolerate partial dependency failure without corrupting existing data.

5.3 Storage

System must store:
- search jobs;
- job runs;
- canonical posts;
- canonical comments;
- search-to-post linkage;
- refresh history;
- enrichment results.

5.4 API response

System must return a structured list with:
- post metadata;
- selected comments;
- source links;
- enrichment fields if available;
- job/run status;
- partial/degraded status when some downstream steps fail.

5.5 Enrichment

System should support:
- extracting top N comments by score;
- generating a concise summary of post + comments;
- optional tagging of topic or pain point.

Enrichment must be:
- optional;
- asynchronously executable;
- isolated from core ingestion so enrichment failure does not fail the whole job;
- bounded by cost and input-size limits.

5.6 Refresh and scheduling

System must support:
- manual run of a query;
- scheduled rerun of saved query;
- updating scores/comments for existing posts;
- jittered scheduling to avoid thundering-herd behavior;
- prevention of overlapping refresh runs for the same saved query.

5.7 Deduplication and idempotency

System must:
- avoid duplicate storage using Reddit post/comment IDs;
- avoid duplicate active jobs for the same idempotent request;
- make refreshes safe under queue redelivery and client retry;
- record retry attempts and terminal outcome explicitly.

Idempotency policy
- `idempotency_key` is mandatory for `POST /search` and `POST /refresh/{job_id}`;
- idempotency keys must be unique within the scope of `workspace_id + method + route`;
- the system must store a normalized request fingerprint for each idempotency key;
- reusing the same idempotency key with the same normalized payload within the retention window must return the original logical response;
- reusing the same idempotency key with a different normalized payload must return `409 Conflict`;
- idempotency records should be retained for 24 hours in the MVP.

5.8 Rate limiting and safety

System must:
- throttle requests to external providers;
- queue background jobs;
- log errors and external API failures;
- prefer official API first;
- cap per-workspace and global concurrency;
- reject or defer work when system capacity or source quota is exhausted.

5.9 Access control

System must:
- support ownership fields for jobs and saved searches from the MVP schema onward;
- separate client-visible reads from privileged ingestion writes;
- make resource access enforceable per job/workspace if auth is enabled later.

MVP identity handling
- MVP tests and internal callers must provide workspace identity via `X-Workspace-Id`;
- non-production environments may use a single configured default internal workspace if the header is omitted;
- production behavior must not rely on an implicit default workspace.

---

6. Non-functional requirements

Reliability
- System should tolerate partial failures of Reddit data sources.
- Failed jobs should be retryable.
- All retries must be bounded and paired with idempotent writes.

Performance
- A query for up to 100 posts should complete within a reasonable async processing window.
- API should return cached existing data quickly when possible.
- Enrichment must not block first availability of core results.

Acceptance SLA for MVP
- `POST /search` p95 response time should be under 300 ms, excluding downstream async work;
- a newly created job should be observable via `GET /search/{job_id}` within 2 seconds;
- ingestion without enrichment for searches with `limit <= 100` should complete at p95 within 60 seconds under healthy dependencies;
- ingestion with enrichment enabled for searches with `limit <= 100` should complete at p95 within 120 seconds under healthy dependencies.

Scalability
- Architecture should support scaling workers independently from API.
- Database schema should support tens/hundreds of thousands of posts/comments in MVP phase.
- The system should support workload isolation so refresh traffic does not starve interactive searches.

Maintainability
- Source adapters must be separated from business logic.
- Enrichment must be optional and replaceable.
- External provider logic must be centralized behind adapter interfaces.

Security
- Secrets must be stored in Railway environment variables or equivalent secret manager.
- DB access must be protected with RLS/service-role separation where relevant.
- Service-role credentials must not be used in client-facing paths unless strictly required.
- Inputs must be validated at all trust boundaries.
- Logs and error payloads must not leak secrets or sensitive operational data.
- unauthorized job access should return `404` rather than `403` to reduce cross-workspace resource enumeration.

Compliance / blocking risk
- System must not rely on high-frequency browser scraping.
- System must prefer compliant access patterns and caching.
- The default MVP deployment must not depend on browser scraping fallback.

Operability
- System must emit structured logs, metrics, and trace/correlation identifiers.
- Operators must be able to see queue depth, job latency, retry counts, and external dependency health.

Recovery
- Database backups/PITR must be enabled.
- Migrations must be observable and rollback-aware.
- Ingestion history must be replayable enough to rebuild derived state if needed.

---

7. Trust boundaries and assets

Primary assets
- Reddit API credentials
- Supabase credentials
- Redis credentials
- OpenAI credentials if enrichment is enabled
- saved search definitions
- job history and enrichment outputs
- canonical posts and comments

Trust boundaries
- Client to API
- API to queue/Redis
- Worker to Reddit API
- Worker to OpenAI API
- API/worker to Postgres
- operator/admin access to infra

Business invariants
- canonical posts/comments are unique by Reddit IDs;
- one saved query can have many runs;
- one Reddit post can belong to many search jobs;
- duplicate queue delivery must not create duplicate logical results;
- partial failure must not overwrite good data with null or incomplete state.

Query normalization rules
- trim leading and trailing whitespace;
- collapse internal whitespace runs to a single space;
- lowercase;
- apply Unicode NFKC normalization;
- split on whitespace into tokens;
- remove duplicate tokens while preserving first occurrence;
- preserve token order rather than sorting alphabetically;
- include normalized query text and normalized filtering fields in request fingerprints and query hashes.

---

8. Data model (revised draft)

`workspaces`
- `id`
- `name`
- `created_at`
- `updated_at`

`search_jobs`
- `id`
- `workspace_id`
- `created_by` nullable for internal MVP
- `query_text`
- `query_hash`
- `subreddit`
- `min_score`
- `date_from`
- `date_to`
- `limit`
- `include_comments`
- `enrich`
- `status` (`idle`, `running`, `partial`, `error`, `paused`)
- `schedule_enabled`
- `schedule_cron`
- `next_run_at`
- `last_run_at`
- `last_success_at`
- `last_error_code`
- `last_error_text`
- `created_at`
- `updated_at`

`job_runs`
- `id`
- `search_job_id`
- `run_number`
- `trigger_type` (`manual`, `scheduled`, `retry`)
- `source`
- `status` (`queued`, `running`, `partial`, `completed`, `retryable_failed`, `failed`, `cancelled`)
- `attempt`
- `correlation_id`
- `started_at`
- `finished_at`
- `posts_found`
- `comments_found`
- `error_code`
- `error_text`

`posts`
- `id` internal
- `reddit_post_id` unique
- `subreddit`
- `title`
- `body_text`
- `author_name`
- `score`
- `num_comments`
- `created_utc`
- `permalink`
- `url`
- `last_fetched_at`
- `source_fetched_at`
- `raw_json` optional and retention-limited
- `inserted_at`
- `updated_at`

`comments`
- `id` internal
- `reddit_comment_id` unique
- `reddit_post_id`
- `parent_comment_id`
- `author_name`
- `body_text`
- `score`
- `created_utc`
- `permalink`
- `last_fetched_at`
- `raw_json` optional and retention-limited
- `inserted_at`
- `updated_at`

`job_posts`
- `search_job_id`
- `job_run_id`
- `reddit_post_id`
- `matched_at`
- `rank`
- `match_reason`

`enrichments`
- `id`
- `reddit_post_id`
- `version`
- `summary`
- `top_comment_ids`
- `topic_label`
- `pain_points`
- `model_name`
- `status`
- `created_at`
- `updated_at`

Optional future tables
- `api_idempotency_keys`
- `audit_logs`
- `exports`

Notes
- `posts` must not contain a direct `query_id`, because one Reddit post may appear in many searches.
- Ownership and workspace scoping must live on jobs and related control-plane entities.
- Canonical Reddit entities remain shared and deduplicated.
- `search_jobs.status` reflects the latest effective operational state of the saved search:
  - latest active run maps to `running`
  - latest terminal `completed` maps to `idle`
  - latest terminal `partial` maps to `partial`
  - latest terminal `retryable_failed` or `failed` maps to `error`
  - manually disabled schedules map to `paused`

---

9. API design (MVP draft, hardened)

`POST /search`

Create and run a search.

Request:

```json
{
  "query": "AI product manager",
  "subreddit": "productmanagement",
  "limit": 50,
  "min_score": 5,
  "date_from": "2025-01-01",
  "date_to": "2026-03-01",
  "include_comments": true,
  "enrich": true,
  "idempotency_key": "client-generated-uuid"
}
```

Behavior:
- validate and normalize input;
- create or reuse an idempotent search request;
- return `202 Accepted` with job identifier;
- never perform long-running Reddit fetch synchronously in the request thread.

Normalization rules
- `subreddit` may be provided as `programming` or `r/programming`;
- subreddit values must be trimmed, lowercased, stripped of a leading `r/`, and stored in normalized form;
- valid subreddit regex for the normalized value is `^[a-z0-9][a-z0-9_]{1,20}$`.

Response:

```json
{
  "job_id": "uuid",
  "run_id": "uuid",
  "status": "queued"
}
```

`GET /search/{job_id}`

Return search/job status and aggregated results.

Response should include:
- job status
- latest run status
- partial flag
- result counts
- normalized post list
- enrichment presence/absence

Default ordering
- results must be ordered by `matched_at desc`;
- ties must be broken by `reddit_post_id asc`.

Response shape

```json
{
  "job_id": "uuid",
  "workspace_id": "uuid",
  "status": "running",
  "query": {
    "query_text": "AI product manager",
    "subreddit": "productmanagement",
    "min_score": 5,
    "date_from": "2025-01-01",
    "date_to": "2025-12-31",
    "limit": 50,
    "include_comments": true,
    "enrich": true
  },
  "latest_run": {
    "run_id": "uuid",
    "status": "partial",
    "trigger_type": "manual",
    "started_at": "2026-03-28T10:00:00Z",
    "finished_at": null,
    "posts_found": 12,
    "comments_found": 84,
    "partial": true,
    "error_code": "comments_timeout",
    "error_message": "Comment fetch timed out after partial success"
  },
  "results": {
    "total_posts": 12,
    "returned_posts": 12,
    "ordering": "matched_at_desc",
    "items": []
  }
}
```

Partial result visibility
- if usable results exist, `GET /search/{job_id}` must return them immediately even while the latest run is still `running`;
- if a run ends in `partial`, the endpoint must continue returning the partial result set together with the terminal `partial` status.

`GET /posts`

Return stored posts with filters.

Supported query params:
- `query`
- `subreddit`
- `min_score`
- `date_from`
- `date_to`
- `limit`
- `offset`

Validation rules:
- hard cap on `limit`
- bounded `offset`
- safe query parsing and normalization

Default ordering and pagination
- posts must be ordered by `created_utc desc`;
- ties must be broken by `reddit_post_id asc`;
- offset pagination is acceptable for the MVP;
- pagination must remain stable for a single response based on the documented ordering.

Response shape

```json
{
  "data": [],
  "pagination": {
    "limit": 25,
    "offset": 0,
    "returned": 25,
    "has_more": true
  },
  "ordering": "created_utc_desc"
}
```

`GET /posts/{reddit_post_id}`

Return one post with comments and enrichment.

`POST /refresh/{job_id}`

Rerun saved query.

Requirements:
- accepts idempotency key;
- must not start a second overlapping active refresh for the same job;
- should return the existing active run if one is already in progress for the same normalized request.

Error handling
- `400` for invalid input
- `404` for missing job/post
- `409` for conflicting active run when idempotency cannot be satisfied
- `429` for rate-limited clients or exhausted job quota
- `503` for degraded system capacity

Error response envelope

```json
{
  "error": {
    "code": "invalid_request",
    "message": "Human-readable summary",
    "details": [
      {
        "field": "limit",
        "code": "max_exceeded",
        "message": "limit must be less than or equal to 100"
      }
    ],
    "retryable": false,
    "request_id": "uuid"
  }
}
```

Recommended error codes
- `400`: `invalid_request`
- `409`: `idempotency_payload_mismatch`, `state_conflict`
- `429`: `rate_limited`, `quota_exceeded`
- `503`: `capacity_exhausted`, `dependency_unavailable`

---

10. Recommended source strategy

Source priority
1. Official Reddit API (primary)
2. Optional historical/secondary source adapter in a future phase
3. Browser scraping excluded from MVP default implementation

Why
- lower blocking risk;
- better maintainability;
- simpler compliance story;
- more predictable limits.

Source adapter requirements
- centralized throttling
- request timeouts
- bounded retries with exponential backoff and jitter
- dependency health tracking
- safe degraded mode on provider outage
- explicit classification of transient versus terminal provider failures

---

11. Suggested architecture for Railway + Supabase

Components
1. FastAPI backend
   - REST API
   - validation and authorization boundary
   - idempotency handling
   - job orchestration
2. Worker process
   - async search jobs
   - comment fetching
   - refresh tasks
   - canonical upserts
3. Enrichment worker
   - summarization tasks
   - optional tagging
   - isolated failure domain from ingestion
4. Supabase Postgres
   - primary relational storage
   - indexes for search and filtering
   - RLS-ready schema for control-plane tables
5. Redis / Upstash Redis
   - queue
   - rate-limit state
   - distributed locks if needed
   - short-lived cache
6. Railway Cron / scheduler
   - periodic refresh jobs
   - jittered dispatch
7. Supabase Auth (optional later)
   - not required for internal MVP
   - schema must be ownership-ready from day one

Security role separation
- API read path uses least-privileged DB role.
- Worker uses privileged write role for ingestion.
- Migration/deploy pipeline uses separate migration role.

---

12. Detailed architecture flow

Flow A. New search
1. Client sends request to FastAPI.
2. FastAPI validates input and idempotency key.
3. FastAPI creates or reuses `search_job` and opens a `job_run`.
4. FastAPI pushes job to worker queue.
5. Worker acquires run lock and calls Reddit source adapter.
6. Worker normalizes posts/comments to internal schema.
7. Worker upserts canonical posts/comments into Supabase Postgres.
8. Worker records `job_posts` linkage.
9. Worker marks run as `completed`, `partial`, or `retryable_failed`.
10. Worker optionally enqueues enrichment for changed posts only.
11. Client polls result endpoint.

Flow B. Refresh existing query
1. Scheduler triggers refresh with jitter and concurrency budget.
2. Worker loads saved query.
3. Worker prevents overlapping active run for the same job.
4. Worker reruns source adapter with throttle.
5. Worker updates existing records and inserts new ones.
6. Worker recalculates enrichment only when source content changed.

Flow C. Read results
1. Client calls `/posts` or `/search/{job_id}`.
2. FastAPI reads structured data from Postgres.
3. FastAPI returns normalized list plus job/run status.
4. If enrichment is unavailable, API returns results without blocking.

Flow D. Failure handling
1. On Reddit timeout or `429`, worker retries with bounded backoff.
2. On repeated failure, run becomes `retryable_failed`.
3. On partial comment failure, run becomes `partial` if at least one usable post was persisted.
4. On enrichment failure, ingestion remains successful and enrichment is marked failed separately.

Run outcome rules
- `partial` means at least one usable post was persisted for the run, but one or more downstream fetch stages failed, timed out, or were truncated;
- `retryable_failed` means no usable new results were persisted for the run and the failure is transient;
- `failed` means the run cannot succeed without operator or caller correction, for example invalid configuration or non-retriable validation error;
- enrichment failure alone must not downgrade a completed ingestion run.

---

13. Recommended tech stack

Backend
- Python 3.11+
- FastAPI
- httpx
- Pydantic
- SQLAlchemy or SQLModel
- Alembic

Queue / jobs
- Dramatiq, RQ, or Celery
- Redis / Upstash Redis

Database
- Supabase Postgres

Infra
- Railway for API and worker deployment
- Supabase for DB

Optional AI enrichment
- OpenAI API for summarization / tagging

Implementation guidance
- Prefer simplest queue stack that supports retries, delayed jobs, and observability cleanly.
- Keep ingestion and enrichment as separate queues or priorities.

---

14. Database and indexing recommendations

Core indexes
- `posts.reddit_post_id` unique
- `comments.reddit_comment_id` unique
- `posts.subreddit`
- `posts.created_utc`
- `posts.score`
- `comments.reddit_post_id`
- `comments.score`
- `search_jobs.workspace_id`
- `search_jobs.status`
- `search_jobs.query_hash`
- `job_runs.search_job_id`
- `job_runs.status`
- `job_runs.started_at`
- `job_posts.search_job_id`
- `job_posts.reddit_post_id`

Recommended constraints
- unique active-run guard per `search_job_id` where status is active
- foreign keys on all linkage tables
- bounded enums for run/job statuses

Optional later
- Postgres full-text search on title/body/comments
- vector embeddings for semantic search

---

15. Anti-blocking and abuse-control strategy

MVP-safe approach
- use official API credentials;
- respect rate limits;
- cache already fetched posts/comments;
- use background jobs instead of synchronous bursts;
- avoid scraping every page view live;
- refresh only changed/new posts where possible;
- add jitter between requests;
- centralize source adapter throttling;
- cap interactive and scheduled concurrency separately;
- apply per-client or per-workspace quotas.

Explicitly avoid in MVP
- large-scale anonymous scraping;
- multiple rotating fake accounts;
- heavy headless browsing;
- bypass techniques likely to violate platform terms.

---

16. Observability

System must log:
- search start/end;
- external API errors;
- number of posts/comments fetched;
- retries;
- enrichment failures;
- queue delay and job duration;
- rate-limit or quota rejections.

Structured logging requirements
- JSON logs only
- include `request_id`, `correlation_id`, `job_id`, `run_id`, and `workspace_id` where available
- redact secrets and sensitive configuration values

Minimum metrics
- queue depth
- oldest queued job age
- job completion time
- Reddit API latency/error rate
- enrichment latency/error rate
- retry count
- duplicate suppression count
- partial-result rate

Recommended
- tracing across API, worker, and DB boundaries later
- alerting on stuck jobs, high retry rates, and dependency outage signals

---

17. Security requirements

Authentication and authorization
- Even if public auth is deferred, the schema and service boundaries must support per-workspace ownership.
- Resource authorization must be enforceable per job and per workspace.
- Privileged admin/service operations must be separated from user-scoped reads.

Secrets and configuration
- Secrets must never be committed to source control.
- Secrets must be rotatable without major code changes.
- Test and production credentials must be isolated.

Input and output safety
- All external inputs must be schema-validated.
- Untrusted Reddit content must be treated as data, not trusted markup or instructions.
- Future UI/rendering layers must escape or sanitize stored content before display.
- LLM prompts must bound and delimit Reddit text to reduce prompt-injection risk.
- “selected comments” in API responses must mean the top 3 comments by score descending, then `created_utc` ascending, then `reddit_comment_id` ascending, unless an explicit future parameter changes that contract.

Data protection
- TLS in transit is required.
- Backups must be protected.
- Retention policies must be defined for raw payloads, logs, and enrichments.

Auditability
- Privileged actions and operational overrides should be auditable with actor, action, target, and outcome.

---

18. Failure handling and degraded modes

System must define behavior for:
- dependency timeout
- dependency `429`
- partial success
- duplicate delivery
- worker crash during processing
- queue backlog
- migration failure

Required behaviors
- retries must be bounded and jittered;
- duplicate delivery must be safe;
- stale or partially failed runs must not erase valid prior data;
- read APIs should return last known good data when appropriate;
- enrichment outages should degrade features, not core ingestion.
- if a running job already has usable partial results, those results should be visible immediately through `GET /search/{job_id}`.

---

19. Data retention, backup, and recovery

Retention
- define retention period for `raw_json`;
- define log retention;
- define enrichment retention/versioning policy.

Backup and recovery
- enable Postgres backups/PITR;
- rehearse restore process;
- maintain replayable job history through `job_runs`;
- ensure migrations are rollback-aware and resumable.

---

20. MVP milestones

Milestone 1 - Core ingestion
- FastAPI skeleton
- Supabase schema
- Reddit API adapter
- store posts/comments
- canonical deduplication
- idempotent search creation

Milestone 2 - Query and retrieval
- search endpoint
- list endpoints
- filters
- top comments
- partial-result semantics

Milestone 3 - Background jobs
- queue
- refresh jobs
- retry logic
- overlap prevention
- scheduler jitter and quotas

Milestone 4 - Enrichment
- summaries
- pain point extraction
- enrichment isolation and budgeting

Milestone 5 - Hardening
- structured logs and metrics
- secret separation
- retention rules
- backup and recovery validation

---

21. Success metrics for MVP

- number of successful search jobs;
- average job completion time;
- percentage of duplicate-free imports;
- refresh success rate;
- number of usable posts/comments returned per query;
- qualitative usefulness of summaries;
- retry success rate after transient failure;
- percentage of jobs completed without overlapping duplicate runs;
- rate of degraded-but-successful results versus total failed jobs.

---

22. Risks

- Reddit API limitations.
- Policy changes by Reddit.
- Historical access gaps.
- Cost increase if AI enrichment is overused.
- Queue delays if comments volume is high.
- Multi-tenant leakage risk if ownership and RLS are postponed in implementation.
- Operational blind spots if metrics/alerts are skipped.

---

23. Product direction after MVP

- saved topic monitors;
- alerts on new discussions;
- topic clustering;
- competitor mentions;
- CSV/Notion export;
- dashboard with trends;
- multi-source collection (Reddit + HN + X + forums);
- team workspaces and billing.
