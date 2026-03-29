from __future__ import annotations


def test_get_posts_rejects_limit_above_cap(client, workspace_headers):
    response = client.get("/posts?limit=101", headers=workspace_headers)

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert any(detail["field"] == "limit" for detail in body["error"]["details"])


def test_get_posts_rejects_offset_above_cap(client, workspace_headers):
    response = client.get("/posts?offset=1001", headers=workspace_headers)

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert any(detail["field"] == "offset" for detail in body["error"]["details"])


def test_get_post_unknown_or_unauthorized_id_returns_404(client, workspace_headers):
    response = client.get("/posts/t3_missing", headers=workspace_headers)

    assert response.status_code == 404


def test_all_error_responses_use_standard_error_envelope(client, workspace_headers):
    response = client.get("/posts?limit=101", headers=workspace_headers)

    assert response.status_code == 400
    body = response.json()
    assert set(body["error"]) == {"code", "message", "details", "retryable", "request_id"}
    assert isinstance(body["error"]["details"], list)
