from __future__ import annotations


def test_project_search_job_status_from_completed_run(project_search_job_status):
    assert project_search_job_status(run_status="completed", schedule_enabled=True) == "idle"


def test_project_search_job_status_from_partial_run(project_search_job_status):
    assert project_search_job_status(run_status="partial", schedule_enabled=True) == "partial"


def test_project_search_job_status_from_failed_run(project_search_job_status):
    assert project_search_job_status(run_status="retryable_failed", schedule_enabled=True) == "error"
    assert project_search_job_status(run_status="failed", schedule_enabled=True) == "error"


def test_project_search_job_status_from_disabled_schedule(project_search_job_status):
    assert project_search_job_status(run_status="completed", schedule_enabled=False) == "paused"


def test_classify_run_outcome_returns_partial_when_usable_posts_exist(classify_run_outcome):
    outcome = classify_run_outcome(
        persisted_post_count=1,
        downstream_stage_failed=True,
        failure_is_transient=True,
        failure_is_terminal=False,
    )

    assert outcome == "partial"


def test_classify_run_outcome_returns_retryable_failed_when_nothing_usable_persisted(
    classify_run_outcome,
):
    outcome = classify_run_outcome(
        persisted_post_count=0,
        downstream_stage_failed=True,
        failure_is_transient=True,
        failure_is_terminal=False,
    )

    assert outcome == "retryable_failed"


def test_classify_run_outcome_returns_failed_for_terminal_non_retryable_failure(
    classify_run_outcome,
):
    outcome = classify_run_outcome(
        persisted_post_count=0,
        downstream_stage_failed=True,
        failure_is_transient=False,
        failure_is_terminal=True,
    )

    assert outcome == "failed"
