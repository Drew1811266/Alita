# Agent Runtime Phase I Evidence-Driven Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade research execution from snippet stitching to source-grounded evidence synthesis with deterministic citation and quality gates.

**Architecture:** Add `research_evidence.py` as a pure evidence layer used by `web_research.py` and `ResearchFlowExecutor`. Search results become `ResearchEvidenceSet` records with accepted, rejected, duplicate, and failed-read sources. Report synthesis remains deterministic-first in this phase: generated Markdown must cite accepted source IDs and quality checks fail reports with no accepted sources or no citations. Public research event payloads remain compatible.

**Tech Stack:** Python 3.12, Pydantic v2, existing `SearchProvider`/`SearchResult`, existing `ResearchFlowExecutor`, pytest.

---

## Current Baseline

- `web_research.py` builds research graphs and quick answers.
- `ResearchFlowExecutor` handles privacy guard, query plan, search, source review, source reading, report synthesis, quality check, and Markdown output.
- Source reading stores `sourceContent`, `readStatus`, and failed read details.
- Current report synthesis can still rely too heavily on snippets and deterministic string composition.

## Non-Goals

- Do not add browser automation.
- Do not add paid search APIs.
- Do not change `research.completed` payload fields.
- Do not add long-running durable research jobs.
- Do not require network in tests.
- Do not add frontend UI changes in Phase I.

## Files

### Create

- `python/agent_service/research_evidence.py`
  - Defines evidence source and evidence set models.
  - Deduplicates sources by normalized URL and content hash.
  - Scores accepted/rejected sources deterministically.
  - Validates citation coverage in Markdown.
- `python/tests/test_research_evidence.py`
  - Tests deduplication, scoring, content hashing, citation coverage, and quality failures.

### Modify

- `python/agent_service/web_research.py`
  - Use evidence helpers for quick answer source payloads where compatible.
  - Keep existing source payload shape.
- `python/agent_service/execution.py`
  - Use evidence helpers in `ResearchFlowExecutor` source review, source reading, report synthesis, and quality check.
- `python/agent_service/web_search.py`
  - Add small URL normalization helper only if needed by evidence dedupe.
- `python/tests/test_web_research.py`
  - Add source-grounded report tests.
- `python/tests/test_agent_routing_integration.py`
  - Assert existing research event compatibility.

---

## Design Contract

Create `python/agent_service/research_evidence.py`:

```python
from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, Field


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
```

Required helpers:

- `normalize_source_url(url: str) -> str`
  - Lowercase scheme/host.
  - Drop fragment.
  - Drop common tracking params: `utm_source`, `utm_medium`, `utm_campaign`, `utm_term`, `utm_content`, `fbclid`, `gclid`.
- `content_hash(text: str) -> str`
  - Return SHA-256 hex digest of normalized text.
- `evidence_from_search_results(question: str, results: list[dict[str, Any]]) -> ResearchEvidenceSet`
  - Build deterministic source IDs in order: `S1`, `S2`, `S3`, then increment for each additional source.
  - Mark duplicate normalized URLs as duplicate sources.
  - Score sources using existing accepted flag when present; otherwise use title/snippet/url quality.
- `attach_read_content(evidence_set, read_payloads, failed_reads) -> ResearchEvidenceSet`
  - Add `content_excerpt` and `content_hash` to accepted sources.
- `citation_ids_in_markdown(markdown: str) -> set[str]`
  - Find citations like `[S1]`, `[S2]`.
- `validate_citation_coverage(markdown: str, evidence_set: ResearchEvidenceSet) -> list[str]`
  - Return diagnostics such as `missing_citations` and `no_accepted_sources`.

---

## Task 0: Baseline Verification

**Files:**
- Read: `python/agent_service/web_research.py`
- Read: `python/agent_service/execution.py`
- Read: `python/tests/test_web_research.py`

- [ ] **Step 1: Run current research baseline**

Run:

```powershell
python -m pytest -q python\tests\test_web_research.py python\tests\test_agent_routing_integration.py
```

Expected:

```text
... passed
```

---

## Task 1: Evidence Models And Deduplication

**Files:**
- Create: `python/agent_service/research_evidence.py`
- Create: `python/tests/test_research_evidence.py`

- [ ] **Step 1: Write failing evidence tests**

Create `python/tests/test_research_evidence.py`:

```python
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
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_research_evidence.py
```

Expected:

```text
ModuleNotFoundError: No module named 'agent_service.research_evidence'
```

- [ ] **Step 3: Implement evidence module**

Implement the design contract in `python/agent_service/research_evidence.py`. Keep all functions pure and network-free.

- [ ] **Step 4: Run evidence tests**

Run:

```powershell
python -m pytest -q python\tests\test_research_evidence.py
```

Expected:

```text
4 passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/research_evidence.py python/tests/test_research_evidence.py
git commit -m "feat: add research evidence set"
```

---

## Task 2: Source Reading And Evidence Attachment

**Files:**
- Modify: `python/agent_service/research_evidence.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/tests/test_research_evidence.py`
- Modify: `python/tests/test_web_research.py`

- [ ] **Step 1: Add read content attachment test**

Append to `python/tests/test_research_evidence.py`:

```python
from agent_service.research_evidence import attach_read_content


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
```

- [ ] **Step 2: Run new test and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_research_evidence.py::test_attach_read_content_adds_excerpt_and_hash
```

Expected:

```text
ImportError: cannot import name 'attach_read_content'
```

- [ ] **Step 3: Implement `attach_read_content()`**

Implement matching by normalized URL and copy failed reads into `ResearchEvidenceSet.failed_reads`.

- [ ] **Step 4: Wire source review/read outputs**

In `ResearchFlowExecutor`:

- In `research-source-review`, include `evidenceSet` as `ResearchEvidenceSet.model_dump()` while preserving `acceptedSources` and `rejectedSources`.
- In `research-source-reading`, update `evidenceSet` with read content and failed reads while preserving existing `sourceContents`/`failedReads` values.

- [ ] **Step 5: Run research tests**

Run:

```powershell
python -m pytest -q python\tests\test_research_evidence.py python\tests\test_web_research.py
```

Expected:

```text
... passed
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add python/agent_service/research_evidence.py python/agent_service/execution.py python/tests/test_research_evidence.py python/tests/test_web_research.py
git commit -m "feat: attach read content to research evidence"
```

---

## Task 3: Citation-Grounded Report Synthesis

**Files:**
- Modify: `python/agent_service/execution.py`
- Modify: `python/tests/test_web_research.py`

- [ ] **Step 1: Add citation report test**

Append to `python/tests/test_execution.py` near the existing research flow tests:

```python
def test_research_report_synthesis_includes_source_citations(tmp_path: Path) -> None:
    question = "Compare current Python packaging tools"
    request = build_research_flow_request(tmp_path, question)
    provider = SequencedSearchProvider(
        {
            question: [
                SearchResponse(
                    results=[
                        SearchResult(
                            title="Python packaging user guide",
                            url="https://packaging.python.org/en/latest/",
                            snippet="Official guide to Python packaging tools.",
                        )
                    ]
                )
            ],
            f"{question} official sources": [SearchResponse(results=[])],
        }
    )
    source_fetcher = FakeSourceFetcher(
        {
            "https://packaging.python.org/en/latest/": (
                "The Python Packaging User Guide explains pip, build backends, "
                "publishing workflows, and modern project metadata."
            )
        }
    )

    events = list(
        run_graph_events(
            request,
            search_provider=provider,
            source_fetcher=source_fetcher,
        )
    )

    artifact_event = next(event for event in events if event.type == "artifact.created")
    report = Path(artifact_event.payload["path"]).read_text(encoding="utf-8")

    assert "[S1]" in report
    assert "## References" in report
    assert "S1" in report
    assert "https://packaging.python.org/en/latest/" in report
```

Do not use live network.

- [ ] **Step 2: Run test and verify failure**

Run the new test directly:

```powershell
python -m pytest -q python\tests\test_execution.py::test_research_report_synthesis_includes_source_citations
```

Expected:

```text
FAILED
```

- [ ] **Step 3: Update deterministic report synthesis**

In `ResearchFlowExecutor._synthesize_report()` or the current report synthesis branch:

- Read `evidenceSet` when present.
- For each accepted source, include at least one claim with `[S{n}]`.
- Always emit a references section mapping `S{n}` to title and URL.
- Preserve existing section order from `REPORT_SECTION_ORDER`.

- [ ] **Step 4: Update quality check**

In `research-report-quality-check`:

- Call `validate_citation_coverage(report, evidence_set)`.
- Add diagnostics to existing quality payload.
- Fail or flag `qualityStatus="needs_revision"` when diagnostics are non-empty.

- [ ] **Step 5: Run research regression**

Run:

```powershell
python -m pytest -q python\tests\test_research_evidence.py python\tests\test_web_research.py python\tests\test_agent_routing_integration.py
```

Expected:

```text
... passed
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add python/agent_service/execution.py python/tests/test_web_research.py
git commit -m "feat: synthesize cited research reports"
```

---

## Task 4: Final Regression And Review

**Files:**
- Read: `python/agent_service/research_evidence.py`
- Read: `python/agent_service/execution.py`
- Read: `python/agent_service/web_research.py`
- Read: `python/tests/test_research_evidence.py`
- Read: `python/tests/test_web_research.py`

- [ ] **Step 1: Run Phase I focused tests**

Run:

```powershell
python -m pytest -q python\tests\test_research_evidence.py python\tests\test_web_research.py python\tests\test_agent_routing_integration.py
```

Expected:

```text
... passed
```

- [ ] **Step 2: Run web provider and privacy regressions**

Run:

```powershell
python -m pytest -q python\tests\test_web_provider_chain.py python\tests\test_web_search.py python\tests\test_privacy.py
```

Expected:

```text
... passed
```

- [ ] **Step 3: Run full MVP verification**

Run:

```powershell
.\scripts\verify-mvp.ps1
```

Expected:

```text
MVP verification passed.
```

- [ ] **Step 4: Final code review**

Dispatch final review:

```text
Review Phase I Evidence-Driven Research implementation. Prioritize source deduplication, citation coverage, no-network tests, research.completed payload compatibility, quality check behavior, privacy guard preservation, and whether implementation avoids frontend, memory, durable execution, or broad browser automation scope.
```

Expected: reviewer returns no critical or important findings. Fix any critical or important finding before finishing Phase I.

---

## Acceptance Criteria

Phase I is complete when all statements are true:

- `python/agent_service/research_evidence.py` exists and is tested.
- Research evidence deduplicates sources.
- Accepted, rejected, duplicate, and failed-read sources are visible internally.
- Research reports include citations for accepted sources.
- Quality checks catch missing citations and no accepted sources.
- `research.completed` event payload remains compatible.
- Tests do not require live network.
- `.\scripts\verify-mvp.ps1` passes.

## Handoff Notes For Phase J

Phase J can use evidence-driven research behavior in deterministic eval cases. It should use fake search/source providers and must not require network access.
