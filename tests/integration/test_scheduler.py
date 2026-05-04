from __future__ import annotations

from datetime import timedelta

from app.models import JobRunModel, SearchTemplateModel
from app.scheduler import enqueue_due_templates


def test_scheduler_enqueues_due_templates(app, client, workspace_headers, query_bank_yaml):
    imported = client.post(
        "/search-templates/import",
        json={
            "yaml_content": query_bank_yaml,
            "schedule_daily": True,
            "limit": 50,
            "min_score": 5,
            "include_comments": True,
            "enrich": True,
            "idempotency_key": "99999999-9999-9999-9999-999999999998",
        },
        headers=workspace_headers,
    ).json()

    template_id = imported["templates"][0]["template_id"]

    with app.state.repository.session_factory() as session:
        template = session.get(SearchTemplateModel, template_id)
        initial_run = session.get(JobRunModel, imported["templates"][0]["run_id"])
        initial_run.status = "completed"
        template.next_run_at = template.next_run_at - timedelta(days=1)
        session.commit()

    count = enqueue_due_templates(app.state.repository)

    assert count == 1
