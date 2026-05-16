from __future__ import annotations


def test_factory_uses_oauth_provider_by_default(monkeypatch):
    called = {"oauth": False}

    class StubOauth:
        @classmethod
        def from_env(cls):
            called["oauth"] = True
            return "oauth-client"

    monkeypatch.delenv("REDDIT_PROVIDER", raising=False)
    monkeypatch.setattr("app.providers.reddit_factory.RedditOAuthClient", StubOauth)

    from app.providers.reddit_factory import create_reddit_client_from_env

    client = create_reddit_client_from_env()

    assert client == "oauth-client"
    assert called["oauth"] is True


def test_factory_uses_browser_provider_when_requested(monkeypatch):
    called = {"browser": False}

    class StubBrowser:
        @classmethod
        def from_env(cls):
            called["browser"] = True
            return "browser-client"

    monkeypatch.setenv("REDDIT_PROVIDER", "browser")
    monkeypatch.setattr("app.providers.reddit_factory.RedditBrowserClient", StubBrowser)

    from app.providers.reddit_factory import create_reddit_client_from_env

    client = create_reddit_client_from_env()

    assert client == "browser-client"
    assert called["browser"] is True


def test_factory_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("REDDIT_PROVIDER", "mystery")

    from app.providers.reddit_factory import create_reddit_client_from_env
    from app.providers.reddit import RedditConfigurationError

    try:
        create_reddit_client_from_env()
    except RedditConfigurationError as exc:
        assert "REDDIT_PROVIDER" in str(exc)
    else:
        raise AssertionError("Expected invalid provider to raise RedditConfigurationError")
