from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from tests.support import (
    build_query_bank_yaml,
    build_structured_search_payload,
    build_valid_search_payload,
    load_symbol,
)


@pytest.fixture
def workspace_headers() -> dict[str, str]:
    return {"X-Workspace-Id": "test-workspace"}


@pytest.fixture
def valid_search_payload() -> dict[str, object]:
    return build_valid_search_payload()


@pytest.fixture
def structured_search_payload() -> dict[str, object]:
    return build_structured_search_payload()


@pytest.fixture
def query_bank_yaml() -> str:
    return build_query_bank_yaml()


@pytest.fixture
def create_app():
    return load_symbol("app.main", "create_app")


@pytest.fixture
def app(create_app):
    try:
        return create_app(testing=True)
    except TypeError:
        return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def normalize_query():
    return load_symbol("app.domain.search", "normalize_query")


@pytest.fixture
def normalize_subreddit():
    return load_symbol("app.domain.search", "normalize_subreddit")


@pytest.fixture
def build_query_hash():
    return load_symbol("app.domain.search", "build_query_hash")


@pytest.fixture
def project_search_job_status():
    return load_symbol("app.domain.jobs", "project_search_job_status")


@pytest.fixture
def classify_run_outcome():
    return load_symbol("app.domain.jobs", "classify_run_outcome")


@pytest.fixture
def select_api_comments():
    return load_symbol("app.domain.comments", "select_api_comments")


@pytest.fixture
def create_reddit_client():
    return load_symbol("app.providers.reddit", "RedditOAuthClient")
