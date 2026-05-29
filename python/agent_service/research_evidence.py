from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, Field


TRACKING_QUERY_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
}


class EvidenceSource(BaseModel):
    source_id: str
    title: str
    url: str
    source_type: str
    accepted: bool
    score: float
    snippet: str = ""
    content_excerpt: str = ""
    content_hash: str | None = None
    observed_date: str | None = None
    rejection_reason: str | None = None


class ResearchEvidenceSet(BaseModel):
    question: str
    accepted_sources: list[EvidenceSource] = Field(default_factory=list)
    rejected_sources: list[EvidenceSource] = Field(default_factory=list)
    duplicate_sources: list[EvidenceSource] = Field(default_factory=list)
    failed_reads: list[dict[str, str]] = Field(default_factory=list)


def normalize_source_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_PARAMS
    ]
    query.sort(key=lambda item: item[0])
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path,
            urlencode(query, doseq=True),
            "",
        )
    )


def content_hash(text: str) -> str:
    normalized = " ".join(text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def evidence_from_search_results(
    question: str,
    results: list[dict[str, Any]],
) -> ResearchEvidenceSet:
    evidence = ResearchEvidenceSet(question=question)
    seen_urls: set[str] = set()
    for index, result in enumerate(results, start=1):
        url = str(_get(result, "url", ""))
        normalized_url = normalize_source_url(url)
        accepted = _accepted_flag(result)
        source = EvidenceSource(
            source_id=f"S{index}",
            title=str(_get(result, "title", "")),
            url=url,
            source_type=str(_get(result, "source_type", _get(result, "sourceType", "web"))),
            accepted=accepted,
            score=_score_result(result, accepted),
            snippet=str(_get(result, "snippet", "")),
            observed_date=_optional_str(_get(result, "observed_date", None)),
            rejection_reason=_optional_str(_get(result, "rejection_reason", None)),
        )
        if normalized_url in seen_urls:
            evidence.duplicate_sources.append(
                source.model_copy(update={"accepted": False, "rejection_reason": "duplicate_url"})
            )
            continue
        seen_urls.add(normalized_url)
        if accepted:
            evidence.accepted_sources.append(source)
        else:
            evidence.rejected_sources.append(source)
    return evidence


def citation_ids_in_markdown(markdown: str) -> set[str]:
    return {f"S{match}" for match in re.findall(r"\[S(\d+)\]", markdown)}


def validate_citation_coverage(
    markdown: str,
    evidence_set: ResearchEvidenceSet,
) -> list[str]:
    diagnostics: list[str] = []
    if not evidence_set.accepted_sources:
        diagnostics.append("no_accepted_sources")
    accepted_ids = {source.source_id for source in evidence_set.accepted_sources}
    cited_ids = citation_ids_in_markdown(markdown)
    if accepted_ids and not (accepted_ids & cited_ids):
        diagnostics.append("missing_citations")
    return diagnostics


def _accepted_flag(result: dict[str, Any]) -> bool:
    if "accepted" in result:
        return bool(result["accepted"])
    if "accepted" in getattr(result, "__dict__", {}):
        return bool(getattr(result, "accepted"))
    return _score_result(result, True) >= 0.35


def _score_result(result: dict[str, Any], accepted: bool) -> float:
    if not accepted:
        return 0.0
    title = str(_get(result, "title", ""))
    snippet = str(_get(result, "snippet", ""))
    url = str(_get(result, "url", ""))
    score = 0.2
    if title.strip():
        score += 0.25
    if len(snippet.strip()) >= 20:
        score += 0.25
    if url.startswith("https://"):
        score += 0.2
    if any(marker in url for marker in (".gov", ".edu", "official", "docs")):
        score += 0.1
    return min(score, 1.0)


def _get(result: Any, key: str, default: Any = None) -> Any:
    if isinstance(result, dict):
        return result.get(key, default)
    return getattr(result, key, default)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
