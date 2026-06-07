from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import os
from pathlib import Path
import sys
from collections.abc import Callable, Iterable, Mapping
import socket
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agent_service.harness_errors import HarnessError
from agent_service.schema_validation import validate_json_schema_subset
from agent_service.tool_providers.web_search import default_search_provider
from agent_service.tool_registry import ToolRegistry
from agent_service.tool_runtime import ToolRuntimeLoader
from agent_service.web_search import SearchFailure, SearchResult
from tools.markitdown_tool import convert_local_file as convert_markitdown_local_file
from tools.typst_tool import compile_report_pdf as compile_typst_report_pdf


def _default_tool_packages_root() -> Path:
    return default_tool_packages_root()


def default_tool_packages_root() -> Path:
    return resolve_tool_packages_root(_tool_packages_root_candidates())


def resolve_tool_packages_root(candidates: Iterable[Path]) -> Path:
    candidate_list = list(candidates)
    for candidate in candidate_list:
        if _contains_tool_manifests(candidate):
            return candidate

    if candidate_list:
        return candidate_list[-1]

    return Path(__file__).resolve().parents[2] / "tool-packages"


def _tool_packages_root_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured_root = os.getenv("ALITA_TOOL_PACKAGES_ROOT", "").strip()
    if configured_root:
        candidates.append(Path(configured_root))

    pyinstaller_root = getattr(sys, "_MEIPASS", None)
    if pyinstaller_root:
        candidates.append(Path(pyinstaller_root) / "tool-packages")

    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "tool-packages")

    candidates.append(Path(__file__).resolve().parents[2] / "tool-packages")
    candidates.append(Path.cwd() / "tool-packages")
    return candidates


def _contains_tool_manifests(path: Path) -> bool:
    return any(path.glob("*/manifest.json"))


@dataclass(frozen=True)
class ToolInvocation:
    tool_id: str
    operation: str
    arguments: dict[str, object]
    project_path: str
    allowed_roots: list[str] = field(default_factory=list)
    timeout_ms: int | None = None


@dataclass(frozen=True)
class ToolResult:
    values: dict[str, object] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


ToolAdapter = Callable[[ToolInvocation], ToolResult]
ToolAdapterKey = tuple[str, str]


def _run_markitdown(invocation: ToolInvocation) -> ToolResult:
    result = convert_markitdown_local_file(
        input_path=str(invocation.arguments["input_path"]),
        output_path=str(invocation.arguments["output_path"]),
        project_path=invocation.project_path,
        allowed_roots=invocation.allowed_roots,
    )

    return ToolResult(
        values={"text": result.text},
        artifacts=result.artifacts,
        metadata=result.metadata,
    )


def _run_typst(invocation: ToolInvocation) -> ToolResult:
    result = compile_typst_report_pdf(
        title=str(invocation.arguments["title"]),
        outline=str(invocation.arguments["outline"]),
        report=str(invocation.arguments["report"]),
        source_output_path=str(invocation.arguments["source_output_path"]),
        pdf_output_path=str(invocation.arguments["pdf_output_path"]),
        project_path=invocation.project_path,
        allowed_roots=invocation.allowed_roots,
    )

    return ToolResult(
        values={"source": result.source_path, "artifact": result.pdf_path},
        artifacts=result.artifacts,
        metadata=result.metadata,
    )


def _run_receive_attachment(invocation: ToolInvocation) -> ToolResult:
    return ToolResult(values={"paths": str(invocation.arguments.get("paths", ""))})


def _run_web_search(invocation: ToolInvocation) -> ToolResult:
    queries = _web_search_queries(invocation.arguments)
    max_results = _positive_int(invocation.arguments.get("max_results"), default=8)
    if not queries:
        raise HarnessError("invalid_tool_input", "web search query is required")

    provider = default_search_provider()
    results: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    provider_metadata: list[dict[str, object]] = []
    for query in queries:
        response = provider.search(query)
        provider_metadata.append({"query": query, **dict(response.metadata)})
        results.extend(
            _search_result_payload(result, query=query)
            for result in response.results[:max_results]
        )
        if response.failure is not None:
            failures.append(_search_failure_payload(query, response.failure))

    return ToolResult(
        values={
            "query": queries[0],
            "queries": queries,
            "results": results,
            "acceptedSources": results,
            "failures": failures,
            "providerMetadata": provider_metadata,
        },
        metadata={
            "queryCount": len(queries),
            "resultCount": len(results),
            "failureCount": len(failures),
        },
    )


def _run_web_fetch_sources(invocation: ToolInvocation) -> ToolResult:
    sources = _web_sources(invocation.arguments.get("sources"))
    max_sources = _positive_int(invocation.arguments.get("max_sources"), default=5)
    if not sources:
        raise HarnessError("invalid_tool_input", "web sources are required")

    selected_sources = sources[:max_sources]
    source_contents: list[dict[str, object]] = []
    failed_reads: list[dict[str, str]] = []
    for index, source in enumerate(selected_sources, start=1):
        url = str(source.get("url") or "").strip()
        title = str(source.get("title") or "").strip()
        ref = str(source.get("ref") or index)
        if not url:
            failed_reads.append(
                {"ref": ref, "url": "", "error": "source url is missing"}
            )
            continue

        try:
            text = _fetch_web_source_text(url, timeout=_timeout_seconds(invocation))
            status = "read" if text else "empty"
            error_message = ""
        except (HTTPError, URLError, TimeoutError, socket.timeout, OSError) as error:
            text = ""
            status = "failed"
            error_message = str(error)
        except Exception as error:
            text = ""
            status = "failed"
            error_message = str(error)

        truncated_text = _truncate_source_content(text)
        content = {
            **source,
            "ref": ref,
            "title": title,
            "url": url,
            "status": status,
            "content": truncated_text,
            "text": truncated_text,
        }
        if error_message:
            content["readError"] = error_message
            failed_reads.append({"ref": ref, "url": url, "error": error_message})
        source_contents.append(content)

    joined_text = "\n\n".join(
        str(content.get("text") or "")
        for content in source_contents
        if content.get("text")
    )
    return ToolResult(
        values={
            "sources": selected_sources,
            "sourceContents": source_contents,
            "failedSourceReads": failed_reads,
            "text": joined_text,
        },
        metadata={
            "sourceCount": len(selected_sources),
            "readSourceCount": sum(
                1 for content in source_contents
                if content.get("status") == "read"
            ),
            "failedSourceReadCount": len(failed_reads),
        },
    )


class ToolExecutor:
    def __init__(
        self,
        *,
        registry: ToolRegistry | None = None,
        adapters: Mapping[ToolAdapterKey, ToolAdapter] | None = None,
    ) -> None:
        self.registry = registry or ToolRegistry.from_packages_root(
            _default_tool_packages_root()
        )
        self.adapters: dict[ToolAdapterKey, ToolAdapter] = {
            (
                "document.receive_attachment",
                "receive_attachment",
            ): _run_receive_attachment,
            ("document.markitdown_convert", "convert_local_file"): _run_markitdown,
            ("document.typst_compile", "compile_report_pdf"): _run_typst,
            ("web.search.parallel", "search"): _run_web_search,
            ("web.fetch.sources", "fetch_sources"): _run_web_fetch_sources,
        }
        self.adapters.update(adapters or {})
        self.runtime_loader = ToolRuntimeLoader(adapters=self.adapters)

    def run(self, invocation: ToolInvocation) -> ToolResult:
        try:
            manifest = self.registry.get(invocation.tool_id)
        except KeyError as exc:
            raise HarnessError(
                "unsupported_tool", f"unsupported tool: {invocation.tool_id}"
            ) from exc

        if not self.registry.has_operation(invocation.tool_id, invocation.operation):
            raise HarnessError(
                "unsupported_operation",
                f"unsupported operation for {invocation.tool_id}: {invocation.operation}",
            )

        arguments = {"operation": invocation.operation, **invocation.arguments}
        try:
            validate_json_schema_subset(manifest.input_schema, arguments)
        except ValueError as exc:
            raise HarnessError("invalid_tool_input", str(exc)) from exc

        return self.runtime_loader.run(manifest, invocation)


def _web_search_queries(arguments: dict[str, object]) -> list[str]:
    queries: list[str] = []
    raw_queries = arguments.get("queries")
    if isinstance(raw_queries, list):
        queries.extend(str(query).strip() for query in raw_queries if str(query).strip())
    elif isinstance(raw_queries, str) and raw_queries.strip():
        queries.extend(line.strip() for line in raw_queries.splitlines() if line.strip())

    query = str(arguments.get("query") or "").strip()
    if query:
        queries.insert(0, query)

    seen: set[str] = set()
    deduped: list[str] = []
    for query in queries:
        if query in seen:
            continue
        seen.add(query)
        deduped.append(query)
    return deduped


def _web_sources(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []

    sources: list[dict[str, object]] = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, dict):
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            sources.append(
                {
                    "ref": str(item.get("ref") or index),
                    "title": str(item.get("title") or ""),
                    "url": url,
                    "snippet": str(item.get("snippet") or ""),
                    **{
                        key: val
                        for key, val in item.items()
                        if key not in {"ref", "title", "url", "snippet"}
                    },
                }
            )
            continue

        url = str(item).strip()
        if url:
            sources.append({"ref": str(index), "title": url, "url": url, "snippet": ""})
    return sources


def _positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _timeout_seconds(invocation: ToolInvocation) -> float:
    if invocation.timeout_ms is None:
        return 8.0
    return max(1.0, min(15.0, invocation.timeout_ms / 1000))


def _search_result_payload(
    result: SearchResult,
    *,
    query: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": result.title,
        "url": result.url,
        "snippet": result.snippet,
        "query": query,
    }
    if result.sourceType is not None:
        payload["sourceType"] = result.sourceType
    if result.accepted is not None:
        payload["accepted"] = result.accepted
    if result.rejectionReason is not None:
        payload["rejectionReason"] = result.rejectionReason
    return payload


def _search_failure_payload(query: str, failure: SearchFailure) -> dict[str, object]:
    return {
        "query": query,
        "kind": failure.kind,
        "message": failure.message,
        "blocked": failure.blocked,
        "removedCategories": failure.removedCategories,
    }


def _fetch_web_source_text(url: str, *, timeout: float) -> str:
    request = Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; alita-web-fetch/1.0)"},
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(250_000)
        content_type = response.headers.get("Content-Type", "")
        charset = response.headers.get_content_charset() or "utf-8"
    text = raw.decode(charset, errors="replace")
    if "html" in content_type.lower() or "<html" in text[:1000].lower():
        return _extract_text_from_html(text)
    return _normalize_source_text(text)


def _extract_text_from_html(html: str) -> str:
    parser = _ReadableHtmlParser()
    parser.feed(html)
    parser.close()
    return _normalize_source_text(" ".join(parser.text_parts))


def _normalize_source_text(text: str) -> str:
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _truncate_source_content(text: str, *, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n[truncated]"


class _ReadableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = " ".join(data.split())
        if text:
            self.text_parts.append(text)
