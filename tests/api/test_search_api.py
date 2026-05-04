from __future__ import annotations

import copy
from uuid import UUID

import pytest


def test_post_search_returns_202_for_valid_request(client, workspace_headers, valid_search_payload):
    response = client.post("/search", json=valid_search_payload, headers=workspace_headers)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert UUID(body["job_id"])
    assert UUID(body["run_id"])


def test_post_search_accepts_structured_query_definition_payload(
    client, workspace_headers, structured_search_payload
):
    response = client.post("/search", json=structured_search_payload, headers=workspace_headers)

    assert response.status_code == 202
    body = response.json()
    search_view = client.get(f"/search/{body['job_id']}", headers=workspace_headers).json()
    assert search_view["query"]["query_definition_id"] == "q-tooling-001"
    assert search_view["query"]["cluster"] == "tooling_ask"
    assert search_view["query"]["priority"] == 1
    assert search_view["query"]["subreddits"] == ["instructionaldesign", "edtech"]
    assert search_view["query"]["match_must_include_any"] == ["adaptive", "branching"]


def test_post_search_rejects_missing_query(client, workspace_headers, valid_search_payload):
    payload = copy.deepcopy(valid_search_payload)
    payload.pop("query")

    response = client.post("/search", json=payload, headers=workspace_headers)

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert body["error"]["retryable"] is False
    assert any(detail["field"] == "query" for detail in body["error"]["details"])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("query", "x" * 201),
        ("subreddit", "r/Invalid-Name"),
        ("limit", 101),
        ("min_score", -1),
        ("date_from", "2025-03-02"),
        ("date_to", "2026-03-01"),
    ],
)
def test_post_search_rejects_invalid_field_values(
    client, workspace_headers, valid_search_payload, field, value
):
    payload = copy.deepcopy(valid_search_payload)
    payload[field] = value

    response = client.post("/search", json=payload, headers=workspace_headers)

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert body["error"]["request_id"]


def test_post_search_reuses_same_idempotency_key_for_same_payload(
    client, workspace_headers, valid_search_payload
):
    first = client.post("/search", json=valid_search_payload, headers=workspace_headers)
    second = client.post("/search", json=valid_search_payload, headers=workspace_headers)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json() == first.json()


def test_post_search_rejects_same_idempotency_key_for_different_payload(
    client, workspace_headers, valid_search_payload
):
    first = client.post("/search", json=valid_search_payload, headers=workspace_headers)
    assert first.status_code == 202

    changed = copy.deepcopy(valid_search_payload)
    changed["limit"] = 25

    second = client.post("/search", json=changed, headers=workspace_headers)

    assert second.status_code == 409
    body = second.json()
    assert body["error"]["code"] == "idempotency_payload_mismatch"
    assert body["error"]["retryable"] is False


def test_post_search_rejects_subreddit_outside_allowlist(client, workspace_headers, valid_search_payload):
    payload = copy.deepcopy(valid_search_payload)
    payload["subreddit"] = "productmanagement"

    response = client.post("/search", json=payload, headers=workspace_headers)

    assert response.status_code == 400
    assert any(detail["field"] == "subreddit" for detail in response.json()["error"]["details"])


def test_get_search_unknown_or_unauthorized_job_returns_404(client, workspace_headers):
    response = client.get(
        "/search/00000000-0000-0000-0000-000000000000", headers=workspace_headers
    )

    assert response.status_code == 404


def test_post_refresh_requires_idempotency_key(client, workspace_headers):
    response = client.post(
        "/refresh/00000000-0000-0000-0000-000000000000",
        json={},
        headers=workspace_headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_post_refresh_returns_existing_active_run_on_overlap(
    client, workspace_headers, valid_search_payload
):
    create_response = client.post("/search", json=valid_search_payload, headers=workspace_headers)
    assert create_response.status_code == 202
    job_id = create_response.json()["job_id"]

    refresh_payload = {"idempotency_key": "22222222-2222-2222-2222-222222222222"}

    first = client.post(f"/refresh/{job_id}", json=refresh_payload, headers=workspace_headers)
    second = client.post(f"/refresh/{job_id}", json=refresh_payload, headers=workspace_headers)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json() == first.json()


def test_import_search_templates_from_yaml_and_list_them(client, workspace_headers, query_bank_yaml):
    response = client.post(
        "/search-templates/import",
        json={
            "yaml_content": query_bank_yaml,
            "schedule_daily": True,
            "limit": 50,
            "min_score": 5,
            "include_comments": True,
            "enrich": True,
            "idempotency_key": "44444444-4444-4444-4444-444444444444",
        },
        headers=workspace_headers,
    )

    assert response.status_code == 202
    body = response.json()
    assert body["imported_templates"] == 2
    assert body["templates"][0]["schedule_enabled"] is True
    assert body["templates"][0]["schedule_interval_hours"] == 24

    listed = client.get("/search-templates", headers=workspace_headers)
    assert listed.status_code == 200
    templates = listed.json()["templates"]
    assert len(templates) == 2
    assert templates[0]["query_payload"]["query_mode"] == "query_definition"


def test_run_search_template_now_queues_refresh(client, workspace_headers, query_bank_yaml):
    imported = client.post(
        "/search-templates/import",
        json={
            "yaml_content": query_bank_yaml,
            "schedule_daily": True,
            "limit": 50,
            "min_score": 5,
            "include_comments": True,
            "enrich": True,
            "idempotency_key": "55555555-5555-5555-5555-555555555555",
        },
        headers=workspace_headers,
    ).json()
    template_id = imported["templates"][0]["template_id"]

    response = client.post(
        f"/search-templates/{template_id}/run",
        json={"idempotency_key": "66666666-6666-6666-6666-666666666666"},
        headers=workspace_headers,
    )

    assert response.status_code == 202
    body = response.json()
    assert body["template_id"] == template_id
    assert body["status"] == "queued"


def test_home_page_renders_template_import_and_saved_templates_sections(
    client, workspace_headers, query_bank_yaml
):
    client.post(
        "/search-templates/import",
        json={
            "yaml_content": query_bank_yaml,
            "schedule_daily": True,
            "limit": 50,
            "min_score": 5,
            "include_comments": True,
            "enrich": True,
            "idempotency_key": "88888888-8888-8888-8888-888888888888",
        },
        headers=workspace_headers,
    )

    response = client.get("/?workspace_id=test-workspace")

    assert response.status_code == 200
    assert "Import Query Bank" in response.text
    assert "Saved Templates" in response.text
