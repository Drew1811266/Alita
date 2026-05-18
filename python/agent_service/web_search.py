from __future__ import annotations

from dataclasses import dataclass, replace
from html.parser import HTMLParser
import socket
from typing import Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from agent_service.privacy import sanitize_for_web_search


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    sourceType: str | None = None
    accepted: bool | None = None
    rejectionReason: str | None = None


@dataclass(frozen=True)
class SearchFailure:
    kind: str
    message: str
    blocked: bool = False
    removedCategories: list[str] | None = None


@dataclass(frozen=True)
class SearchResponse:
    results: list[SearchResult]
    failure: SearchFailure | None = None


class SearchProvider(Protocol):
    def search(self, query: str) -> SearchResponse:
        ...


Transport = Callable[[str, float, dict[str, str]], bytes]


class DuckDuckGoHtmlSearchProvider:
    def __init__(
        self,
        *,
        transport: Transport | None = None,
        timeout: float = 8.0,
    ) -> None:
        self._transport = transport or _urllib_transport
        self._timeout = timeout

    def search(self, query: str) -> SearchResponse:
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
            )

        url = "https://duckduckgo.com/html/?" + urlencode({"q": guard.sanitizedText})
        headers = {"User-Agent": "Mozilla/5.0 (compatible; web-search-provider/1.0)"}

        try:
            body = self._transport(url, self._timeout, headers)
        except (TimeoutError, socket.timeout):
            return SearchResponse(
                results=[],
                failure=SearchFailure(
                    kind="timeout",
                    message="Search request timed out.",
                ),
            )
        except (HTTPError, URLError, OSError):
            return SearchResponse(
                results=[],
                failure=SearchFailure(
                    kind="network_error",
                    message="Search request failed.",
                ),
            )

        return SearchResponse(
            results=parse_duckduckgo_html_results(
                body.decode("utf-8", errors="replace")
            )
        )


@dataclass(frozen=True)
class InjectedSearchProvider:
    response: SearchResponse

    def search(self, query: str) -> SearchResponse:
        return self.response


def _urllib_transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def parse_duckduckgo_html_results(html: str) -> list[SearchResult]:
    parser = _DuckDuckGoHtmlParser()
    parser.feed(html)
    parser.close()
    return parser.results


class _DuckDuckGoHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[SearchResult] = []
        self._current_title: list[str] = []
        self._current_url: str | None = None
        self._current_snippet: list[str] = []
        self._capture_title = False
        self._capture_snippet = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())

        if tag == "a" and "result__a" in classes:
            self._flush_result()
            self._current_url = _normalize_result_url(attributes.get("href") or "")
            self._current_title = []
            self._current_snippet = []
            self._capture_title = True
            return

        if "result__snippet" in classes:
            self._capture_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture_title:
            self._capture_title = False
        if self._capture_snippet and tag in {"a", "div"}:
            self._capture_snippet = False

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self._current_title.append(data)
        elif self._capture_snippet:
            self._current_snippet.append(data)

    def close(self) -> None:
        self._flush_result()
        super().close()

    def _flush_result(self) -> None:
        title = _clean_text(" ".join(self._current_title))
        url = self._current_url or ""
        if title and url:
            self.results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=_clean_text(" ".join(self._current_snippet)),
                )
            )
        self._current_title = []
        self._current_url = None
        self._current_snippet = []
        self._capture_title = False
        self._capture_snippet = False


def _normalize_result_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.path == "/l/":
        redirected = parse_qs(parsed.query).get("uddg", [""])[0]
        if redirected:
            return redirected
    return url


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def rank_sources(question_type: str, results: list[SearchResult]) -> list[SearchResult]:
    return sorted(
        results,
        key=lambda result: _rank_score(question_type, result),
    )


def classify_sources(
    question_type: str,
    results: list[SearchResult],
) -> list[SearchResult]:
    classified: list[SearchResult] = []
    for result in results:
        source_type = _source_type(question_type, result)
        rejection_reason = _rejection_reason(question_type, result)
        accepted = rejection_reason is None and _is_accepted_source_type(source_type)
        classified.append(
            replace(
                result,
                sourceType=source_type,
                accepted=accepted,
                rejectionReason=(
                    rejection_reason
                    if rejection_reason is not None or accepted
                    else "unrecognized_source"
                ),
            )
        )
    return classified


def _rank_score(question_type: str, result: SearchResult) -> tuple[int, str]:
    host = _host(result.url)
    kind = question_type.lower()
    rejection = _rejection_reason(kind, result)
    if rejection in {"seo_aggregator", "content_farm", "low_signal_repost"}:
        return (90, host)
    if rejection:
        return (80, host)

    if kind == "model":
        if _is_vendor_docs(host):
            return (0, host)
        if host == "huggingface.co" or host == "github.com":
            return (1, host)
    if kind == "software":
        if host == "github.com" or _is_official_docs(host):
            return (0, host)
        if host in {"pypi.org", "npmjs.com"} or host.endswith(".readthedocs.io"):
            return (1, host)
    if kind == "academic":
        if host in {"arxiv.org", "doi.org"} or "doi.org" in host:
            return (0, host)
        if host.endswith(".edu") or _is_research_lab(host):
            return (1, host)
    if kind == "policy":
        if host.endswith(".gov") or _is_regulator(host):
            return (0, host)
        if _is_standards_body(host):
            return (1, host)
    if kind == "product":
        if _is_vendor_docs(host):
            return (0, host)
        if _is_retailer(host):
            return (2, host)

    if _is_official_docs(host) or _is_primary_source(host):
        return (10, host)
    if _is_forum(host):
        return (60, host)
    return (40, host)


def _source_type(question_type: str, result: SearchResult) -> str:
    host = _host(result.url)
    if _is_standards_body(host):
        return "standards_body"
    if host in {"arxiv.org", "doi.org"} or "doi.org" in host:
        return "research_paper"
    if host == "github.com":
        return "primary_repo"
    if _is_recognized_docs(host):
        return "recognized_docs"
    if _is_official_docs(host):
        return "official_docs"
    if _is_vendor_docs(host):
        return "vendor_page"
    if _is_forum(host):
        return "forum"
    return question_type.lower()


def _is_accepted_source_type(source_type: str) -> bool:
    return source_type in {
        "official_docs",
        "vendor_page",
        "primary_repo",
        "research_paper",
        "standards_body",
        "recognized_docs",
    }


def _rejection_reason(question_type: str, result: SearchResult) -> str | None:
    host = _host(result.url)
    haystack = f"{result.title} {result.url} {result.snippet}".lower()
    if "bestreviews." in host or "bestchoices." in host:
        return "seo_aggregator"
    if "top10" in host or "answers.example" in host:
        return "content_farm"
    if "repost" in haystack or "copied-release-notes" in haystack:
        return "low_signal_repost"
    if "last updated 2017" in haystack or "last updated 2016" in haystack:
        return "stale_page"
    if _is_forum(host) and not _has_question_type_signal(question_type, haystack):
        return "unrelated_forum_thread"
    return None


def _has_question_type_signal(question_type: str, haystack: str) -> bool:
    signals = {
        "model": ("model", "llama", "qwen", "gpt", "huggingface"),
        "software": ("docs", "api", "library", "package", "python", "langgraph"),
        "academic": ("paper", "research", "study", "arxiv", "doi"),
        "policy": ("policy", "law", "regulation", "standard", "guidance"),
        "product": ("product", "support", "manual", "spec", "manufacturer"),
    }
    return any(signal in haystack for signal in signals.get(question_type.lower(), ()))


def _host(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _is_primary_source(host: str) -> bool:
    return (
        host == "github.com"
        or host == "huggingface.co"
        or _is_official_docs(host)
        or _is_vendor_docs(host)
        or _is_standards_body(host)
    )


def _is_official_docs(host: str) -> bool:
    return (
        host.startswith("docs.")
        or host.startswith("developer.")
        or host.endswith(".readthedocs.io")
        or host in {"pypi.org", "npmjs.com"}
        or _is_recognized_docs(host)
    )


def _is_vendor_docs(host: str) -> bool:
    return host in {
        "apple.com",
        "support.apple.com",
        "microsoft.com",
        "learn.microsoft.com",
        "openai.com",
        "platform.openai.com",
        "anthropic.com",
        "docs.anthropic.com",
    } or _is_official_docs(host)


def _is_recognized_docs(host: str) -> bool:
    return host in {
        "developer.mozilla.org",
        "docs.python.org",
        "langchain-ai.github.io",
    }


def _is_standards_body(host: str) -> bool:
    return host in {"w3.org", "iso.org", "ietf.org"} or host.endswith(
        (".w3.org", ".iso.org", ".ietf.org")
    )


def _is_regulator(host: str) -> bool:
    return host in {"ftc.gov", "sec.gov", "fda.gov", "europa.eu"} or host.endswith(
        (".ftc.gov", ".sec.gov", ".fda.gov", ".europa.eu")
    )


def _is_research_lab(host: str) -> bool:
    return host.endswith(".edu") or host in {
        "openai.com",
        "deepmind.google",
        "research.google",
        "ai.meta.com",
    }


def _is_retailer(host: str) -> bool:
    return host in {"amazon.com", "bestbuy.com", "walmart.com", "target.com"}


def _is_forum(host: str) -> bool:
    return host in {"reddit.com", "stackoverflow.com", "news.ycombinator.com"} or host.endswith(
        ".stackexchange.com"
    )
