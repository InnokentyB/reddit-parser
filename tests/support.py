from __future__ import annotations

from importlib import import_module
from typing import Any

import pytest


def load_symbol(module_name: str, symbol_name: str) -> Any:
    """Load an implementation symbol and fail with a TDD-oriented message if missing."""
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        pytest.fail(
            f"Missing module '{module_name}'. "
            f"Implement the production code seam expected by the TDD suite before rerunning tests. "
            f"Original error: {exc}"
        )

    try:
        return getattr(module, symbol_name)
    except AttributeError:
        pytest.fail(
            f"Module '{module_name}' does not export '{symbol_name}'. "
            f"Add that public seam so the contract tests can execute."
        )


def build_valid_search_payload() -> dict[str, Any]:
    return {
        "query": "AI course authoring tools",
        "subreddit": "instructionaldesign",
        "limit": 50,
        "min_score": 5,
        "date_from": "2025-01-01",
        "date_to": "2025-03-01",
        "include_comments": True,
        "enrich": True,
        "idempotency_key": "11111111-1111-1111-1111-111111111111",
    }


def build_structured_search_payload() -> dict[str, Any]:
    return {
        "id": "q-tooling-001",
        "intent": "OP explicitly asks for adaptive/branching course tool",
        "cluster": "tooling_ask",
        "priority": 1,
        "subreddits": ["instructionaldesign", "edtech"],
        "query": '(title:"adaptive" OR title:"branching" OR selftext:"adaptive" OR selftext:"branching") AND (title:"tool" OR title:"platform" OR title:"recommend" OR selftext:"recommend") NOT title:"job"',
        "match_must_include_any": ["adaptive", "branching"],
        "exclude_if_contains": ["hiring", "job posting", "looking for work", "freelancer"],
        "limit": 50,
        "min_score": 5,
        "date_from": "2025-01-01",
        "date_to": "2025-03-01",
        "include_comments": True,
        "enrich": True,
        "idempotency_key": "33333333-3333-3333-3333-333333333333",
    }


def build_query_bank_yaml() -> str:
    return """version: "1.0"
last_updated: "2026-04-27"
default_time_filter: "week"
default_sort: "new"
default_limit_per_query: 50
- id: q-tooling-001
  intent: "Adaptive tool request"
  cluster: tooling_ask
  priority: 1
  subreddits: [instructionaldesign, edtech]
  query: 'title:"adaptive" OR selftext:"adaptive"'
  match_must_include_any: ["adaptive"]
  exclude_if_contains: ["hiring"]
- id: q-adaptive-002
  intent: "Branching scenario"
  cluster: framework
  priority: 2
  subreddits: [instructionaldesign]
  query: 'title:"branching" OR selftext:"branching"'
global_exclude_if_any_match:
  - regex: '(?i)\\b(job posting|freelance)\\b'
scraper_cadence:
  pass_interval_hours: 6
  per_query_pause_seconds: 60
"""
