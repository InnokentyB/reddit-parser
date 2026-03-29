# Reddit Insight Collector (MVP) TDD Test Plan

This document converts the current product and architecture requirements into a TDD-first plan that can guide implementation from the outside in.

Primary source:
- [requirements.md](/Users/innokentyb/Documents/Reddit%20scrapper/requirements.md)

---

## 1. Feature model

The system exposes an async search-and-ingest workflow for Reddit data:
- client creates a search job;
- API validates and queues work;
- worker fetches posts and comments from Reddit;
- system stores canonical posts/comments and job-run metadata;
- client polls job state and results;
- saved searches can be refreshed manually or by scheduler;
- enrichment is optional and must not block ingestion success.

Primary observable contracts:
- `POST /search`
- `GET /search/{job_id}`
- `GET /posts`
- `GET /posts/{reddit_post_id}`
- `POST /refresh/{job_id}`

Core invariants to protect with tests:
- canonical posts are unique by `reddit_post_id`;
- canonical comments are unique by `reddit_comment_id`;
- one Reddit post may belong to many search jobs;
- duplicate delivery and client retries must not create duplicate logical work;
- partial failure must not erase previously valid data;
- enrichment failure must not fail ingestion.

Assumptions used for planning:
- the system is async and clients poll for status;
- external providers are mocked/faked in automated tests;
- workspace ownership exists at the schema level even if user auth is added later;
- API tests should focus on externally visible behavior, not internal implementation.

---

## 2. Testability assessment

The requirements are now largely TDD-ready. Remaining gaps are narrower and mostly concern implementation details rather than core contract ambiguity:

- exact JSON schema for individual result items in `GET /search/{job_id}` and `GET /posts/{reddit_post_id}` still needs to be finalized;
- `search_jobs.status` is now defined, but the exact update timing between run completion and job-level projection should be pinned in tests;
- quota thresholds and the exact line between `429` and `503` still need operational tuning;
- retention cleanup behavior for raw payloads is specified directionally, but the cleanup trigger is not yet defined;
- local-development default workspace behavior exists, but production auth migration still needs a future contract.

The main API, validation, idempotency, status, and failure semantics are now specific enough to drive outside-in TDD safely.

---

## 3. Test phases

### Phase 1: First red-green cycle

These are the first tests to write before building the API and ingestion flow.

1. `POST /search` accepts a valid request and returns `202` with `job_id`, `run_id`, and `status=queued`.
2. `POST /search` rejects invalid payloads with `400`.
3. Repeating `POST /search` with the same idempotency key does not create duplicate logical work.
4. `GET /search/{job_id}` returns queued/running state before completion.
5. Successful worker processing stores canonical posts/comments and marks the run completed.
6. Same Reddit post found by multiple searches is stored once and linked many-to-many via job linkage.
7. Duplicate worker delivery for the same run is safe and does not duplicate data.
8. Comment-fetch failure produces a partial result rather than a total data-loss failure.
9. Enrichment failure does not fail a successful ingestion run.
10. `POST /refresh/{job_id}` creates a new run for an existing search job.

### Phase 2: Robustness and policy tests

Add these once the basic contract is passing.

1. Overlapping refresh requests return the existing active run consistently.
2. Retry after transient Reddit timeout succeeds without duplicate writes.
3. Retry after Reddit `429` follows bounded retry policy and terminal status rules.
4. `GET /posts` applies combined filters correctly.
5. `GET /posts/{reddit_post_id}` returns post, comments, and enrichment.
6. Empty-result searches complete successfully with empty results.
7. Refresh updates existing records instead of duplicating them.
8. Scheduler respects jitter and concurrency budget.
9. Ownership and wrong-workspace access are enforced correctly.
10. Query normalization rules produce stable deduplication behavior.

### Phase 3: Hardening and deferred coverage

These can follow after the core service is usable.

1. Quotas and throttling produce `429` or `503` as designed.
2. Retention behavior for raw payloads is enforced.
3. Correlation IDs flow through request, run, and logs/metrics.
4. Recovery and replay tests validate rebuild behavior from `job_runs`.
5. Migration safety tests cover schema evolution and rollback assumptions.

---

## 4. Detailed test scenarios

### A. API contract tests

#### Scenario A1
- priority: must-have
- level: API
- title: Create search job successfully
- preconditions: valid request body; provider is not called synchronously
- action: `POST /search` with valid fields and idempotency key
- expected result:
  - HTTP `202`
  - response contains non-empty `job_id`
  - response contains non-empty `run_id`
  - response contains `status=queued`
- notes: first API contract to pin

#### Scenario A2
- priority: must-have
- level: API
- title: Reject missing required search fields
- preconditions: none
- action: `POST /search` without `query`
- expected result:
  - HTTP `400`
  - response identifies missing field
- notes: split per field if API uses detailed validation errors

#### Scenario A3
- priority: must-have
- level: API
- title: Reject malformed search values
- preconditions: none
- action: `POST /search` with malformed subreddit, invalid date range, invalid `min_score`, oversized `limit`, oversized `offset`, or oversized query
- expected result:
  - HTTP `400`
  - invalid fields are rejected explicitly
- notes: convert into several tests using concrete limits from the requirements

#### Scenario A4
- priority: must-have
- level: API
- title: Reuse idempotent create request
- preconditions: successful prior `POST /search` with idempotency key
- action: repeat same request with same idempotency key
- expected result:
  - no second active logical job is created
- response returns the same logical job/run reference or equivalent idempotent response for the next 24 hours
- notes: must stay black-box and not depend on internal table count alone

#### Scenario A4b
- priority: must-have
- level: API
- title: Reusing idempotency key with different payload returns conflict
- preconditions: successful prior `POST /search` with idempotency key
- action: repeat request with same idempotency key but different normalized payload
- expected result:
  - HTTP `409`
  - error code is `idempotency_payload_mismatch`
- notes: critical guardrail against unsafe retries

#### Scenario A5
- priority: must-have
- level: API
- title: Poll search job before completion
- preconditions: queued or running job exists
- action: `GET /search/{job_id}`
- expected result:
  - HTTP `200`
- response contains current status and no fabricated terminal state
- response does not fabricate completed results
- notes: status vocabulary should be stabilized early

#### Scenario A6
- priority: must-have
- level: API
- title: Refresh existing search job successfully
- preconditions: existing search job with no active run
- action: `POST /refresh/{job_id}` with valid idempotency key
- expected result:
  - HTTP `202`
  - new run is created or queued
  - run is associated with existing search job
- notes: core refresh contract

#### Scenario A7
- priority: should-have
- level: API
- title: Overlapping refresh request is handled predictably
- preconditions: search job already has an active refresh run
- action: call `POST /refresh/{job_id}` again for the same normalized request while a run is active
- expected result:
  - HTTP `202`
  - response returns the existing active run
- notes: overlap is resolved by reuse, not by conflict, unless the idempotency payload mismatches

#### Scenario A8
- priority: should-have
- level: API
- title: Return empty completed results for valid no-match search
- preconditions: provider fake returns no posts
- action: create and process search, then `GET /search/{job_id}`
- expected result:
  - terminal success state
  - empty result list
  - counts equal zero
- notes: empty is not an error

#### Scenario A9
- priority: should-have
- level: API
- title: List posts with combined filters
- preconditions: stored posts cover multiple subreddits, scores, and dates
- action: `GET /posts` with multiple filters
- expected result:
  - only matching posts are returned
  - non-matching posts are excluded
- notes: assert default ordering `created_utc desc`, tie-break `reddit_post_id asc`

#### Scenario A10
- priority: should-have
- level: API
- title: Get single post with comments and enrichment
- preconditions: canonical post exists with comments and enrichment
- action: `GET /posts/{reddit_post_id}`
- expected result:
  - HTTP `200`
  - includes post metadata
  - includes selected comments
  - includes enrichment if available
- notes: selected comments means top 3 by score desc, then `created_utc` asc, then `reddit_comment_id` asc

### B. Ingestion and persistence tests

#### Scenario B1
- priority: must-have
- level: integration
- title: Successful ingestion stores canonical entities
- preconditions: queued run; Reddit adapter fake returns posts and comments
- action: execute worker for the run
- expected result:
  - canonical posts are upserted
  - canonical comments are upserted
  - job-to-post links are created
  - run becomes `completed`
- notes: most important integration test

#### Scenario B2
- priority: must-have
- level: integration
- title: Same Reddit post matched by multiple searches is stored once
- preconditions: two jobs return overlapping post IDs
- action: process both jobs
- expected result:
  - exactly one canonical post per Reddit ID
  - linkage exists for both jobs
- notes: validates many-to-many model

#### Scenario B3
- priority: must-have
- level: integration
- title: Duplicate worker delivery is idempotent
- preconditions: same run is delivered twice
- action: execute worker twice for the same run
- expected result:
  - no duplicate canonical entities
  - no duplicate linkage rows
  - final run state remains valid
- notes: queue safety invariant

#### Scenario B4
- priority: should-have
- level: integration
- title: Refresh updates scores and comments incrementally
- preconditions: post and comments already stored
- action: process refresh with changed score and additional comments
- expected result:
  - existing canonical rows updated
  - new comments inserted
  - unchanged rows not duplicated
- notes: key incremental update path

#### Scenario B5
- priority: should-have
- level: integration
- title: Partial data fetch does not erase good existing data
- preconditions: post already stored from successful earlier run
- action: later refresh returns incomplete provider data or partial failure
- expected result:
  - existing valid data remains intact
  - run reflects partial or retryable failure
- notes: protects against destructive partial updates

### C. Failure and resilience tests

#### Scenario C1
- priority: must-have
- level: integration
- title: Comment fetch failure produces partial run
- preconditions: post fetch succeeds; comment fetch fails
- action: process run
- expected result:
  - posts are stored
  - available comments are stored if any
  - run status is `partial`
  - `GET /search/{job_id}` exposes partial state
- notes: core degraded-mode behavior; partial requires at least one usable persisted post

#### Scenario C2
- priority: must-have
- level: integration
- title: Enrichment failure leaves ingestion successful
- preconditions: ingestion succeeds; enrichment provider fails
- action: execute ingestion and then enrichment
- expected result:
  - ingestion status stays successful
  - enrichment is absent or marked failed
  - core API results remain available
- notes: failure isolation

#### Scenario C3
- priority: must-have
- level: integration
- title: Timeout from Reddit is retried safely
- preconditions: first adapter call times out, retry succeeds
- action: process run with retry policy active
- expected result:
  - bounded retry occurs
  - final status is successful
  - no duplicate writes occur
- notes: test with fake clock if backoff matters

#### Scenario C4
- priority: should-have
- level: integration
- title: Repeated Reddit `429` leads to retryable failure
- preconditions: adapter repeatedly returns rate-limit response
- action: process run
- expected result:
  - retries stop at configured bound
  - run ends in `retryable_failed` or equivalent terminal state
  - data is not partially corrupted
- notes: use `retryable_failed` when no usable results were persisted

#### Scenario C5
- priority: should-have
- level: integration
- title: Worker crash during processing does not create corrupt duplicate state on replay
- preconditions: run starts, some writes succeed, worker stops unexpectedly
- action: re-run same job after recovery
- expected result:
  - recovery is idempotent
  - final data is correct
  - run history is coherent
- notes: high-value regression test

### D. State transition tests

#### Scenario D1
- priority: must-have
- level: service
- title: Valid run lifecycle transitions
- preconditions: run exists in each start state
- action: apply lifecycle transitions
- expected result:
  - allowed transitions succeed
  - invalid transitions are rejected
- notes: assert `search_jobs.status` projection as well once run transitions are applied

#### Scenario D2
- priority: should-have
- level: service
- title: Search job lifecycle tracks latest run outcome correctly
- preconditions: job has multiple runs with different outcomes
- action: apply sequential run completions
- expected result:
  - job-level status fields update consistently
  - timestamps and last-error fields reflect latest relevant run
- notes: needed once `search_jobs.status` is finalized

### E. Permission and ownership tests

#### Scenario E1
- priority: should-have
- level: API
- title: Wrong workspace cannot fetch another workspace job
- preconditions: job exists in workspace A
- action: caller from workspace B requests `GET /search/{job_id}`
- expected result:
  - HTTP `404`
- notes: existence should not be disclosed across workspaces

#### Scenario E2
- priority: should-have
- level: API
- title: Wrong workspace cannot refresh another workspace job
- preconditions: job exists in workspace A
- action: caller from workspace B requests `POST /refresh/{job_id}`
- expected result:
  - HTTP `404`
- notes: important once auth is added

### G. Ordering, normalization, and schema tests

#### Scenario G1
- priority: must-have
- level: service
- title: Query normalization produces stable query hash
- preconditions: semantically equivalent queries with casing and whitespace differences
- action: normalize and hash requests
- expected result:
  - equivalent normalized requests produce identical fingerprint and query hash
  - different filter values produce different fingerprint and query hash
- notes: token order must be preserved while duplicate tokens are removed

#### Scenario G2
- priority: should-have
- level: API
- title: `GET /search/{job_id}` returns partial results immediately when available
- preconditions: running job has already persisted some posts but not finished comment fetch
- action: call `GET /search/{job_id}`
- expected result:
  - HTTP `200`
  - `latest_run.status` is `running` or `partial` per timing
  - results array contains usable persisted posts
- notes: critical for observable degraded-mode behavior

#### Scenario G3
- priority: should-have
- level: API
- title: `GET /search/{job_id}` orders result items by `matched_at desc` with stable tie-break
- preconditions: multiple matched posts with same and different `matched_at` values
- action: call `GET /search/{job_id}`
- expected result:
  - ordering is `matched_at desc`
  - ties resolve by `reddit_post_id asc`
- notes: keeps clients and snapshots deterministic

#### Scenario G4
- priority: should-have
- level: API
- title: Error responses use the standard envelope
- preconditions: invalid request, idempotency conflict, quota exhaustion, or dependency outage
- action: trigger `400`, `409`, `429`, and `503`
- expected result:
  - each response uses the `error.code`, `error.message`, `error.details`, `error.retryable`, `error.request_id` envelope
- notes: should be contract-tested once shared error handling exists

### F. Scheduling and quota tests

#### Scenario F1
- priority: should-have
- level: integration
- title: Scheduler does not dispatch overlapping runs for same search job
- preconditions: scheduled search already active
- action: scheduler tick occurs again
- expected result:
  - no second active run is created
- notes: complements refresh overlap test

#### Scenario F2
- priority: should-have
- level: integration
- title: Scheduler respects concurrency budget
- preconditions: many due jobs exceed allowed parallelism
- action: scheduler dispatches due work
- expected result:
  - only allowed number are dispatched
  - remaining jobs stay pending/deferred
- notes: depends on scheduling implementation

#### Scenario F3
- priority: nice-to-have
- level: API
- title: Create search is rejected when quota is exhausted
- preconditions: workspace/client is already at configured quota
- action: `POST /search`
- expected result:
  - HTTP `429` or `503`, per final policy
- notes: policy question remains

---

## 5. First red-green tests for FastAPI

These are the first concrete tests worth writing before implementation starts.

### Test 1
- title: `POST /search returns 202 and queue metadata for valid request`
- why first: pins the main API boundary and request contract

### Test 2
- title: `POST /search rejects invalid request body with 400`
- why second: forces schema validation before business logic spreads

### Test 3
- title: `POST /search with same idempotency key is safe to retry`
- why third: prevents a major architectural regression early

### Test 4
- title: `GET /search/{job_id} returns non-terminal state before worker completion`
- why fourth: locks async behavior and status polling contract

### Test 5
- title: `worker persists canonical posts/comments and completes run`
- why fifth: establishes the ingestion happy path

### Test 6
- title: `duplicate worker delivery does not duplicate stored entities`
- why sixth: hardens queue processing before complexity grows

### Test 7
- title: `comment fetch failure yields partial run with usable post results`
- why seventh: proves graceful degradation early

### Test 8
- title: `enrichment failure does not fail ingestion result`
- why eighth: keeps async boundaries clean

### Test 9
- title: `POST /refresh/{job_id} creates a new run for an existing job`
- why ninth: extends the lifecycle safely

### Test 10
- title: `overlapping refresh does not create a second active run`
- why tenth: closes a major race condition

---

## 6. Open questions before implementation

### Input and validation

- Validation is now fixed as:
  - `query`: 1..200 chars after trim
  - normalized keyword count: 1..10
  - date span: up to 365 days
  - `limit`: 1..100
  - `offset`: 0..1000
  - `min_score`: 0..100000
  - normalized subreddit regex: `^[a-z0-9][a-z0-9_]{1,20}$`

### Idempotency

- `idempotency_key` is mandatory for create and refresh.
- Same key plus different normalized payload returns `409` with `idempotency_payload_mismatch`.
- Retention window is 24 hours.
- Scope is `workspace_id + method + route`.

### Status and lifecycle

- `search_jobs.status`: `idle`, `running`, `partial`, `error`, `paused`
- `job_runs.status`: `queued`, `running`, `partial`, `completed`, `retryable_failed`, `failed`, `cancelled`
- `partial` requires at least one usable persisted post with some downstream failure or truncation.
- `retryable_failed` means no usable persisted results and a transient failure.
- Partial results become visible immediately once usable data exists.

### API contract

- `GET /search/{job_id}` and `GET /posts` now have baseline response envelopes in the requirements.
- Default sort for `GET /search/{job_id}` is `matched_at desc`, tie-break `reddit_post_id asc`.
- Default sort for `GET /posts` is `created_utc desc`, tie-break `reddit_post_id asc`.
- MVP pagination is offset-based.
- “selected comments” means top 3 comments by score desc, then `created_utc` asc, then `reddit_comment_id` asc.

### Ownership and authorization

- Workspace identity in MVP tests is provided via `X-Workspace-Id`.
- Unauthorized resource access returns `404`.
- Canonical post visibility still needs a future product decision if external multi-tenant reads are introduced.

### Failure policy

- Overlapping refresh returns the existing active run for the same normalized request.
- Transient upstream failures retry silently until bounded retry exhaustion.
- Capacity-handling policy between queueing and rejection still needs operational tuning.
- Acceptance SLA is now:
  - `POST /search` p95 under 300 ms
  - job visible within 2 seconds
  - ingestion without enrichment p95 under 60 seconds
  - ingestion with enrichment p95 under 120 seconds

---

## 7. Suggested implementation order

1. API schema validation for `POST /search`
2. idempotent job creation
3. `GET /search/{job_id}` polling contract
4. worker happy path for canonical ingestion
5. deduplication and duplicate-delivery safety
6. partial-result handling
7. refresh flow
8. filter/read endpoints
9. scheduler behavior
10. ownership and quota enforcement

---

## 8. Exit criteria for TDD readiness

Implementation can start cleanly once these are fixed:
- response schemas for `GET /search/{job_id}` and `GET /posts` are defined;
- validation limits are concrete;
- idempotency conflict rules are decided;
- refresh overlap behavior is decided;
- job and run status transitions are finalized.

At that point, the Phase 1 tests above should be sufficient to drive the first implementation cycle.
