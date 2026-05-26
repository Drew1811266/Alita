# Unified Agent Tool Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Alita's unified Agent tool protocol so internal node tools and external MCP tools are managed through one catalog, one gateway, one permission model, and one audit trail.

**Architecture:** Keep Alita's internal Tool Gateway as the safety and execution kernel. Add provider-based tool discovery with `InternalToolProvider` and `McpToolProvider`, normalize all tools into unified definitions, and add model-provider tool-calling adapters plus an optional Alita MCP server in later phases. Each phase ends with a strict audit gate; passing the gate automatically unlocks the next phase.

**Tech Stack:** Python FastAPI/Pydantic/pytest, React 19, TypeScript, Vitest, Tauri 2, Rust, MCP JSON-RPC style client/server abstractions, existing Alita sidecar and Preferences systems.

---

## Continuous Execution Rules

This is a single continuous implementation effort on one branch.

After each phase:

1. Run all phase-specific tests listed in that phase.
2. Run the required affected-suite checks.
3. Create or update the phase audit note in `docs/superpowers/audits/2026-05-25-unified-agent-tool-protocol-phase-N.md`.
4. Commit the phase implementation and audit note only if every required check passes.
5. Continue automatically to the next phase after the commit.

If any check fails:

- Do not continue to the next phase.
- Fix the failure inside the same phase.
- Re-run the full phase audit.
- Commit only after the audit passes.

Required audit note format:

```markdown
# Unified Agent Tool Protocol Phase N Audit

## Scope Reviewed

- [list concrete files/features reviewed]

## Verification Commands

- [command] -> [pass/fail and key counts]

## Acceptance Criteria

- [x] Criterion 1
- [x] Criterion 2

## Security Review

- [x] Secrets are not persisted outside credential storage.
- [x] Raw provider errors are sanitized.
- [x] Tool calls pass through the Unified Tool Gateway.

## Decision

PASS. Continue to Phase N+1.
```

For Phase 5, the decision line is:

```markdown
PASS. Unified Agent Tool Protocol implementation complete.
```

## File Structure

Create or modify these files over the full implementation:

- `python/agent_service/tool_protocol.py`: unified tool definition, invocation, result, error, safety policy, and provider protocol models.
- `python/agent_service/tool_providers/internal.py`: provider wrapper for existing `ToolRegistry` and internal adapters.
- `python/agent_service/tool_providers/mcp.py`: MCP client provider abstraction, discovery, invocation, result mapping.
- `python/agent_service/tool_gateway.py`: unified execution gateway with validation, permission checks, provider dispatch, result normalization.
- `python/agent_service/tool_registry.py`: compatibility layer that can expose existing manifests as unified definitions.
- `python/agent_service/tool_execution.py`: compatibility adapter from existing `ToolInvocation -> ToolResult` to unified gateway.
- `python/agent_service/tool_resolver.py`: task-context-based tool filtering for planning and routing.
- `python/agent_service/model_tool_adapter.py`: conversion from unified tool definitions to model-provider tool schemas.
- `python/agent_service/mcp_server.py`: optional Alita MCP server for Phase 5.
- `python/agent_service/app.py`: endpoints for MCP provider discovery, optional MCP server lifecycle, and gateway-backed tool calls where needed.
- `python/agent_service/schemas.py`: API schemas for unified tools, MCP provider config views, and safe tool summaries.
- `python/tests/test_tool_protocol.py`: unified protocol model tests.
- `python/tests/test_tool_gateway.py`: gateway validation, dispatch, error, and safety tests.
- `python/tests/test_mcp_tool_provider.py`: fake MCP provider discovery and call tests.
- `python/tests/test_tool_resolver.py`: planning tool filtering tests.
- `python/tests/test_model_tool_adapter.py`: provider tool-calling schema conversion tests.
- `python/tests/test_mcp_server.py`: optional Alita MCP server tests.
- `src-tauri/src/preferences.rs`: MCP provider config and tool provider preference schema.
- `src-tauri/src/api_credentials.rs`: credential storage for MCP provider secrets.
- `src-tauri/src/commands.rs`: Tauri commands for MCP provider CRUD, discovery, and safe status views.
- `src-tauri/src/lib.rs`: register new commands/modules.
- `src-tauri/tests/preferences_tests.rs`: provider config migration and persistence tests.
- `src-tauri/tests/api_credentials_tests.rs`: MCP credential target tests.
- `src-tauri/tests/tool_provider_commands_tests.rs`: MCP provider command tests.
- `src/shared/types.ts`: unified tool, provider, and MCP config types.
- `src/features/preferences/preferencesApi.ts`: provider command wrappers.
- `src/features/preferences/PreferencesDialog.tsx`: MCP server management UI.
- `src/features/preferences/PreferencesDialog.test.tsx`: UI tests for provider config and secret hiding.
- `src/features/task/useTaskEvents.ts`: include unified tool IDs in relevant graph/task payloads if needed.
- `src/app/App.tsx`: load provider/tool views and pass them to Preferences.
- `tool-packages/*/manifest.json`: add MCP-compatible field aliases where needed while preserving old fields.
- `docs/superpowers/audits/`: phase audit notes.
- `README.md`: document unified tool protocol and MCP integration.

---

## Phase 1: Unified Protocol Kernel

### Task 1.1: Add Unified Tool Protocol Models

**Files:**
- Create: `python/agent_service/tool_protocol.py`
- Create: `python/tests/test_tool_protocol.py`

- [ ] **Step 1: Write failing protocol model tests**

Add `python/tests/test_tool_protocol.py`:

```python
from agent_service.tool_protocol import (
    ToolResultContent,
    ToolSafetyPolicy,
    UnifiedToolDefinition,
    UnifiedToolError,
    UnifiedToolResult,
)


def test_unified_tool_definition_rejects_blank_id() -> None:
    try:
        UnifiedToolDefinition(
            id="",
            source="internal",
            provider_id="internal",
            provider_tool_name="document.markitdown_convert",
            display_name="MarkItDown",
            description="Convert supported local documents to Markdown.",
            capabilities=["document_conversion"],
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            permissions=["read_project_files"],
            safety_policy=ToolSafetyPolicy(
                filesystem="project_read",
                network="none",
                user_approval="never",
                secrets="none",
                sandbox="not_required",
                max_runtime_ms=60000,
            ),
            timeout_ms=60000,
            examples=[],
            enabled=True,
        )
    except ValueError as error:
        assert "tool id is required" in str(error)
    else:
        raise AssertionError("blank tool id should fail")


def test_unified_tool_result_sanitizes_error_shape() -> None:
    result = UnifiedToolResult(
        ok=False,
        content=[],
        structured_content=None,
        artifacts=[],
        metadata={},
        error=UnifiedToolError(
            code="provider_failed",
            message="provider failed",
            recoverable=True,
            safe_details={"status": 502},
        ),
    )

    assert result.error is not None
    assert result.error.code == "provider_failed"
    assert result.error.safe_details == {"status": 502}


def test_text_result_content_preserves_text() -> None:
    content = ToolResultContent(type="text", text="converted text")

    assert content.type == "text"
    assert content.text == "converted text"
```

- [ ] **Step 2: Run failing test**

Run:

```powershell
python -m pytest tests/test_tool_protocol.py -q
```

Expected: fail because `agent_service.tool_protocol` does not exist.

- [ ] **Step 3: Implement protocol models**

Create `python/agent_service/tool_protocol.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


JsonObject = dict[str, Any]
ToolSource = Literal["internal", "mcp"]
FilesystemPolicy = Literal[
    "none", "project_read", "project_write", "external_read", "external_write"
]
NetworkPolicy = Literal["none", "provider_declared", "any"]
ApprovalPolicy = Literal["never", "before_call", "high_risk_only"]
SecretsPolicy = Literal["none", "provider_managed", "user_configured"]
SandboxPolicy = Literal["not_required", "required"]


@dataclass(frozen=True)
class ToolSafetyPolicy:
    filesystem: FilesystemPolicy
    network: NetworkPolicy
    user_approval: ApprovalPolicy
    secrets: SecretsPolicy
    sandbox: SandboxPolicy
    max_runtime_ms: int

    def __post_init__(self) -> None:
        if self.max_runtime_ms <= 0:
            raise ValueError("max runtime must be positive")


@dataclass(frozen=True)
class UnifiedToolDefinition:
    id: str
    source: ToolSource
    provider_id: str
    provider_tool_name: str
    display_name: str
    description: str
    capabilities: list[str]
    input_schema: JsonObject
    output_schema: JsonObject | None
    permissions: list[str]
    safety_policy: ToolSafetyPolicy
    timeout_ms: int
    examples: list[JsonObject] = field(default_factory=list)
    version: str | None = None
    node_template: JsonObject | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("tool id is required")
        if not self.provider_id.strip():
            raise ValueError("provider id is required")
        if not self.provider_tool_name.strip():
            raise ValueError("provider tool name is required")
        if self.timeout_ms <= 0:
            raise ValueError("timeout must be positive")


@dataclass(frozen=True)
class UnifiedToolInvocation:
    invocation_id: str
    run_id: str
    task_id: str
    tool_id: str
    arguments: JsonObject
    allowed_roots: list[str]
    requested_permissions: list[str]
    project_path: str | None = None
    node_id: str | None = None
    approval_token: str | None = None
    model_session_id: str | None = None


@dataclass(frozen=True)
class ToolResultContent:
    type: Literal["text", "json", "artifact", "resource_link"]
    text: str | None = None
    value: Any | None = None
    path: str | None = None
    uri: str | None = None
    title: str | None = None
    mime_type: str | None = None


@dataclass(frozen=True)
class UnifiedToolError:
    code: str
    message: str
    recoverable: bool
    safe_details: JsonObject | None = None


@dataclass(frozen=True)
class UnifiedToolResult:
    ok: bool
    content: list[ToolResultContent]
    structured_content: JsonObject | None
    artifacts: list[str]
    metadata: dict[str, str]
    error: UnifiedToolError | None = None


class ToolProvider(Protocol):
    provider_id: str
    source: ToolSource

    def list_tools(self) -> list[UnifiedToolDefinition]:
        raise NotImplementedError

    def call_tool(self, invocation: UnifiedToolInvocation) -> UnifiedToolResult:
        raise NotImplementedError
```

- [ ] **Step 4: Verify protocol model tests pass**

Run:

```powershell
python -m pytest tests/test_tool_protocol.py -q
```

Expected: `3 passed`.

### Task 1.2: Wrap Existing Internal Tools As A Provider

**Files:**
- Create: `python/agent_service/tool_providers/internal.py`
- Modify: `python/agent_service/tool_registry.py`
- Create: `python/tests/test_tool_gateway.py`

- [ ] **Step 1: Write failing internal provider tests**

Add initial tests to `python/tests/test_tool_gateway.py`:

```python
from pathlib import Path

from agent_service.tool_providers.internal import InternalToolProvider
from agent_service.tool_registry import ToolRegistry


def test_internal_provider_lists_existing_manifest_tools() -> None:
    registry = ToolRegistry.from_packages_root(Path(__file__).parents[1] / ".." / "tool-packages")
    provider = InternalToolProvider(registry=registry)

    tools = provider.list_tools()
    tool_ids = {tool.id for tool in tools}

    assert "internal:document.markitdown_convert" in tool_ids
    assert "internal:document.typst_compile" in tool_ids


def test_internal_provider_preserves_manifest_permissions() -> None:
    registry = ToolRegistry.from_packages_root(Path(__file__).parents[1] / ".." / "tool-packages")
    provider = InternalToolProvider(registry=registry)

    markitdown = next(
        tool for tool in provider.list_tools() if tool.id == "internal:document.markitdown_convert"
    )

    assert "read_project_files" in markitdown.permissions
    assert markitdown.provider_id == "internal"
    assert markitdown.source == "internal"
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
python -m pytest tests/test_tool_gateway.py -q
```

Expected: fail because `InternalToolProvider` does not exist.

- [ ] **Step 3: Implement internal provider**

Create `python/agent_service/tool_providers/internal.py`:

```python
from __future__ import annotations

from agent_service.tool_protocol import (
    ToolSafetyPolicy,
    UnifiedToolDefinition,
    UnifiedToolInvocation,
    UnifiedToolResult,
)
from agent_service.tool_registry import ToolRegistry


class InternalToolProvider:
    provider_id = "internal"
    source = "internal"

    def __init__(self, *, registry: ToolRegistry) -> None:
        self.registry = registry

    def list_tools(self) -> list[UnifiedToolDefinition]:
        tools = []
        for manifest in self.registry.enabled_tools():
            max_runtime_ms = int(manifest.timeout_policy.get("seconds", 60)) * 1000
            tools.append(
                UnifiedToolDefinition(
                    id=f"internal:{manifest.tool_id}",
                    source="internal",
                    provider_id=self.provider_id,
                    provider_tool_name=manifest.tool_id,
                    display_name=manifest.name,
                    description=manifest.description,
                    version=manifest.version,
                    capabilities=list(manifest.capabilities),
                    input_schema=dict(manifest.input_schema),
                    output_schema=dict(manifest.output_schema),
                    permissions=list(manifest.permissions),
                    safety_policy=ToolSafetyPolicy(
                        filesystem=_filesystem_policy(manifest.permissions),
                        network="provider_declared"
                        if manifest.security_policy.get("network") is True
                        else "none",
                        user_approval="high_risk_only",
                        secrets="none",
                        sandbox="not_required",
                        max_runtime_ms=max_runtime_ms,
                    ),
                    timeout_ms=max_runtime_ms,
                    examples=list(manifest.examples),
                    node_template=manifest.node_templates[0]
                    if manifest.node_templates
                    else None,
                    enabled=True,
                )
            )
        return tools

    def call_tool(self, invocation: UnifiedToolInvocation) -> UnifiedToolResult:
        raise NotImplementedError("internal execution is added through the gateway task")


def _filesystem_policy(permissions: list[str]) -> str:
    if "write_project_outputs" in permissions:
        return "project_write"
    if "read_project_files" in permissions:
        return "project_read"
    return "none"
```

- [ ] **Step 4: Verify tests pass**

Run:

```powershell
python -m pytest tests/test_tool_gateway.py tests/test_tool_protocol.py -q
```

Expected: provider listing tests and protocol tests pass.

### Task 1.3: Add Unified Gateway With Existing Execution Compatibility

**Files:**
- Create: `python/agent_service/tool_gateway.py`
- Modify: `python/agent_service/tool_execution.py`
- Modify: `python/tests/test_tool_gateway.py`

- [ ] **Step 1: Add failing gateway tests**

Append to `python/tests/test_tool_gateway.py`:

```python
from agent_service.tool_gateway import UnifiedToolGateway
from agent_service.tool_protocol import UnifiedToolInvocation


def test_gateway_rejects_unknown_tool() -> None:
    gateway = UnifiedToolGateway(providers=[])
    invocation = UnifiedToolInvocation(
        invocation_id="inv-1",
        run_id="run-1",
        task_id="task-1",
        tool_id="internal:missing.tool",
        arguments={},
        allowed_roots=[],
        requested_permissions=[],
    )

    result = gateway.call_tool(invocation)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "unsupported_tool"


def test_gateway_validates_input_schema_before_provider_call() -> None:
    registry = ToolRegistry.from_packages_root(Path(__file__).parents[1] / ".." / "tool-packages")
    provider = InternalToolProvider(registry=registry)
    gateway = UnifiedToolGateway(providers=[provider])
    invocation = UnifiedToolInvocation(
        invocation_id="inv-1",
        run_id="run-1",
        task_id="task-1",
        tool_id="internal:document.markitdown_convert",
        arguments={"operation": "convert_local_file"},
        allowed_roots=[],
        requested_permissions=["read_project_files"],
    )

    result = gateway.call_tool(invocation)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "invalid_tool_input"
```

- [ ] **Step 2: Run failing gateway tests**

Run:

```powershell
python -m pytest tests/test_tool_gateway.py -q
```

Expected: fail because `UnifiedToolGateway` does not exist.

- [ ] **Step 3: Implement minimal gateway**

Create `python/agent_service/tool_gateway.py`:

```python
from __future__ import annotations

from agent_service.schema_validation import validate_json_schema_subset
from agent_service.tool_protocol import (
    ToolProvider,
    UnifiedToolError,
    UnifiedToolInvocation,
    UnifiedToolResult,
)


class UnifiedToolGateway:
    def __init__(self, *, providers: list[ToolProvider]) -> None:
        self.providers = providers

    def list_tools(self):
        tools = []
        for provider in self.providers:
            tools.extend(provider.list_tools())
        return tools

    def call_tool(self, invocation: UnifiedToolInvocation) -> UnifiedToolResult:
        tool = next(
            (candidate for candidate in self.list_tools() if candidate.id == invocation.tool_id),
            None,
        )
        if tool is None:
            return _error("unsupported_tool", f"unsupported tool: {invocation.tool_id}")
        if not tool.enabled:
            return _error("tool_disabled", f"tool disabled: {invocation.tool_id}")
        try:
            validate_json_schema_subset(tool.input_schema, invocation.arguments)
        except ValueError as error:
            return _error("invalid_tool_input", str(error), recoverable=True)

        provider = next(
            provider for provider in self.providers if provider.provider_id == tool.provider_id
        )
        return provider.call_tool(invocation)


def _error(
    code: str,
    message: str,
    *,
    recoverable: bool = False,
) -> UnifiedToolResult:
    return UnifiedToolResult(
        ok=False,
        content=[],
        structured_content=None,
        artifacts=[],
        metadata={},
        error=UnifiedToolError(code=code, message=message, recoverable=recoverable),
    )
```

- [ ] **Step 4: Add compatibility from current internal execution**

Modify `InternalToolProvider.call_tool()` so it delegates to the existing `ToolExecutor` adapter path. Keep current `ToolExecutor.run()` API intact for existing callers during Phase 1.

Use this implementation shape:

```python
from agent_service.tool_execution import ToolExecutor, ToolInvocation
from agent_service.tool_protocol import ToolResultContent, UnifiedToolError


class InternalToolProvider:
    def __init__(self, *, registry: ToolRegistry, executor: ToolExecutor | None = None) -> None:
        self.registry = registry
        self.executor = executor or ToolExecutor(registry=registry)

    def call_tool(self, invocation: UnifiedToolInvocation) -> UnifiedToolResult:
        provider_tool_id = invocation.tool_id.removeprefix("internal:")
        try:
            result = self.executor.run(
                ToolInvocation(
                    tool_id=provider_tool_id,
                    operation=str(invocation.arguments.get("operation", "")),
                    arguments={
                        key: value
                        for key, value in invocation.arguments.items()
                        if key != "operation"
                    },
                    project_path=invocation.project_path or "",
                    allowed_roots=invocation.allowed_roots,
                )
            )
        except Exception as error:
            return UnifiedToolResult(
                ok=False,
                content=[],
                structured_content=None,
                artifacts=[],
                metadata={},
                error=UnifiedToolError(
                    code=getattr(error, "code", "tool_failed"),
                    message=str(error),
                    recoverable=False,
                ),
            )

        return UnifiedToolResult(
            ok=True,
            content=[
                ToolResultContent(type="json", value=result.values),
                *[
                    ToolResultContent(type="artifact", path=artifact)
                    for artifact in result.artifacts
                ],
            ],
            structured_content=dict(result.values),
            artifacts=list(result.artifacts),
            metadata=dict(result.metadata),
        )
```

- [ ] **Step 5: Verify Phase 1 target tests**

Run:

```powershell
python -m pytest tests/test_tool_protocol.py tests/test_tool_gateway.py tests/test_tool_execution.py tests/test_tool_registry.py -q
```

Expected: all selected tests pass.

### Task 1.4: Phase 1 Audit Gate

**Files:**
- Create: `docs/superpowers/audits/2026-05-25-unified-agent-tool-protocol-phase-1.md`

- [ ] **Step 1: Run affected checks**

Run:

```powershell
python -m pytest tests/test_tool_protocol.py tests/test_tool_gateway.py tests/test_tool_execution.py tests/test_tool_registry.py -q
python -m pytest tests/test_graph.py tests/test_execution.py -q
```

Expected: all pass.

- [ ] **Step 2: Write Phase 1 audit note**

Create the audit file with:

```markdown
# Unified Agent Tool Protocol Phase 1 Audit

## Scope Reviewed

- Unified protocol models.
- Internal tool provider wrapper.
- Unified gateway validation path.
- Compatibility with existing internal tool execution.

## Verification Commands

- `python -m pytest tests/test_tool_protocol.py tests/test_tool_gateway.py tests/test_tool_execution.py tests/test_tool_registry.py -q` -> PASS.
- `python -m pytest tests/test_graph.py tests/test_execution.py -q` -> PASS.

## Acceptance Criteria

- [x] Existing internal tools appear in the unified catalog.
- [x] Unknown tools return `unsupported_tool`.
- [x] Invalid inputs return `invalid_tool_input`.
- [x] Existing graph and execution tests still pass.

## Security Review

- [x] Tool calls pass through the Unified Tool Gateway in the new path.
- [x] Existing path validation remains in internal tool adapters.
- [x] No secrets are introduced in Phase 1.

## Decision

PASS. Continue to Phase 2.
```

- [ ] **Step 3: Commit Phase 1**

Run:

```powershell
git add python/agent_service/tool_protocol.py python/agent_service/tool_gateway.py python/agent_service/tool_providers/internal.py python/tests/test_tool_protocol.py python/tests/test_tool_gateway.py docs/superpowers/audits/2026-05-25-unified-agent-tool-protocol-phase-1.md
git commit -m "feat: add unified tool protocol kernel"
```

Expected: commit succeeds. Continue automatically to Phase 2.

---

## Phase 2: MCP Client Provider

### Task 2.1: Add MCP Provider Protocol And Fake Client

**Files:**
- Create: `python/agent_service/tool_providers/mcp.py`
- Create: `python/tests/test_mcp_tool_provider.py`

- [ ] **Step 1: Write failing MCP discovery tests**

Create `python/tests/test_mcp_tool_provider.py`:

```python
from agent_service.tool_providers.mcp import McpToolProvider, McpToolSpec


class FakeMcpClient:
    def list_tools(self):
        return [
            McpToolSpec(
                name="search_docs",
                description="Search an external documentation source.",
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {"query": {"type": "string"}},
                },
                output_schema={"type": "object"},
            )
        ]

    def call_tool(self, name, arguments):
        return {
            "content": [{"type": "text", "text": "result"}],
            "structuredContent": {"matches": 1},
            "isError": False,
        }


def test_mcp_provider_maps_tools_to_unified_catalog() -> None:
    provider = McpToolProvider(
        provider_id="mcp-docs",
        display_name="Docs MCP",
        client=FakeMcpClient(),
        enabled=True,
    )

    tools = provider.list_tools()

    assert tools[0].id == "mcp:mcp-docs:search_docs"
    assert tools[0].source == "mcp"
    assert tools[0].provider_tool_name == "search_docs"
    assert tools[0].input_schema["required"] == ["query"]
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
python -m pytest tests/test_mcp_tool_provider.py -q
```

Expected: fail because MCP provider module does not exist.

- [ ] **Step 3: Implement MCP provider data mapping**

Create `python/agent_service/tool_providers/mcp.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from agent_service.tool_protocol import (
    ToolResultContent,
    ToolSafetyPolicy,
    UnifiedToolDefinition,
    UnifiedToolError,
    UnifiedToolInvocation,
    UnifiedToolResult,
)


@dataclass(frozen=True)
class McpToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None


class McpClient(Protocol):
    def list_tools(self) -> list[McpToolSpec]:
        raise NotImplementedError

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class McpToolProvider:
    source = "mcp"

    def __init__(
        self,
        *,
        provider_id: str,
        display_name: str,
        client: McpClient,
        enabled: bool,
    ) -> None:
        self.provider_id = provider_id
        self.display_name = display_name
        self.client = client
        self.enabled = enabled

    def list_tools(self) -> list[UnifiedToolDefinition]:
        if not self.enabled:
            return []
        return [
            UnifiedToolDefinition(
                id=f"mcp:{self.provider_id}:{tool.name}",
                source="mcp",
                provider_id=self.provider_id,
                provider_tool_name=tool.name,
                display_name=tool.name,
                description=tool.description,
                capabilities=["external_mcp"],
                input_schema=dict(tool.input_schema),
                output_schema=dict(tool.output_schema or {}),
                permissions=["call_external_mcp_tool"],
                safety_policy=ToolSafetyPolicy(
                    filesystem="none",
                    network="provider_declared",
                    user_approval="high_risk_only",
                    secrets="provider_managed",
                    sandbox="not_required",
                    max_runtime_ms=60000,
                ),
                timeout_ms=60000,
                examples=[],
                enabled=True,
            )
            for tool in self.client.list_tools()
        ]

    def call_tool(self, invocation: UnifiedToolInvocation) -> UnifiedToolResult:
        name = invocation.tool_id.removeprefix(f"mcp:{self.provider_id}:")
        try:
            raw = self.client.call_tool(name, invocation.arguments)
        except Exception:
            return _mcp_error("mcp_call_failed", "MCP tool call failed")

        if raw.get("isError") is True:
            return _mcp_error("mcp_tool_error", "MCP tool returned an error", recoverable=True)

        return UnifiedToolResult(
            ok=True,
            content=_map_content(raw.get("content", [])),
            structured_content=raw.get("structuredContent"),
            artifacts=[],
            metadata={"providerId": self.provider_id},
        )


def _map_content(items: list[dict[str, Any]]) -> list[ToolResultContent]:
    mapped: list[ToolResultContent] = []
    for item in items:
        if item.get("type") == "text":
            mapped.append(ToolResultContent(type="text", text=str(item.get("text", ""))))
        else:
            mapped.append(ToolResultContent(type="json", value=item))
    return mapped


def _mcp_error(code: str, message: str, *, recoverable: bool = False) -> UnifiedToolResult:
    return UnifiedToolResult(
        ok=False,
        content=[],
        structured_content=None,
        artifacts=[],
        metadata={},
        error=UnifiedToolError(code=code, message=message, recoverable=recoverable),
    )
```

- [ ] **Step 4: Add MCP call tests**

Append:

```python
from agent_service.tool_protocol import UnifiedToolInvocation


def test_mcp_provider_calls_tool_and_maps_result() -> None:
    provider = McpToolProvider(
        provider_id="mcp-docs",
        display_name="Docs MCP",
        client=FakeMcpClient(),
        enabled=True,
    )

    result = provider.call_tool(
        UnifiedToolInvocation(
            invocation_id="inv-1",
            run_id="run-1",
            task_id="task-1",
            tool_id="mcp:mcp-docs:search_docs",
            arguments={"query": "alita"},
            allowed_roots=[],
            requested_permissions=["call_external_mcp_tool"],
        )
    )

    assert result.ok is True
    assert result.structured_content == {"matches": 1}
    assert result.content[0].text == "result"
```

- [ ] **Step 5: Verify MCP provider tests**

Run:

```powershell
python -m pytest tests/test_mcp_tool_provider.py tests/test_tool_gateway.py -q
```

Expected: pass.

### Task 2.2: Add MCP Provider Preferences And Commands

**Files:**
- Modify: `src-tauri/src/preferences.rs`
- Modify: `src-tauri/src/api_credentials.rs`
- Modify: `src-tauri/src/commands.rs`
- Modify: `src-tauri/src/lib.rs`
- Create: `src-tauri/tests/tool_provider_commands_tests.rs`
- Modify: `src-tauri/tests/preferences_tests.rs`
- Modify: `src/shared/types.ts`
- Modify: `src/features/preferences/preferencesApi.ts`
- Modify: `src/features/preferences/PreferencesDialog.tsx`
- Modify: `src/features/preferences/PreferencesDialog.test.tsx`

- [ ] **Step 1: Write Rust preference tests for MCP provider config**

Add tests that prove:

```rust
#[test]
fn default_preferences_include_internal_tool_provider() {
    let preferences = AppPreferences::default();

    assert!(preferences
        .tool_provider_configs
        .iter()
        .any(|provider| provider.provider_id == "internal"));
}

#[test]
fn mcp_provider_config_does_not_store_secrets() {
    let mut preferences = AppPreferences::default();
    let provider = upsert_mcp_tool_provider_config(
        &mut preferences,
        McpToolProviderInput {
            provider_id: None,
            display_name: "Docs MCP".to_string(),
            transport: "stdio".to_string(),
            command: Some("npx".to_string()),
            args: vec!["@example/docs-mcp".to_string()],
            url: None,
            enabled: true,
        },
    )
    .unwrap();

    let serialized = serde_json::to_string(&preferences).unwrap();

    assert!(serialized.contains("Docs MCP"));
    assert!(serialized.contains(&provider.provider_id));
    assert!(!serialized.contains("token"));
    assert!(!serialized.contains("secret"));
}
```

- [ ] **Step 2: Implement preference schema additions**

Add `ToolProviderConfig`, `McpToolProviderConfig`, `McpToolProviderInput`, and helpers:

```rust
pub fn upsert_mcp_tool_provider_config(
    preferences: &mut AppPreferences,
    input: McpToolProviderInput,
) -> Result<McpToolProviderConfig, String> {
    validate_mcp_tool_provider_input(&input)?;
    let provider_id = input
        .provider_id
        .clone()
        .unwrap_or_else(|| format!("alita.mcp-provider.{}", uuid::Uuid::new_v4()));
    let config = McpToolProviderConfig {
        provider_id: provider_id.clone(),
        source: "mcp".to_string(),
        display_name: input.display_name.trim().to_string(),
        transport: input.transport.trim().to_string(),
        command: input.command.map(|value| value.trim().to_string()),
        args: input.args,
        url: input.url.map(|value| value.trim().to_string()),
        enabled: input.enabled,
        created_at: now_iso8601(),
        updated_at: now_iso8601(),
    };
    upsert_mcp_config_in_place(preferences, config.clone());
    Ok(config)
}

pub fn delete_mcp_tool_provider_config(
    preferences: &mut AppPreferences,
    provider_id: &str,
) -> Result<(), String> {
    if provider_id == "internal" {
        return Err("internal tool provider cannot be deleted".to_string());
    }
    let before = preferences.tool_provider_configs.len();
    preferences
        .tool_provider_configs
        .retain(|provider| provider.provider_id() != provider_id);
    if preferences.tool_provider_configs.len() == before {
        return Err(format!("unknown tool provider: {provider_id}"));
    }
    Ok(())
}
```

Rules:

- `internal` provider cannot be deleted.
- `stdio` requires a non-empty command.
- `http` requires a loopback or HTTPS URL.
- Secrets are credential-store only.

- [ ] **Step 3: Add Tauri commands**

Add commands:

```rust
#[tauri::command]
pub fn save_mcp_tool_provider_config(
    app: tauri::AppHandle,
    payload: SaveMcpToolProviderPayload,
) -> Result<PreferencesView, String>

#[tauri::command]
pub fn delete_mcp_tool_provider_config_command(
    app: tauri::AppHandle,
    provider_id: String,
) -> Result<PreferencesView, String>

#[tauri::command]
pub async fn refresh_mcp_tool_provider_tools(
    app: tauri::AppHandle,
    provider_id: String,
) -> Result<Vec<UnifiedToolSummary>, String>
```

The refresh command can use a testable fake boundary at first; real MCP process wiring can be implemented in Python provider code.

- [ ] **Step 4: Add frontend types and Preferences UI**

Add TypeScript types matching Rust views:

```ts
export type ToolProviderSource = "internal" | "mcp";
export type McpTransport = "stdio" | "http";

export type McpToolProviderConfig = {
  providerId: string;
  source: "mcp";
  displayName: string;
  transport: McpTransport;
  command?: string;
  args: string[];
  url?: string;
  enabled: boolean;
  hasCredential: boolean;
};
```

UI requirements:

- Preferences gets a tool provider section.
- Internal provider is visible but not editable.
- MCP provider forms do not echo saved secrets.
- Buttons: Save, Delete, Refresh Tools.

- [ ] **Step 5: Verify Phase 2 UI and Rust tests**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml --test preferences_tests --test tool_provider_commands_tests
npm run frontend:lint
npm run frontend:test -- src/features/preferences/PreferencesDialog.test.tsx
```

Expected: pass.

### Task 2.3: Phase 2 Audit Gate

**Files:**
- Create: `docs/superpowers/audits/2026-05-25-unified-agent-tool-protocol-phase-2.md`

- [ ] **Step 1: Run affected checks**

Run:

```powershell
python -m pytest tests/test_mcp_tool_provider.py tests/test_tool_gateway.py -q
cargo test --manifest-path src-tauri/Cargo.toml --test preferences_tests --test tool_provider_commands_tests
npm run frontend:lint
npm run frontend:test -- src/features/preferences/PreferencesDialog.test.tsx
```

Expected: all pass.

- [ ] **Step 2: Write Phase 2 audit note**

Use the required audit format. Acceptance criteria must include:

- Fake MCP provider discovery works.
- Fake MCP invocation works through unified result mapping.
- MCP provider configuration stores no secrets.
- Disabled MCP providers are not exposed.
- Preferences UI does not reveal saved credentials.

- [ ] **Step 3: Commit Phase 2**

Run:

```powershell
git add python/agent_service/tool_providers/mcp.py python/tests/test_mcp_tool_provider.py src-tauri src src/shared/types.ts docs/superpowers/audits/2026-05-25-unified-agent-tool-protocol-phase-2.md
git commit -m "feat: add mcp tool provider configuration"
```

Expected: commit succeeds. Continue automatically to Phase 3.

---

## Phase 3: Agent Tool Selection And Node Planning

### Task 3.1: Add Unified Tool Resolver

**Files:**
- Modify: `python/agent_service/tool_resolver.py`
- Create or modify: `python/tests/test_tool_resolver.py`
- Modify: `python/agent_service/context_manager.py`
- Modify: `python/agent_service/planner_v2.py`
- Modify: `python/agent_service/tool_router.py`

- [ ] **Step 1: Write resolver tests**

Add tests proving:

```python
def test_resolver_filters_document_task_to_document_tools() -> None:
    tools = [
        tool_definition("internal:document.markitdown_convert", ["document_conversion"]),
        tool_definition("mcp:docs:search_docs", ["external_mcp", "documentation_search"]),
        tool_definition("internal:web.search", ["web_search"]),
    ]

    selected = resolve_tools_for_task(
        tools,
        task_text="Convert this uploaded docx into a markdown summary.",
        disabled_tool_ids=[],
        approved_permissions=[],
    )

    assert [tool.id for tool in selected] == ["internal:document.markitdown_convert"]


def test_resolver_excludes_disabled_tools() -> None:
    tools = [tool_definition("internal:document.markitdown_convert", ["document_conversion"])]

    selected = resolve_tools_for_task(
        tools,
        task_text="Convert a document.",
        disabled_tool_ids=["internal:document.markitdown_convert"],
        approved_permissions=[],
    )

    assert selected == []
```

- [ ] **Step 2: Implement resolver**

Add a deterministic resolver first. It should use:

- capability tags
- disabled tool IDs
- task keyword hints
- permission policy

Do not use an LLM inside the resolver in this phase.

- [ ] **Step 3: Update context manager and planner**

Replace direct `ToolRegistry.enabled_tools()` summaries with `UnifiedToolGateway.list_tools()` plus resolver filtering.

Planner prompt requirements:

- Include tool ID.
- Include display name.
- Include short description.
- Include input schema summary.
- Include permission/risk summary.
- Do not include secrets, provider credentials, or raw command lines.

- [ ] **Step 4: Verify planner/resolver tests**

Run:

```powershell
python -m pytest tests/test_tool_resolver.py tests/test_context_manager.py tests/test_planner_v2.py tests/test_tool_router.py -q
```

Expected: pass.

### Task 3.2: Bind Generated Nodes To Unified Tool IDs

**Files:**
- Modify: `python/agent_service/graph_compiler.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/agent_service/schemas.py`
- Modify: `src/shared/types.ts`
- Modify: relevant graph/planner tests

- [ ] **Step 1: Add failing graph binding tests**

Add tests proving generated fixed tool nodes store unified IDs:

```python
def test_compiled_document_graph_uses_unified_tool_id() -> None:
    graph = compile_task_graph_for_test("Convert an uploaded DOCX into Markdown.")
    fixed_tool_nodes = [node for node in graph.nodes if node.nodeType == "fixed_tool"]

    assert any(node.toolRef == "internal:document.markitdown_convert" for node in fixed_tool_nodes)
```

- [ ] **Step 2: Implement compatibility mapping**

Execution must accept both:

- old `document.markitdown_convert`
- new `internal:document.markitdown_convert`

Normalize before execution:

```python
def normalize_tool_id(tool_id: str) -> str:
    if tool_id.startswith("internal:") or tool_id.startswith("mcp:"):
        return tool_id
    return f"internal:{tool_id}"
```

- [ ] **Step 3: Verify graph execution compatibility**

Run:

```powershell
python -m pytest tests/test_graph.py tests/test_execution.py tests/test_graph_compiler.py -q
```

Expected: pass.

### Task 3.3: Phase 3 Audit Gate

**Files:**
- Create: `docs/superpowers/audits/2026-05-25-unified-agent-tool-protocol-phase-3.md`

- [ ] **Step 1: Run affected checks**

Run:

```powershell
python -m pytest tests/test_tool_resolver.py tests/test_context_manager.py tests/test_planner_v2.py tests/test_tool_router.py tests/test_graph.py tests/test_execution.py tests/test_graph_compiler.py -q
npm run frontend:lint
```

Expected: all pass.

- [ ] **Step 2: Write Phase 3 audit note**

Acceptance criteria must include:

- Planner sees filtered unified tool summaries.
- Disabled tools are removed before planning.
- Generated graphs bind stable unified tool IDs.
- Old project tool IDs remain executable.

- [ ] **Step 3: Commit Phase 3**

Run:

```powershell
git add python/agent_service src/shared/types.ts python/tests docs/superpowers/audits/2026-05-25-unified-agent-tool-protocol-phase-3.md
git commit -m "feat: route planning through unified tool catalog"
```

Expected: commit succeeds. Continue automatically to Phase 4.

---

## Phase 4: Model Provider Tool-Calling Adapters

### Task 4.1: Add Model Tool Schema Adapter

**Files:**
- Create: `python/agent_service/model_tool_adapter.py`
- Create: `python/tests/test_model_tool_adapter.py`
- Modify: `python/agent_service/model_client.py`
- Modify: `python/agent_service/model_policy.py` if provider capability flags belong there

- [ ] **Step 1: Write failing adapter tests**

Create `python/tests/test_model_tool_adapter.py`:

```python
from agent_service.model_tool_adapter import to_openai_tool_schema
from agent_service.tool_protocol import ToolSafetyPolicy, UnifiedToolDefinition


def test_unified_tool_converts_to_openai_tool_schema() -> None:
    tool = UnifiedToolDefinition(
        id="internal:document.markitdown_convert",
        source="internal",
        provider_id="internal",
        provider_tool_name="document.markitdown_convert",
        display_name="Convert Document",
        description="Convert a project document to Markdown.",
        capabilities=["document_conversion"],
        input_schema={
            "type": "object",
            "required": ["input_path"],
            "properties": {"input_path": {"type": "string"}},
        },
        output_schema={"type": "object"},
        permissions=["read_project_files"],
        safety_policy=ToolSafetyPolicy(
            filesystem="project_read",
            network="none",
            user_approval="never",
            secrets="none",
            sandbox="not_required",
            max_runtime_ms=60000,
        ),
        timeout_ms=60000,
        examples=[],
    )

    schema = to_openai_tool_schema(tool)

    assert schema["type"] == "function"
    assert schema["function"]["name"] == "internal__document__markitdown_convert"
    assert schema["function"]["parameters"]["required"] == ["input_path"]
```

- [ ] **Step 2: Implement schema adapter**

Create:

```python
from __future__ import annotations

import re

from agent_service.tool_protocol import UnifiedToolDefinition


def to_openai_tool_schema(tool: UnifiedToolDefinition) -> dict:
    return {
        "type": "function",
        "function": {
            "name": model_safe_tool_name(tool.id),
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }


def model_safe_tool_name(tool_id: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_]", "__", tool_id)
    value = re.sub(r"__+", "__", value).strip("_")
    return value[:64]
```

- [ ] **Step 3: Add reverse mapping tests**

Add a mapping registry so model tool names map back to stable Alita tool IDs:

```python
from agent_service.model_tool_adapter import ModelToolNameMap


def test_model_tool_name_map_round_trips_tool_id() -> None:
    mapping = ModelToolNameMap.from_tools([tool])

    model_name = mapping.model_name_for_tool_id("internal:document.markitdown_convert")

    assert mapping.tool_id_for_model_name(model_name) == "internal:document.markitdown_convert"
```

- [ ] **Step 4: Verify adapter tests**

Run:

```powershell
python -m pytest tests/test_model_tool_adapter.py -q
```

Expected: pass.

### Task 4.2: Add Tool-Calling Execution Loop

**Files:**
- Modify: `python/agent_service/graph.py`
- Modify: `python/agent_service/model_client.py`
- Modify: `python/agent_service/schemas.py`
- Modify: `python/tests/test_graph.py`
- Modify: `python/tests/test_model_client.py`

- [ ] **Step 1: Write tests for tool call rejection**

Add a fake model client that returns a tool call for a disabled tool. Test that the call is rejected before provider execution and that the model receives a safe error result.

Expected assertion:

```python
assert event["type"] == "tool.call.rejected"
assert event["payload"]["error"]["code"] == "tool_disabled"
```

- [ ] **Step 2: Implement provider capability flag**

Add config/capability:

```python
supports_native_tool_calls: bool
```

Default:

- Local llama.cpp: false unless explicitly implemented.
- OpenAI-compatible API: true only when provider config enables it.
- Existing text-only flow remains default.

- [ ] **Step 3: Implement tool call loop**

Algorithm:

1. Resolve tools for the current task.
2. Convert tools to provider schema.
3. Send messages plus tools to model provider if supported.
4. If model returns tool calls, map model tool name to Alita tool ID.
5. Validate and execute through `UnifiedToolGateway`.
6. Append structured tool result to model conversation.
7. Continue until the model returns a final answer or max tool call iterations is reached.

Limits:

- Max tool call iterations: 5.
- No direct provider execution.
- All errors sanitized.

- [ ] **Step 4: Verify model tool-calling tests**

Run:

```powershell
python -m pytest tests/test_model_tool_adapter.py tests/test_model_client.py tests/test_graph.py -q
```

Expected: pass.

### Task 4.3: Phase 4 Audit Gate

**Files:**
- Create: `docs/superpowers/audits/2026-05-25-unified-agent-tool-protocol-phase-4.md`

- [ ] **Step 1: Run affected checks**

Run:

```powershell
python -m pytest tests/test_model_tool_adapter.py tests/test_model_client.py tests/test_graph.py tests/test_app.py -q
npm run frontend:lint
```

Expected: all pass.

- [ ] **Step 2: Write Phase 4 audit note**

Acceptance criteria must include:

- Unified tools convert to provider tool schemas.
- Model tool names map back to stable tool IDs.
- Disabled/unavailable tools are rejected before execution.
- Providers without native tool calling keep existing behavior.
- Tool calls execute only through the Unified Tool Gateway.

- [ ] **Step 3: Commit Phase 4**

Run:

```powershell
git add python/agent_service/model_tool_adapter.py python/agent_service python/tests docs/superpowers/audits/2026-05-25-unified-agent-tool-protocol-phase-4.md
git commit -m "feat: add model tool calling adapter"
```

Expected: commit succeeds. Continue automatically to Phase 5.

---

## Phase 5: Alita MCP Server

### Task 5.1: Add Optional Alita MCP Server

**Files:**
- Create: `python/agent_service/mcp_server.py`
- Create: `python/tests/test_mcp_server.py`
- Modify: `python/agent_service/app.py`
- Modify: `python/agent_service/schemas.py`
- Modify: `src-tauri/src/preferences.rs`
- Modify: `src/features/preferences/PreferencesDialog.tsx`

- [ ] **Step 1: Write failing server tests**

Create `python/tests/test_mcp_server.py`:

```python
from agent_service.mcp_server import AlitaMcpServer


def test_alita_mcp_server_lists_only_allowed_tools(fake_gateway) -> None:
    server = AlitaMcpServer(
        gateway=fake_gateway,
        allowed_tool_ids=["internal:document.receive_attachment"],
        enabled=True,
    )

    tools = server.list_tools()

    assert [tool["name"] for tool in tools] == ["internal__document__receive_attachment"]


def test_alita_mcp_server_rejects_non_whitelisted_tool(fake_gateway) -> None:
    server = AlitaMcpServer(
        gateway=fake_gateway,
        allowed_tool_ids=["internal:document.receive_attachment"],
        enabled=True,
    )

    result = server.call_tool("internal__document__markitdown_convert", {})

    assert result["isError"] is True
```

- [ ] **Step 2: Implement server wrapper**

Implement an in-process server abstraction first. It should expose methods equivalent to:

- `list_tools()`
- `call_tool(name, arguments)`

Route calls through the gateway and map unified results to MCP result shape.

- [ ] **Step 3: Add server disabled-by-default preference**

Preference defaults:

```ts
alitaMcpServer: {
  enabled: false,
  allowedToolIds: [],
  requireLocalAuth: true
}
```

- [ ] **Step 4: Verify server tests**

Run:

```powershell
python -m pytest tests/test_mcp_server.py -q
```

Expected: pass.

### Task 5.2: Add External Call Auditing

**Files:**
- Modify: `python/agent_service/run_journal.py`
- Modify: `python/agent_service/mcp_server.py`
- Modify: `python/tests/test_mcp_server.py`
- Modify: `python/tests/test_run_journal.py`

- [ ] **Step 1: Add audit tests**

Add tests proving external MCP calls write sanitized audit events:

```python
def test_external_mcp_call_writes_sanitized_audit(fake_gateway, run_journal) -> None:
    server = AlitaMcpServer(
        gateway=fake_gateway,
        allowed_tool_ids=["internal:document.receive_attachment"],
        enabled=True,
        run_journal=run_journal,
    )

    server.call_tool("internal__document__receive_attachment", {"path": "inputs/a.md"})

    events = run_journal.events()
    assert events[-1]["source"] == "external_mcp"
    assert "secret" not in str(events[-1]).lower()
```

- [ ] **Step 2: Implement audit event recording**

Record:

- source: `external_mcp`
- tool ID
- timestamp
- safe argument summary
- result status
- sanitized error

Do not record:

- auth tokens
- provider credentials
- raw command lines with secrets

- [ ] **Step 3: Verify audit tests**

Run:

```powershell
python -m pytest tests/test_mcp_server.py tests/test_run_journal.py -q
```

Expected: pass.

### Task 5.3: Phase 5 Final Audit Gate

**Files:**
- Create: `docs/superpowers/audits/2026-05-25-unified-agent-tool-protocol-phase-5.md`
- Modify: `README.md`

- [ ] **Step 1: Update README**

Document:

- Internal tools use the Unified Tool Gateway.
- External MCP servers can be configured as providers.
- Alita MCP server is optional and disabled by default.
- Secrets are stored in OS credentials, not project files.

- [ ] **Step 2: Run final full verification**

Run:

```powershell
npm run frontend:lint
npm run frontend:test
python -m pytest
cargo fmt --manifest-path src-tauri/Cargo.toml -- --check
cargo test --manifest-path src-tauri/Cargo.toml
git diff --check
```

Expected:

- frontend lint passes
- frontend tests pass
- Python tests pass
- Rust fmt check passes
- Rust tests pass
- diff check passes

- [ ] **Step 3: Write Phase 5 audit note**

Acceptance criteria must include:

- Alita MCP server is disabled by default.
- Only whitelisted tools are exposed.
- External calls route through the Unified Tool Gateway.
- Write/high-risk tools require approval or are rejected.
- Audit logs are sanitized.
- Full verification passes.

- [ ] **Step 4: Commit Phase 5**

Run:

```powershell
git add python/agent_service python/tests src-tauri src README.md docs/superpowers/audits/2026-05-25-unified-agent-tool-protocol-phase-5.md
git commit -m "feat: expose optional alita mcp server"
```

Expected: commit succeeds. Unified Agent Tool Protocol implementation complete.

---

## Final Integration Review

After Phase 5 commit:

- [ ] Run `git log --oneline -5` and confirm the five phase commits are present.
- [ ] Run `git status --short --branch` and confirm no unexpected implementation changes remain.
- [ ] Re-read all five audit notes and confirm each decision is PASS.
- [ ] Confirm no file contains leaked sample secrets:

```powershell
rg -n "sk-|apiKey|access_token|secret|bearer" docs python src-tauri src
```

Expected: only safe field names, tests with fake values, or redaction assertions appear.

- [ ] Prepare completion summary with:
  - phase commits
  - verification results
  - remaining risks
  - follow-up recommendations

## Plan Self-Review

- The plan covers all five design phases.
- Each phase has a strict audit gate and automatic progression rule.
- Internal tools remain product-owned and gateway-controlled.
- MCP is added as an external provider first, then optional server exposure last.
- Model-provider tool calling is an adapter layer, not the primary tool runtime.
- The plan contains no intentionally deferred placeholder work.
