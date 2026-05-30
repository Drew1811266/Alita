from __future__ import annotations

from agent_service.research_evidence import (
    attach_read_content,
    claim_level_citation_diagnostics,
    citation_ids_in_markdown,
    content_hash,
    evidence_from_search_results,
    research_claims_from_markdown,
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


def test_attach_read_content_adds_excerpt_and_hash() -> None:
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

    updated = attach_read_content(
        evidence,
        [
            {
                "url": "https://example.com/a",
                "sourceContent": "Long source content " * 80,
                "readStatus": "read",
            }
        ],
        [],
    )

    source = updated.accepted_sources[0]
    assert source.content_hash
    assert source.content_excerpt.startswith("Long source content")
    assert len(source.content_excerpt) <= 600


def test_research_claims_report_claims_without_evidence_refs() -> None:
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

    claims = research_claims_from_markdown(
        "Supported claim [S1].\n\nUnsupported claim.",
        evidence,
    )

    assert claims[0].claim_id == "C1"
    assert claims[0].evidence_refs[0].source_id == "S1"
    assert claims[0].diagnostics == []
    assert claims[1].claim_id == "C2"
    assert claims[1].diagnostics == ["missing_evidence"]
    assert claim_level_citation_diagnostics(
        "Supported claim [S1].\n\nUnsupported claim.",
        evidence,
    ) == ["claim_C2_missing_evidence"]


def test_research_claims_bind_to_source_excerpts() -> None:
    evidence = attach_read_content(
        evidence_from_search_results(
            "Question",
            [
                {
                    "title": "Accepted",
                    "url": "https://example.com/a",
                    "snippet": "Useful.",
                    "accepted": True,
                }
            ],
        ),
        [
            {
                "url": "https://example.com/a",
                "sourceContent": "The package guide explains build backends and project metadata.",
                "readStatus": "read",
            }
        ],
        [],
    )

    claims = research_claims_from_markdown(
        "## Key Findings\n\n- Python packaging uses build backends [S1].",
        evidence,
    )

    assert claims[0].support_status == "supported"
    assert claims[0].evidence_refs[0].excerpt.startswith("The package guide")
    assert claims[0].evidence_refs[0].support_status == "supports"
