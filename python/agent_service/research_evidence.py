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


class EvidenceRef(BaseModel):
    source_id: str
    title: str
    url: str


class ResearchClaim(BaseModel):
    claim_id: str
    text: str
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


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
            observed_date=_optional_str(
                _get(result, "observed_date", _get(result, "observedDate", None))
            ),
            rejection_reason=_optional_str(
                _get(result, "rejection_reason", _get(result, "rejectionReason", None))
            ),
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


def attach_read_content(
    evidence_set: ResearchEvidenceSet | dict[str, Any],
    read_payloads: list[dict[str, Any]],
    failed_reads: list[dict[str, Any]],
) -> ResearchEvidenceSet:
    evidence = (
        evidence_set
        if isinstance(evidence_set, ResearchEvidenceSet)
        else ResearchEvidenceSet.model_validate(evidence_set)
    )
    accepted_sources = list(evidence.accepted_sources)
    source_indexes_by_url = {
        normalize_source_url(source.url): index
        for index, source in enumerate(accepted_sources)
    }

    for payload in read_payloads:
        if str(_get(payload, "readStatus", _get(payload, "status", ""))) != "read":
            continue
        url = str(_get(payload, "url", ""))
        normalized_url = normalize_source_url(url)
        source_index = source_indexes_by_url.get(normalized_url)
        if source_index is None:
            continue
        content = str(_get(payload, "sourceContent", _get(payload, "content", "")))
        if not content.strip():
            continue
        accepted_sources[source_index] = accepted_sources[source_index].model_copy(
            update={
                "content_excerpt": _content_excerpt(content),
                "content_hash": content_hash(content),
            }
        )

    return evidence.model_copy(
        update={
            "accepted_sources": accepted_sources,
            "failed_reads": [_failed_read_payload(item) for item in failed_reads],
        }
    )


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


def research_claims_from_markdown(
    markdown: str,
    evidence_set: ResearchEvidenceSet,
) -> list[ResearchClaim]:
    accepted_sources = {
        source.source_id: source
        for source in evidence_set.accepted_sources
    }
    claims: list[ResearchClaim] = []
    active_section: str | None = None
    has_sections = any(line.strip().startswith("## ") for line in markdown.splitlines())
    for line in markdown.splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith("## "):
            active_section = text.removeprefix("## ").strip().lower()
            continue
        if text.startswith("#"):
            continue
        if has_sections and active_section not in {"key findings", "project summaries"}:
            continue
        text = text.removeprefix("- ").strip()
        if not text or text.lower().startswith("question:"):
            continue
        if text.lower().startswith(("source:", "references", "s1:", "s2:", "s3:")):
            continue
        cited_ids = citation_ids_in_markdown(text)
        refs = [
            EvidenceRef(
                source_id=source.source_id,
                title=source.title,
                url=source.url,
            )
            for source_id, source in sorted(accepted_sources.items())
            if source_id in cited_ids
        ]
        diagnostics = [] if refs else ["missing_evidence"]
        claims.append(
            ResearchClaim(
                claim_id=f"C{len(claims) + 1}",
                text=text,
                evidence_refs=refs,
                diagnostics=diagnostics,
            )
        )
    return claims


def claim_level_citation_diagnostics(
    markdown: str,
    evidence_set: ResearchEvidenceSet,
) -> list[str]:
    diagnostics: list[str] = []
    for claim in research_claims_from_markdown(markdown, evidence_set):
        if "missing_evidence" in claim.diagnostics:
            diagnostics.append(f"claim_{claim.claim_id}_missing_evidence")
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


def _content_excerpt(text: str, *, limit: int = 600) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _failed_read_payload(item: dict[str, Any]) -> dict[str, str]:
    return {
        "ref": str(_get(item, "ref", "")),
        "url": str(_get(item, "url", "")),
        "error": str(_get(item, "error", _get(item, "message", ""))),
    }
