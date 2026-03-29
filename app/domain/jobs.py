from __future__ import annotations


def project_search_job_status(run_status: str, schedule_enabled: bool) -> str:
    if not schedule_enabled:
        return "paused"
    if run_status in {"queued", "running"}:
        return "running"
    if run_status == "completed":
        return "idle"
    if run_status == "partial":
        return "partial"
    if run_status in {"retryable_failed", "failed", "cancelled"}:
        return "error"
    raise ValueError(f"Unsupported run status: {run_status}")


def classify_run_outcome(
    persisted_post_count: int,
    downstream_stage_failed: bool,
    failure_is_transient: bool,
    failure_is_terminal: bool,
) -> str:
    if persisted_post_count > 0 and downstream_stage_failed:
        return "partial"
    if failure_is_terminal:
        return "failed"
    if failure_is_transient:
        return "retryable_failed"
    return "completed"
