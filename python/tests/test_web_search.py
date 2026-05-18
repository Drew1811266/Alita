from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from agent_service.web_search import (
    DuckDuckGoHtmlSearchProvider,
    SearchFailure,
    SearchResult,
    classify_sources,
    parse_duckduckgo_html_results,
    rank_sources,
)


def test_provider_sanitizes_query_before_request_construction() -> None:
    seen: list[str] = []

    def transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
        seen.append(url)
        return b""

    provider = DuckDuckGoHtmlSearchProvider(transport=transport)
    raw_query = (
        r"Search D:\Software Project\Alita\python\agent_service\graph.py "
        "LangGraph docs token=abcdefghijklmnopqrstuvwxyz1234567890 drew@example.com"
    )

    response = provider.search(raw_query)

    assert response.failure is None
    query = parse_qs(urlparse(seen[0]).query)["q"][0]
    assert query == "Search [LOCAL_PATH] LangGraph docs [SECRET] [EMAIL]"
    assert "Software Project" not in seen[0]
    assert "abcdefghijklmnopqrstuvwxyz1234567890" not in seen[0]
    assert "drew@example.com" not in seen[0]


def test_provider_does_not_request_when_privacy_guard_blocks_query() -> None:
    called = False

    def transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
        nonlocal called
        called = True
        return b""

    provider = DuckDuckGoHtmlSearchProvider(transport=transport)

    response = provider.search(r"cd C:\Users\Drew\Projects\Alita")

    assert called is False
    assert response.results == []
    assert response.failure == SearchFailure(
        kind="privacy_blocked",
        message="Search query was blocked by privacy guard.",
        blocked=True,
        removedCategories=["LOCAL_PATH"],
    )


def test_timeout_returns_structured_failure() -> None:
    def transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
        raise TimeoutError("timed out while connecting to private host details")

    provider = DuckDuckGoHtmlSearchProvider(transport=transport, timeout=0.01)

    response = provider.search("LangGraph routing docs")

    assert response.results == []
    assert response.failure == SearchFailure(
        kind="timeout",
        message="Search request timed out.",
    )


def test_html_parser_returns_title_url_and_snippet() -> None:
    html = """
    <html><body>
      <div class="result">
        <a class="result__a" href="https://docs.example.com/page?q=1">Example Docs</a>
        <a class="result__snippet">Official usage examples &amp; API notes.</a>
      </div>
      <div class="result">
        <a class="result__a" href="https://github.com/org/project">Project Repo</a>
        <div class="result__snippet">Primary source repository.</div>
      </div>
    </body></html>
    """

    results = parse_duckduckgo_html_results(html)

    assert results == [
        SearchResult(
            title="Example Docs",
            url="https://docs.example.com/page?q=1",
            snippet="Official usage examples & API notes.",
        ),
        SearchResult(
            title="Project Repo",
            url="https://github.com/org/project",
            snippet="Primary source repository.",
        ),
    ]


def test_official_domains_rank_above_forums_and_aggregators_for_official_sources() -> None:
    results = [
        SearchResult("Forum answer", "https://stackoverflow.com/questions/1", "thread"),
        SearchResult("SEO summary", "https://bestchoices.example/top-langgraph", "roundup"),
        SearchResult("LangGraph Docs", "https://langchain-ai.github.io/langgraph/", "docs"),
    ]

    ranked = rank_sources("software", results)

    assert [result.title for result in ranked] == [
        "LangGraph Docs",
        "Forum answer",
        "SEO summary",
    ]


def test_dynamic_source_ranking_for_supported_question_types() -> None:
    cases = [
        (
            "model",
            [
                SearchResult("Reddit", "https://reddit.com/r/LocalLLaMA/post", ""),
                SearchResult("Provider docs", "https://platform.openai.com/docs/models", ""),
                SearchResult("Model repo", "https://huggingface.co/Qwen/Qwen3", ""),
            ],
            ["Provider docs", "Model repo", "Reddit"],
        ),
        (
            "software",
            [
                SearchResult("Blog repost", "https://medium.com/someone/repost", ""),
                SearchResult("Package", "https://pypi.org/project/langgraph/", ""),
                SearchResult("Primary repo", "https://github.com/langchain-ai/langgraph", ""),
            ],
            ["Primary repo", "Package", "Blog repost"],
        ),
        (
            "academic",
            [
                SearchResult("SEO explainer", "https://papersummary.example/123", ""),
                SearchResult("Paper", "https://arxiv.org/abs/2401.00001", ""),
                SearchResult("Lab", "https://cs.stanford.edu/research/example", ""),
            ],
            ["Paper", "Lab", "SEO explainer"],
        ),
        (
            "policy",
            [
                SearchResult("Forum", "https://reddit.com/r/legaladvice/post", ""),
                SearchResult("Regulator", "https://www.ftc.gov/business-guidance", ""),
                SearchResult("Standards", "https://www.iso.org/standard/27001", ""),
            ],
            ["Regulator", "Standards", "Forum"],
        ),
        (
            "product",
            [
                SearchResult("Affiliate review", "https://bestreviews.example/widget", ""),
                SearchResult("Manufacturer", "https://support.apple.com/mac", ""),
                SearchResult("Retail listing", "https://www.amazon.com/example", ""),
            ],
            ["Manufacturer", "Retail listing", "Affiliate review"],
        ),
    ]

    for question_type, results, expected_titles in cases:
        assert [result.title for result in rank_sources(question_type, results)] == expected_titles


def test_source_classification_accepts_primary_sources_and_rejects_low_signal_sources() -> None:
    results = [
        SearchResult("Official docs", "https://docs.python.org/3/library/asyncio.html", ""),
        SearchResult("Vendor page", "https://www.microsoft.com/windows", ""),
        SearchResult("Primary repo", "https://github.com/python/cpython", ""),
        SearchResult("Research paper", "https://doi.org/10.1145/123456", ""),
        SearchResult("Standards body", "https://www.w3.org/TR/webauthn-3/", ""),
        SearchResult("Recognized docs", "https://developer.mozilla.org/en-US/docs/Web/API", ""),
        SearchResult("SEO aggregator", "https://bestreviews.example/python-asyncio", ""),
        SearchResult("Content farm", "https://top10answers.example/what-is-asyncio", ""),
        SearchResult("Low signal repost", "https://medium.com/someone/copied-release-notes", ""),
        SearchResult("Stale page", "https://old.example.com/asyncio", "Last updated 2017"),
        SearchResult("Unrelated forum", "https://reddit.com/r/gardening/comments/1", "tomato thread"),
    ]

    classified = classify_sources("software", results)

    accepted = {result.title: result for result in classified if result.accepted}
    rejected = {result.title: result for result in classified if not result.accepted}
    assert set(accepted) == {
        "Official docs",
        "Vendor page",
        "Primary repo",
        "Research paper",
        "Standards body",
        "Recognized docs",
    }
    assert rejected["SEO aggregator"].rejectionReason == "seo_aggregator"
    assert rejected["Content farm"].rejectionReason == "content_farm"
    assert rejected["Low signal repost"].rejectionReason == "low_signal_repost"
    assert rejected["Stale page"].rejectionReason == "stale_page"
    assert rejected["Unrelated forum"].rejectionReason == "unrelated_forum_thread"
