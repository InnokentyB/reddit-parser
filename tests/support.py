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
        "query": "AI product manager",
        "subreddit": "productmanagement",
        "limit": 50,
        "min_score": 5,
        "date_from": "2025-01-01",
        "date_to": "2025-03-01",
        "include_comments": True,
        "enrich": True,
        "idempotency_key": "11111111-1111-1111-1111-111111111111",
    }
