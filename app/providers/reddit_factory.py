from __future__ import annotations

import os

from app.providers.reddit import RedditConfigurationError, RedditOAuthClient
from app.providers.reddit_browser import RedditBrowserClient


SUPPORTED_REDDIT_PROVIDERS = {"oauth", "browser"}


def get_reddit_provider_name() -> str:
    provider = os.getenv("REDDIT_PROVIDER", "oauth").strip().lower() or "oauth"
    if provider not in SUPPORTED_REDDIT_PROVIDERS:
        raise RedditConfigurationError(
            f"REDDIT_PROVIDER must be one of: {', '.join(sorted(SUPPORTED_REDDIT_PROVIDERS))}"
        )
    return provider


def create_reddit_client_from_env():
    provider = get_reddit_provider_name()
    if provider == "oauth":
        return RedditOAuthClient.from_env()
    if provider == "browser":
        return RedditBrowserClient.from_env()
    raise RedditConfigurationError(f"Unsupported Reddit provider '{provider}'")
