from __future__ import annotations

from collections.abc import Callable, Sequence
import json
import os
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from agent_service.privacy import sanitize_for_web_search
from agent_service.web_search import (
    DuckDuckGoHtmlSearchProvider,
    SearchFailure,
    SearchProvider,
    SearchResponse,
    SearchResult,
)


SearchTransport = Callable[[str, float, dict[str, str]], bytes]


class ProviderChainSearchProvider:
    name = "provider_chain"

    def __init__(self, providers: Sequence[SearchProvider]) -> None:
        self.providers = list(providers)

    def is_configured(self) -> bool:
        return any(
            _provider_configuration_status(provider) == "configured"
            for provider in self.providers
        )

    def search(self, query: str) -> SearchResponse:
        attempts: list[dict[str, str]] = []
        last_failure: SearchFailure | None = None
        saw_actual_failure = False

        for provider in self.providers:
            provider_name = _provider_name(provider)
            configuration_status = _provider_configuration_status(provider)
            if configuration_status == "error":
                last_failure = SearchFailure(
                    kind="provider_error",
                    message="Search provider failed.",
                )
                saw_actual_failure = True
                attempts.append(
                    {
                        "provider": provider_name,
                        "status": "failed",
                        "kind": last_failure.kind,
                        "message": last_failure.message,
                    }
                )
                continue
            if configuration_status == "not_configured":
                attempts.append({"provider": provider_name, "status": "not_configured"})
                continue

            try:
                response = provider.search(query)
            except Exception:
                last_failure = SearchFailure(
                    kind="provider_error",
                    message="Search provider failed.",
                )
                saw_actual_failure = True
                attempts.append(
                    {
                        "provider": provider_name,
                        "status": "failed",
                        "kind": last_failure.kind,
                        "message": last_failure.message,
                    }
                )
                continue

            if response.results:
                return SearchResponse(
                    results=response.results,
                    failure=None,
                    metadata={
                        "provider": provider_name,
                        "attempts": [
                            *attempts,
                            {"provider": provider_name, "status": "ok"},
                        ],
                    },
                )

            if response.failure is not None:
                last_failure = response.failure
                saw_actual_failure = (
                    saw_actual_failure or response.failure.kind != "no_results"
                )
                attempts.append(_failure_attempt(provider_name, response.failure.kind))
                if response.failure.kind == "privacy_blocked" and response.failure.blocked:
                    return SearchResponse(
                        results=[],
                        failure=SearchFailure(
                            kind=response.failure.kind,
                            message=_safe_failure_message(response.failure.kind),
                            blocked=True,
                            removedCategories=response.failure.removedCategories,
                        ),
                        metadata={"provider": self.name, "attempts": attempts},
                    )
                continue

            last_failure = SearchFailure(
                kind="no_results",
                message="Search provider returned no results.",
            )
            attempts.append({"provider": provider_name, "status": "no_results"})

        return SearchResponse(
            results=[],
            failure=SearchFailure(
                kind=last_failure.kind if last_failure else "not_configured",
                message=(
                    "没有找到相关搜索结果。"
                    if last_failure is not None and not saw_actual_failure
                    else "所有搜索服务暂时不可用。"
                    if last_failure is not None
                    else "没有可用的搜索服务，请配置搜索提供方。"
                ),
                blocked=last_failure.blocked if last_failure else False,
                removedCategories=last_failure.removedCategories
                if last_failure
                else None,
            ),
            metadata={"provider": self.name, "attempts": attempts},
        )


class BraveSearchProvider:
    name = "brave"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        transport: SearchTransport | None = None,
        timeout: float = 8.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv(
            "ALITA_BRAVE_SEARCH_API_KEY",
            "",
        )
        self._transport = transport or _urllib_transport
        self._timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str) -> SearchResponse:
        if not self.is_configured():
            return SearchResponse(
                results=[],
                failure=SearchFailure(
                    kind="not_configured",
                    message="Brave Search API key is not configured.",
                ),
                metadata={"provider": self.name},
            )

        guard = sanitize_for_web_search(query)
        if guard.blocked:
            return SearchResponse(
                results=[],
                failure=SearchFailure(
                    kind="privacy_blocked",
                    message="Search query was blocked by privacy guard.",
                    blocked=True,
                    removedCategories=guard.removedCategories,
                ),
                metadata={"provider": self.name},
            )

        url = "https://api.search.brave.com/res/v1/web/search?" + urlencode(
            {"q": guard.sanitizedText}
        )
        headers = {
            "Accept": "application/json",
            "User-Agent": "Alita/0.27 web-search-tool",
            "X-Subscription-Token": self.api_key or "",
        }
        try:
            body = self._transport(url, self._timeout, headers)
            payload = json.loads(body.decode("utf-8", errors="replace"))
        except (TimeoutError, socket.timeout):
            return SearchResponse(
                results=[],
                failure=SearchFailure(
                    kind="timeout",
                    message="Brave Search request timed out.",
                ),
                metadata={"provider": self.name},
            )
        except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError):
            return SearchResponse(
                results=[],
                failure=SearchFailure(
                    kind="network_error",
                    message="Brave Search request failed.",
                ),
                metadata={"provider": self.name},
            )

        return SearchResponse(
            results=_brave_results(payload),
            metadata={"provider": self.name},
        )


def default_search_provider() -> SearchProvider:
    provider_name = os.getenv("ALITA_WEB_SEARCH_PROVIDER", "auto").strip().lower()
    timeout = _timeout_from_env()
    brave = BraveSearchProvider(timeout=timeout)
    duckduckgo = DuckDuckGoHtmlSearchProvider(timeout=timeout)

    if provider_name == "brave":
        return brave
    if provider_name in {"duckduckgo", "ddg"}:
        return duckduckgo
    return ProviderChainSearchProvider([brave, duckduckgo])


def _urllib_transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _brave_results(payload: Any) -> list[SearchResult]:
    if not isinstance(payload, dict):
        return []
    web = payload.get("web")
    if not isinstance(web, dict):
        return []
    results = web.get("results")
    if not isinstance(results, list):
        return []

    mapped: list[SearchResult] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("description") or item.get("snippet") or "").strip()
        if title and url:
            mapped.append(SearchResult(title=title, url=url, snippet=snippet))
    return mapped


def _provider_name(provider: SearchProvider) -> str:
    return str(getattr(provider, "name", provider.__class__.__name__))


def _failure_attempt(provider_name: str, kind: str) -> dict[str, str]:
    return {
        "provider": provider_name,
        "status": "failed",
        "kind": kind,
        "message": _safe_failure_message(kind),
    }


def _safe_failure_message(kind: str) -> str:
    return {
        "timeout": "Search timed out.",
        "network_error": "Search request failed.",
        "privacy_blocked": "Search query was blocked by privacy guard.",
        "not_configured": "Search provider is not configured.",
        "no_results": "Search provider returned no results.",
        "provider_error": "Search provider failed.",
    }.get(kind, "Search provider failed.")


def _provider_configuration_status(provider: SearchProvider) -> str:
    checker = getattr(provider, "is_configured", None)
    if checker is None:
        return "configured"
    try:
        return "configured" if checker() else "not_configured"
    except Exception:
        return "error"


def _timeout_from_env() -> float:
    raw = os.getenv("ALITA_WEB_SEARCH_TIMEOUT_SECONDS", "8")
    try:
        return max(0.5, float(raw))
    except ValueError:
        return 8.0
