from __future__ import annotations

from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

from agent_service.tool_providers.web_search import (
    BraveSearchProvider,
    ProviderChainSearchProvider,
    default_search_provider,
)
from agent_service.web_search import (
    DuckDuckGoHtmlSearchProvider,
    SearchFailure,
    SearchResponse,
    SearchResult,
)


class FakeProvider:
    def __init__(
        self,
        name: str,
        response: SearchResponse,
        *,
        configured: bool = True,
    ) -> None:
        self.name = name
        self.response = response
        self.configured = configured
        self.queries: list[str] = []

    def is_configured(self) -> bool:
        return self.configured

    def search(self, query: str) -> SearchResponse:
        self.queries.append(query)
        return self.response


class RaisingProvider:
    name = "brave"

    def __init__(self) -> None:
        self.queries: list[str] = []

    def is_configured(self) -> bool:
        return True

    def search(self, query: str) -> SearchResponse:
        self.queries.append(query)
        raise RuntimeError("private provider stack details")


class RaisingConfigurationProvider:
    name = "brave"

    def is_configured(self) -> bool:
        raise RuntimeError("private configuration details")

    def search(self, query: str) -> SearchResponse:
        raise AssertionError("search should not be called")


def test_default_search_provider_auto_chain_when_env_absent_or_auto(
    monkeypatch,
) -> None:
    monkeypatch.delenv("ALITA_WEB_SEARCH_PROVIDER", raising=False)

    provider = default_search_provider()

    assert isinstance(provider, ProviderChainSearchProvider)
    assert [nested.name for nested in provider.providers] == ["brave", "duckduckgo"]

    monkeypatch.setenv("ALITA_WEB_SEARCH_PROVIDER", "auto")

    provider = default_search_provider()

    assert isinstance(provider, ProviderChainSearchProvider)
    assert [nested.name for nested in provider.providers] == ["brave", "duckduckgo"]


def test_default_search_provider_brave_env_returns_brave(monkeypatch) -> None:
    monkeypatch.setenv("ALITA_WEB_SEARCH_PROVIDER", "brave")

    provider = default_search_provider()

    assert isinstance(provider, BraveSearchProvider)


def test_default_search_provider_duckduckgo_env_returns_duckduckgo(
    monkeypatch,
) -> None:
    for provider_name in ("ddg", "duckduckgo"):
        monkeypatch.setenv("ALITA_WEB_SEARCH_PROVIDER", provider_name)

        provider = default_search_provider()

        assert isinstance(provider, DuckDuckGoHtmlSearchProvider)


def test_default_search_provider_timeout_propagates_to_auto_chain(
    monkeypatch,
) -> None:
    monkeypatch.delenv("ALITA_WEB_SEARCH_PROVIDER", raising=False)
    monkeypatch.setenv("ALITA_WEB_SEARCH_TIMEOUT_SECONDS", "3.25")

    provider = default_search_provider()

    assert isinstance(provider, ProviderChainSearchProvider)
    assert [nested._timeout for nested in provider.providers] == [3.25, 3.25]


def test_default_search_provider_timeout_clamps_low_values(monkeypatch) -> None:
    monkeypatch.delenv("ALITA_WEB_SEARCH_PROVIDER", raising=False)
    monkeypatch.setenv("ALITA_WEB_SEARCH_TIMEOUT_SECONDS", "0.1")

    provider = default_search_provider()

    assert isinstance(provider, ProviderChainSearchProvider)
    assert [nested._timeout for nested in provider.providers] == [0.5, 0.5]


def test_chain_skips_unconfigured_provider_and_uses_first_success() -> None:
    skipped = FakeProvider("brave", SearchResponse(results=[]), configured=False)
    success = FakeProvider(
        "duckduckgo",
        SearchResponse(
            results=[
                SearchResult(
                    title="Python Docs",
                    url="https://docs.python.org/",
                    snippet="Official docs.",
                )
            ]
        ),
    )
    chain = ProviderChainSearchProvider([skipped, success])

    response = chain.search("latest Python release")

    assert skipped.queries == []
    assert success.queries == ["latest Python release"]
    assert response.results[0].title == "Python Docs"
    assert response.metadata["provider"] == "duckduckgo"
    assert response.metadata["attempts"] == [
        {"provider": "brave", "status": "not_configured"},
        {"provider": "duckduckgo", "status": "ok"},
    ]


def test_chain_success_metadata_does_not_leak_provider_metadata() -> None:
    provider = FakeProvider(
        "brave",
        SearchResponse(
            results=[
                SearchResult(
                    title="Python Docs",
                    url="https://docs.python.org/",
                    snippet="Official docs.",
                )
            ],
            metadata={
                "rawQuery": r"C:\Users\Drew\secret.txt",
                "apiKey": "secret",
            },
        ),
    )

    response = ProviderChainSearchProvider([provider]).search("latest Python release")

    assert response.metadata == {
        "provider": "brave",
        "attempts": [{"provider": "brave", "status": "ok"}],
    }
    assert "rawQuery" not in response.metadata
    assert "apiKey" not in response.metadata
    assert r"C:\Users\Drew\secret.txt" not in str(response.metadata)
    assert "secret" not in str(response.metadata)


def test_chain_falls_back_after_retryable_failure() -> None:
    failure = FakeProvider(
        "brave",
        SearchResponse(
            results=[],
            failure=SearchFailure(kind="timeout", message="Search timed out."),
        ),
    )
    success = FakeProvider(
        "duckduckgo",
        SearchResponse(
            results=[
                SearchResult(
                    title="LangGraph Docs",
                    url="https://langchain-ai.github.io/langgraph/",
                    snippet="Docs.",
                )
            ]
        ),
    )

    response = ProviderChainSearchProvider([failure, success]).search("LangGraph docs")

    assert failure.queries == ["LangGraph docs"]
    assert success.queries == ["LangGraph docs"]
    assert response.results[0].title == "LangGraph Docs"
    assert response.metadata["attempts"][0] == {
        "provider": "brave",
        "status": "failed",
        "kind": "timeout",
        "message": "Search timed out.",
    }


def test_chain_failure_attempt_message_does_not_leak_provider_message() -> None:
    failure = FakeProvider(
        "brave",
        SearchResponse(
            results=[],
            failure=SearchFailure(
                kind="network_error",
                message=r"DNS failed for C:\Users\Drew\secret.txt apiKey=secret",
            ),
        ),
    )
    success = FakeProvider(
        "duckduckgo",
        SearchResponse(
            results=[
                SearchResult(
                    title="LangGraph Docs",
                    url="https://langchain-ai.github.io/langgraph/",
                    snippet="Docs.",
                )
            ]
        ),
    )

    response = ProviderChainSearchProvider([failure, success]).search("LangGraph docs")

    assert response.metadata["attempts"][0] == {
        "provider": "brave",
        "status": "failed",
        "kind": "network_error",
        "message": "Search request failed.",
    }
    assert r"C:\Users\Drew\secret.txt" not in str(response.metadata)
    assert "apiKey=secret" not in str(response.metadata)


def test_chain_records_provider_exception_safely_and_falls_back() -> None:
    failure = RaisingProvider()
    success = FakeProvider(
        "duckduckgo",
        SearchResponse(
            results=[
                SearchResult(
                    title="LangGraph Docs",
                    url="https://langchain-ai.github.io/langgraph/",
                    snippet="Docs.",
                )
            ]
        ),
    )

    response = ProviderChainSearchProvider([failure, success]).search("LangGraph docs")

    assert failure.queries == ["LangGraph docs"]
    assert success.queries == ["LangGraph docs"]
    assert response.results[0].title == "LangGraph Docs"
    assert response.metadata["attempts"][0] == {
        "provider": "brave",
        "status": "failed",
        "kind": "provider_error",
        "message": "Search provider failed.",
    }
    assert "private provider stack details" not in str(response.metadata)


def test_chain_records_configuration_exception_safely_and_falls_back() -> None:
    failure = RaisingConfigurationProvider()
    success = FakeProvider(
        "duckduckgo",
        SearchResponse(
            results=[
                SearchResult(
                    title="LangGraph Docs",
                    url="https://langchain-ai.github.io/langgraph/",
                    snippet="Docs.",
                )
            ]
        ),
    )

    response = ProviderChainSearchProvider([failure, success]).search("LangGraph docs")

    assert success.queries == ["LangGraph docs"]
    assert response.results[0].title == "LangGraph Docs"
    assert response.metadata["attempts"][0] == {
        "provider": "brave",
        "status": "failed",
        "kind": "provider_error",
        "message": "Search provider failed.",
    }
    assert "private configuration details" not in str(response.metadata)


def test_chain_is_configured_handles_configuration_exception() -> None:
    chain = ProviderChainSearchProvider(
        [
            RaisingConfigurationProvider(),
            FakeProvider("duckduckgo", SearchResponse(results=[]), configured=True),
        ]
    )

    assert chain.is_configured() is True


def test_chain_returns_clear_failure_when_every_provider_fails() -> None:
    chain = ProviderChainSearchProvider(
        [
            FakeProvider("brave", SearchResponse(results=[]), configured=False),
            FakeProvider(
                "duckduckgo",
                SearchResponse(
                    results=[],
                    failure=SearchFailure(
                        kind="network_error",
                        message="Search request failed.",
                    ),
                ),
            ),
        ]
    )

    response = chain.search("today Shanghai weather")

    assert response.results == []
    assert response.failure is not None
    assert response.failure.kind == "network_error"
    assert response.failure.message == "所有搜索服务暂时不可用。"
    assert response.metadata["attempts"] == [
        {"provider": "brave", "status": "not_configured"},
        {
            "provider": "duckduckgo",
            "status": "failed",
            "kind": "network_error",
            "message": "Search request failed.",
        },
    ]


def test_chain_stops_on_privacy_blocked_failure() -> None:
    privacy_blocked = FakeProvider(
        "brave",
        SearchResponse(
            results=[],
            failure=SearchFailure(
                kind="privacy_blocked",
                message="Search query was blocked by privacy guard.",
                blocked=True,
                removedCategories=["LOCAL_PATH"],
            ),
        ),
    )
    fallback = FakeProvider(
        "duckduckgo",
        SearchResponse(
            results=[
                SearchResult(
                    title="Should Not Run",
                    url="https://example.com/",
                    snippet="Skipped.",
                )
            ]
        ),
    )

    response = ProviderChainSearchProvider([privacy_blocked, fallback]).search(
        r"Search C:\Users\Drew\project\secret.txt latest Python release"
    )

    assert privacy_blocked.queries == [
        r"Search C:\Users\Drew\project\secret.txt latest Python release"
    ]
    assert fallback.queries == []
    assert response.results == []
    assert response.failure is not None
    assert response.failure.kind == "privacy_blocked"
    assert response.failure.blocked is True
    assert response.failure.removedCategories == ["LOCAL_PATH"]
    assert response.metadata == {
        "provider": "provider_chain",
        "attempts": [
            {
                "provider": "brave",
                "status": "failed",
                "kind": "privacy_blocked",
                "message": "Search query was blocked by privacy guard.",
            }
        ],
    }


def test_chain_privacy_blocked_message_does_not_leak_provider_message() -> None:
    privacy_blocked = FakeProvider(
        "brave",
        SearchResponse(
            results=[],
            failure=SearchFailure(
                kind="privacy_blocked",
                message=r"blocked raw query C:\Users\Drew\secret.txt apiKey=secret",
                blocked=True,
                removedCategories=["LOCAL_PATH", "SECRET"],
            ),
        ),
    )
    fallback = FakeProvider("duckduckgo", SearchResponse(results=[]))

    response = ProviderChainSearchProvider([privacy_blocked, fallback]).search(
        r"Search C:\Users\Drew\project\secret.txt latest Python release"
    )

    assert fallback.queries == []
    assert response.failure == SearchFailure(
        kind="privacy_blocked",
        message="Search query was blocked by privacy guard.",
        blocked=True,
        removedCategories=["LOCAL_PATH", "SECRET"],
    )
    assert response.metadata == {
        "provider": "provider_chain",
        "attempts": [
            {
                "provider": "brave",
                "status": "failed",
                "kind": "privacy_blocked",
                "message": "Search query was blocked by privacy guard.",
            }
        ],
    }
    assert r"C:\Users\Drew\secret.txt" not in str(response.failure)
    assert "apiKey=secret" not in str(response.failure)
    assert r"C:\Users\Drew\secret.txt" not in str(response.metadata)
    assert "apiKey=secret" not in str(response.metadata)


def test_chain_returns_no_results_failure_when_all_providers_are_empty() -> None:
    chain = ProviderChainSearchProvider(
        [
            FakeProvider("brave", SearchResponse(results=[])),
            FakeProvider("duckduckgo", SearchResponse(results=[])),
        ]
    )

    response = chain.search("latest Python release")

    assert response.results == []
    assert response.failure is not None
    assert response.failure.kind == "no_results"
    assert response.failure.message == "没有找到相关搜索结果。"
    assert response.metadata["attempts"] == [
        {"provider": "brave", "status": "no_results"},
        {"provider": "duckduckgo", "status": "no_results"},
    ]


def test_brave_provider_maps_json_results_and_sanitizes_query() -> None:
    seen: list[tuple[str, dict[str, str]]] = []

    def transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
        seen.append((url, headers))
        return (
            b'{"web":{"results":[{"title":"Python",'
            b'"url":"https://www.python.org/","description":"Official site."}]}}'
        )

    provider = BraveSearchProvider(api_key="test-key", transport=transport)

    response = provider.search(
        r"Search C:\Users\Drew\project\secret.txt latest Python release"
    )

    assert response.failure is None
    assert response.results == [
        SearchResult(
            title="Python",
            url="https://www.python.org/",
            snippet="Official site.",
        )
    ]
    assert response.metadata["provider"] == "brave"
    assert seen[0][1]["X-Subscription-Token"] == "test-key"
    query = parse_qs(urlparse(seen[0][0]).query)["q"][0]
    assert query == "Search [LOCAL_PATH] latest Python release"


def test_brave_provider_returns_not_configured_without_api_key() -> None:
    called = False

    def transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
        nonlocal called
        called = True
        return b"{}"

    provider = BraveSearchProvider(api_key="", transport=transport)

    response = provider.search("latest Python release")

    assert called is False
    assert response.results == []
    assert response.failure is not None
    assert response.failure.kind == "not_configured"


def test_brave_provider_maps_network_error_without_leaking_transport_details() -> None:
    def transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
        raise URLError("private dns details")

    provider = BraveSearchProvider(api_key="test-key", transport=transport)

    response = provider.search("latest Python release")

    assert response.results == []
    assert response.failure is not None
    assert response.failure.kind == "network_error"
    assert response.failure.message == "Brave Search request failed."
