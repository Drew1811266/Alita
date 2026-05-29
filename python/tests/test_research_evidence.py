from __future__ import annotations

from agent_service.research_evidence import (
    citation_ids_in_markdown,
    content_hash,
    evidence_from_search_results,
    normalize_source_url,
    validate_citation_coverage,
)


def test_normalize_source_url_removes_tracking_and_fragment() -> None:
    assert normalize_source_url(
        "HTTPS://Example.com/Path?utm_source=x&b=2&a=1#section"
    ) == "https://example.com/Path?a=1&b=2"


def test_evidence_from_search_results_deduplicates_urls() -> None:
    evidence = evidence_from_search_results(
        "What is Python packaging?",
        [
            {
                "title": "Python Packaging",
                "url": "https://example.com/pkg?utm_source=x",
                "snippet": "Official packaging guide.",
                "accepted": True,
            },
            {
                "title": "Duplicate",
                "url": "https://example.com/pkg",
                "snippet": "Duplicate copy.",
                "accepted": True,
            },
        ],
    )

    assert [source.source_id for source in evidence.accepted_sources] == ["S1"]
    assert [source.source_id for source in evidence.duplicate_sources] == ["S2"]


def test_citation_coverage_reports_missing_citations() -> None:
    evidence = evidence_from_search_results(
        "Question",
        [
            {
                "title": "Accepted",
                "url": "https://example.com/a",
                "snippet": "Useful.",
                "accepted": True,
            }
        ],
    )

    assert citation_ids_in_markdown("Claim [S1].") == {"S1"}
    assert validate_citation_coverage("Claim without citation.", evidence) == [
        "missing_citations"
    ]


def test_content_hash_is_stable_for_whitespace_variants() -> None:
    assert content_hash("A\n\nB") == content_hash("A B")
