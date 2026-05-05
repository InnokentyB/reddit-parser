from __future__ import annotations


def test_swagger_ui_is_published(client):
    response = client.get("/docs")

    assert response.status_code == 200
    assert "Swagger UI" in response.text


def test_openapi_json_includes_planner_endpoints_and_workspace_header(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    body = response.json()
    assert body["info"]["title"] == "Reddit Insight Collector API"
    assert "/insights" in body["paths"]
    assert "/summaries/{job_id}" in body["paths"]
    assert "/search" in body["paths"]

    posts_parameters = body["paths"]["/posts"]["get"]["parameters"]
    assert any(parameter["name"] == "X-Workspace-Id" for parameter in posts_parameters)
