# Unified Agent Tool Protocol Design

## Goal

Build a long-term Agent tool protocol architecture for Alita that can manage both product-owned internal node tools and external MCP tools through one tool catalog, one invocation gateway, one permission model, and one audit trail.

The architecture must support five implementation phases in one continuous development effort. Each phase must finish with strict acceptance review. If the review passes, implementation proceeds to the next phase automatically. If a review fails, implementation stops until the failure is fixed and reviewed again.

## Product Direction

Alita's internal tools are part of the product, not just external capabilities. They need deep integration with projects, artifacts, node status, run history, file boundaries, user approvals, and UI state. MCP is valuable for external interoperability, but MCP should not replace Alita's internal execution kernel.

The chosen direction is:

- Keep Alita's internal Tool Gateway as the product safety and execution boundary.
- Make internal tool definitions MCP-compatible where useful.
- Add MCP as an external tool provider.
- Present internal tools and MCP tools through a unified tool catalog.
- Convert the unified tool catalog into model-provider tool-calling formats when needed.
- Optionally expose selected Alita tools through an Alita MCP server after the internal gateway is mature.

## Current State

Alita already has a usable internal tool foundation:

- `python/agent_service/tool_registry.py` loads `tool-packages/<tool>/manifest.json`.
- `ToolManifestSpec` includes IDs, descriptions, capabilities, schemas, permissions, timeout policy, artifact policy, and node templates.
- `python/agent_service/tool_execution.py` defines `ToolInvocation` and `ToolResult`.
- `ToolExecutor.run()` checks that a tool exists, checks that an operation exists, validates input against the manifest schema, and dispatches to an adapter.
- The Agent harness design already requires a Tool Registry and Tool Invocation Gateway.

The current foundation is close to MCP conceptually, but it is internal-only and not yet structured as a provider-based protocol.

## External Standards Context

MCP standardizes how a client discovers and calls tools exposed by an MCP server. MCP tools are listed through `tools/list`, called through `tools/call`, and described with names, descriptions, and JSON Schema input schemas. MCP call results support textual content, structured content, and error indication.

OpenAI-style function calling and compatible provider variants solve a different problem: how a model API receives tool definitions and returns requested tool calls. This is a model-provider adapter layer, not a full tool runtime.

Alita should support both:

- MCP for external tool interoperability.
- Model-provider tool-calling adapters for model API execution.
- Alita Unified Tool Gateway for product safety, execution, logging, and node integration.

Reference URLs:

- MCP tools specification: https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- MCP schema: https://modelcontextprotocol.io/specification/2025-11-25/schema
- OpenAI function calling: https://platform.openai.com/docs/guides/function-calling

## Architecture

```text
Agent / Planner / Router / Node Graph
        |
        v
Unified Tool Catalog
        |
        v
Alita Unified Tool Gateway
        |
        +-- InternalToolProvider
        |       - Existing Python/Rust/local tools
        |       - Product-owned artifact and project integration
        |
        +-- MCPToolProvider
        |       - External MCP servers
        |       - tools/list discovery
        |       - tools/call invocation
        |
        +-- FutureToolProviders
                - OpenAPI
                - Browser automation service
                - Enterprise connectors

Model Provider Tool Adapter
        |
        +-- OpenAI-compatible tools/function calling
        +-- DeepSeek/Kimi/GLM/MiniMax provider variants
```

The Unified Tool Gateway is the only path that may execute a tool. The Agent, node graph, and model-provider adapters must not call internal adapters or MCP servers directly.

## Core Concepts

### Unified Tool Definition

Every internal or external tool is normalized into a single catalog shape.

```ts
type UnifiedToolSource = "internal" | "mcp";

type UnifiedToolDefinition = {
  id: string;
  source: UnifiedToolSource;
  providerId: string;
  providerToolName: string;
  displayName: string;
  description: string;
  version?: string;
  capabilities: string[];
  inputSchema: JsonSchemaObject;
  outputSchema?: JsonSchemaObject;
  permissions: ToolPermission[];
  safetyPolicy: ToolSafetyPolicy;
  timeoutMs: number;
  nodeTemplate?: ToolNodeTemplate;
  examples: ToolExample[];
  enabled: boolean;
};
```

`id` is the Alita-stable ID used by nodes, logs, permissions, and preferences. External MCP tool IDs are namespaced so they do not collide with internal tools:

```text
internal:document.markitdown_convert
mcp:<server-id>:<tool-name>
```

The provider-specific name is preserved in `providerToolName`. For MCP tools, this is the name passed to `tools/call`.

### Unified Tool Invocation

```ts
type UnifiedToolInvocation = {
  invocationId: string;
  runId: string;
  taskId: string;
  nodeId?: string;
  toolId: string;
  arguments: Record<string, unknown>;
  projectPath?: string;
  allowedRoots: string[];
  requestedPermissions: ToolPermission[];
  approvalToken?: string;
  modelSessionId?: string;
};
```

The invocation object is owned by Alita. MCP calls are derived from it, not stored as the primary runtime representation.

### Unified Tool Result

```ts
type UnifiedToolResult = {
  ok: boolean;
  content: ToolResultContent[];
  structuredContent?: Record<string, unknown>;
  artifacts: string[];
  metadata: Record<string, string>;
  error?: UnifiedToolError;
};

type ToolResultContent =
  | { type: "text"; text: string }
  | { type: "json"; value: unknown }
  | { type: "artifact"; path: string; mimeType?: string }
  | { type: "resource_link"; uri: string; title?: string };

type UnifiedToolError = {
  code: string;
  message: string;
  recoverable: boolean;
  safeDetails?: Record<string, unknown>;
};
```

Internal results and MCP results are normalized into this shape. The Agent sees structured results and safe errors, not raw provider exceptions.

### Tool Provider Interface

```python
class ToolProvider(Protocol):
    provider_id: str
    source: Literal["internal", "mcp"]

    def list_tools(self) -> list[UnifiedToolDefinition]:
        raise NotImplementedError

    def call_tool(self, invocation: UnifiedToolInvocation) -> UnifiedToolResult:
        raise NotImplementedError
```

The registry becomes provider-based. Internal manifest packages are exposed by `InternalToolProvider`. External MCP servers are exposed by `McpToolProvider`.

### Safety Policy

Every tool must declare a safety policy. The gateway enforces policy before provider invocation.

```ts
type ToolSafetyPolicy = {
  filesystem: "none" | "project_read" | "project_write" | "external_read" | "external_write";
  network: "none" | "provider_declared" | "any";
  userApproval: "never" | "before_call" | "high_risk_only";
  secrets: "none" | "provider_managed" | "user_configured";
  sandbox: "not_required" | "required";
  maxRuntimeMs: number;
};
```

MCP tools default to stricter policies than internal tools:

- No project write access by default.
- User approval required for write-like or destructive capabilities.
- Secrets are never passed through model messages.
- Raw MCP errors are sanitized before being shown to users or models.

## Data Model Changes

### Preferences

Preferences should store non-sensitive tool provider configuration:

```ts
type ToolProviderConfig =
  | InternalToolProviderConfig
  | McpToolProviderConfig;

type InternalToolProviderConfig = {
  providerId: "internal";
  source: "internal";
  enabled: true;
};

type McpToolProviderConfig = {
  providerId: string;
  source: "mcp";
  displayName: string;
  transport: "stdio" | "http";
  command?: string;
  args?: string[];
  url?: string;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
};
```

Secrets, bearer tokens, and MCP server credentials must be stored in the system credential store, not in preferences.

### Project Files

Project files should continue to store stable node references. They must not store MCP credentials.

For fixed tool nodes:

```ts
type ToolNodeBinding = {
  toolId: string;
  providerId: string;
  providerToolName: string;
  version?: string;
};
```

Existing `toolRef` values can migrate to `toolId` without changing user projects in the first phase. Backward compatibility must remain.

### Run Journal

Run journal entries should record:

- `invocationId`
- `toolId`
- `providerId`
- safe input summary
- permission decision
- start/end timestamps
- result status
- artifact paths
- sanitized error code/message

Run journals must never record secrets or raw credential-bearing command lines.

## Five-Phase Implementation Strategy

### Phase 1: Unified Protocol Kernel

Build the internal protocol foundation without changing user-facing behavior.

Scope:

- Add unified tool definition, invocation, result, error, and provider models.
- Wrap existing internal manifests behind `InternalToolProvider`.
- Keep existing internal adapters working.
- Add compatibility mapping from current `ToolInvocation -> ToolResult`.
- Keep current node graph behavior unchanged.

Acceptance:

- Existing internal document, MarkItDown, Typst, and web-related tool tests pass.
- New unit tests prove internal tools appear in the unified catalog.
- New unit tests prove invalid inputs, unknown tools, disabled tools, and unsupported operations return unified errors.
- Existing project files and existing fixed tool nodes still run.

### Phase 2: MCP Client Provider

Add external MCP tool discovery and invocation through the unified gateway.

Scope:

- Add MCP provider configuration and safe credential handling.
- Implement MCP client abstraction with test fakes.
- Support `tools/list` discovery and `tools/call` invocation.
- Map MCP input schemas and call results into unified definitions and results.
- Add Preferences UI for MCP server management.
- Add node selection support for MCP tools.

Acceptance:

- A fake MCP server can expose a tool, appear in the unified catalog, and be called through the gateway.
- MCP tool failures produce sanitized unified errors.
- Disabled MCP providers are hidden from Agent planning and blocked at execution.
- MCP credentials are not written to preferences, project files, logs, run journals, or frontend snapshots.

### Phase 3: Agent Tool Selection And Node Planning

Make the Agent use the unified catalog when understanding user tasks and planning node workflows.

Scope:

- Add a tool resolver that filters tools by task intent, capabilities, permissions, disabled state, and project context.
- Update Planner/Router prompts to use compact unified tool summaries.
- Store tool selection rationale in planning metadata.
- Make generated node plans use stable `toolId` bindings.
- Add execution feedback so recoverable tool errors can trigger replanning or user questions.

Acceptance:

- Planner tests show only relevant tool summaries are presented for document, web, and mixed tasks.
- Agent-generated graphs bind tools through unified IDs.
- Disabled or high-risk tools are not selected without permission.
- Tool failure events include enough structured information for follow-up planning.

### Phase 4: Model Provider Tool-Calling Adapters

Connect unified tool definitions to model API tool-calling formats without binding product logic to any single provider.

Scope:

- Add `ModelToolSchemaAdapter` for OpenAI-compatible tool/function calling.
- Add provider capability flags for native tool calling vs. text-only planning.
- Add an Agent loop that can receive model tool calls, validate them through the unified gateway, execute, and return results to the model.
- Keep existing graph-first execution intact.
- Do not bypass node graph permissions or run journal.

Acceptance:

- Unit tests verify unified tool definitions convert to OpenAI-compatible tool schemas.
- Tool call requests from a model are rejected if the tool is unavailable, disabled, or permission-denied.
- Successful model tool calls execute through the gateway and return structured results to the model loop.
- Providers without native tool-calling continue using graph planning and text responses.

### Phase 5: Alita MCP Server

Expose selected Alita tools to external MCP clients after internal gateway controls are stable.

Scope:

- Add an optional local Alita MCP server.
- Expose only explicitly allowed internal tools.
- Route all external calls through the same unified gateway.
- Require local authentication and safe project scoping.
- Add audit logs for external MCP calls.

Acceptance:

- External MCP client tests can list allowed Alita tools and call a safe read-only tool.
- Non-whitelisted tools are invisible.
- Write tools require explicit user approval or are rejected.
- External calls appear in run/audit logs with sanitized inputs and outputs.
- The MCP server is disabled by default.

## Continuous Implementation And Phase Gates

The five phases should be implemented in one continuous branch, but each phase has a hard gate:

1. Implement the phase.
2. Run the phase-specific tests.
3. Run affected full-suite checks.
4. Produce a phase audit note with evidence.
5. If and only if the audit passes, commit the phase and continue to the next phase.

If a phase fails:

- Do not continue to the next phase.
- Fix the failure inside the same phase.
- Re-run the audit.
- Continue only after the audit passes.

This gives the user the effect of automatic progression without losing review discipline.

## Security Requirements

- Secrets must never be sent to the model unless they are explicitly required by a provider call and never included in prompt text.
- Secrets must never be stored in project files, preferences, run history, frontend persistent state, logs, or audit notes.
- MCP tools default to least privilege.
- Project file reads and writes must go through existing path-boundary checks.
- External network tools must be explicitly declared and visible in Preferences.
- Destructive or high-risk operations require user approval before execution.
- Raw provider errors must be sanitized before reaching the model or UI.

## Backward Compatibility

The first phase must not break existing projects or tests.

Rules:

- Existing `toolRef` values remain accepted.
- Existing tool package manifests remain valid.
- Existing internal adapters continue to run.
- Existing Preferences tool enablement by tool ID remains honored.
- Project schema migration can be deferred until the unified protocol is proven; runtime compatibility is required immediately.

## Non-Goals

This design does not require:

- Replacing internal execution with MCP.
- Making every internal tool an MCP server.
- Exposing Alita tools externally before Phase 5.
- Supporting every MCP transport in the first MCP client version.
- Letting model providers execute tools directly.
- Letting external MCP servers write arbitrary files.

## Design Self-Review

- No placeholder requirements remain.
- The architecture keeps product safety in Alita rather than outsourcing it to MCP.
- Each phase is independently testable and has explicit acceptance criteria.
- The plan supports one continuous implementation branch with phase-by-phase audit gates.
- The design preserves existing internal tools while adding external MCP interoperability.
