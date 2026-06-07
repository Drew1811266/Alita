# Node Catalog Design

## Status

This design is approved for planning.

The first implementation should add a shared Node Catalog layer for Alita. The
catalog serves both Deep Agent graph planning and the frontend read-only node
library. It does not introduce manual canvas editing, drag-and-drop node
composition, user-defined nodes, or a full plugin marketplace in the first
release.

## Purpose

Alita's Deep Agent runtime can already reason, draft plans, review plans,
compile graphs, execute graphs, verify results, and propose repair. The current
limitation is that the Agent has too few concrete nodes to compose after it
understands a user's request.

The goal is to give the Agent a stable, testable catalog of nodes it can choose
from when compiling a graph. The same catalog should also be visible to the
frontend so users can understand what Alita is able to do and why a generated
graph contains specific nodes.

## Product Principle

The Agent should compile user goals into real, explainable nodes.

Each node in the catalog must declare:

- what capability it provides;
- what inputs and outputs it accepts;
- how it executes or interrupts;
- what permissions and risks it carries;
- where it came from;
- whether it is currently available.

Planner and compiler code should not silently invent tools or hide unsupported
capabilities behind generic model nodes. If a capability is unsupported, the
system should fail honestly, ask the user for clarification, or request setup.

## Baseline

Existing reusable pieces:

- `tool-packages/*/manifest.json`
  Already defines internal tool metadata such as capabilities, operations,
  input schema, output schema, permissions, examples, and `node_templates`.

- `python/agent_service/tool_registry.py`
  Loads tool manifests and exposes enabled internal tools.

- `python/agent_service/tool_providers/internal.py`
  Converts internal tool manifests into unified tool definitions.

- `python/agent_service/deep_agent_runtime_graph.py`
  Builds Deep Agent context, runs planning and graph compilation, and executes
  confirmed compiled graphs.

- `python/agent_service/deep_agent_graph_compile.py`
  Converts `PlanDraft` steps into public `RunGraph` nodes, but currently relies
  on a hard-coded document capability binding table.

- `python/agent_service/agent_plan_compile.py`
  Converts a confirmed public `RunGraph` into `AgentCompiledGraph` and validates
  provenance, bindings, dependencies, and execution readiness.

- `src/features/canvas/NodeCanvas.tsx` and
  `src/features/canvas/NodePopover.tsx`
  Display generated graph nodes and node details.

The first Node Catalog implementation should compose with these modules instead
of replacing the Deep Agent runtime.

## Out Of Scope

The first release does not include:

- manual drag-and-drop node composition;
- manual edge wiring;
- node parameter editing UI;
- user-created custom nodes;
- saved graph templates;
- dynamic hot reload of catalog entries;
- full external plugin or MCP node marketplace behavior.

MCP and plugin sources should be represented in the schema, but the first
implementation should focus on internal and system nodes.

## Architecture

Node Catalog should become a shared protocol layer between Agent planning,
graph compilation, execution binding, and frontend display.

```text
tool-packages/*/manifest.json
MCP tools / future plugins
system model nodes
system human nodes
system verifier nodes
system output nodes
        |
        v
NodeCatalogBuilder
        |
        v
NodeCatalogSnapshot
        |
        +--> Deep Agent Planner
        +--> Graph Compiler
        +--> Agent Plan Compiler
        +--> Frontend Node Library
        +--> Canvas Node Details
```

The backend is the source of truth. The frontend consumes a serialized
`NodeCatalogSnapshot` and should not duplicate node definitions.

## NodeDefinition

`NodeDefinition` is the normalized catalog entry used by both the Agent and the
frontend.

```text
NodeDefinition
- nodeId: stable node definition id, for example document.convert.markdown
- kind: tool | model | human | verifier | output
- displayName: user-facing name
- description: short explanation
- category: document | web | data | reasoning | human | verification | output
- capabilities: planning and resolver capability keys
- inputPorts: normalized input port definitions
- outputPorts: normalized output port definitions
- execution: execution binding
- permissions: permission and risk profile
- examples: short examples for planner and frontend display
- source: internal_tool | system | mcp | plugin
- version: node definition version
- availability: current availability state
```

The Agent should see a compact summary of this structure during planning. The
compiler should use the full structure when binding plan steps to executable
graph nodes.

## NodeExecutionBinding

Execution binding tells the compiler and runtime how a catalog node becomes a
real graph node.

```text
NodeExecutionBinding
- type: tool | model | human | verifier | output
- toolId?: internal or external tool id
- operation?: tool operation name
- modelPolicy?: deep_reasoning | node_reasoning | fast_chat | fast_factual
- verifierType?: artifact_exists | citation_check | schema_check | coverage_check
- outputType?: markdown | docx | pdf | table | checklist | final_response
```

Tool nodes should compile to `fixed_tool` graph nodes with `toolBinding`.
Model nodes should compile to `model` graph nodes with `modelRef` or policy
metadata. Human nodes should compile to interruptible nodes. Verifier and output
nodes should compile to explicit execution metadata instead of being hidden in
chat text.

## NodePort

Node ports should be normalized before they reach the frontend or compiler.

```text
NodePort
- id
- label
- dataType: text | markdown | document | table | json | artifact | url | query | decision
- required
- multiple
- description
```

Tool manifests may continue using their existing `node_templates`, but
`NodeCatalogBuilder` should normalize ports into this contract.

## NodePermissionProfile

Catalog permissions declare requirements; they do not grant authority.
Execution still flows through the existing authority and permission gates.

```text
NodePermissionProfile
- permissions: read_project_files | write_project_outputs | network | run_local_cli | run_python_plugin | call_external_mcp_tool
- riskLevel: low | medium | high
- requiresApproval: true | false
- filesystem: none | project_read | project_write
- network: none | external
- sandbox: none | sidecar | external
```

Suggested risk levels:

- low: pure model reasoning, format checks, already uploaded attachment reads;
- medium: project file reads, project artifact writes, web search;
- high: local CLI execution, Python plugins, external MCP calls, writes outside
  project-controlled outputs.

## Catalog Snapshot

`NodeCatalogSnapshot` is the serialized view shared by planner, compiler, and
frontend.

```text
NodeCatalogSnapshot
- schemaVersion
- generatedAt
- nodes
- diagnostics
- sourceSummary
```

Diagnostics should include invalid node definitions, missing dependencies,
disabled tools, and provider configuration issues. Invalid internal nodes should
fail CI. In product runtime, one invalid optional node should not prevent the
rest of the catalog from loading.

## First Node Set

The first catalog should focus on document/report, web research, and general
office automation tasks.

Document and report nodes:

- `document.receive_attachment`
- `document.read`
- `document.convert.markdown`
- `document.extract_outline`
- `document.summarize`
- `document.extract_facts`
- `document.compare`
- `document.write_markdown`
- `document.write_docx`
- `document.render_pdf`

Web research nodes:

- `web.search`
- `web.open_page`
- `web.extract_content`
- `web.evaluate_source`
- `web.collect_evidence`
- `web.citation_check`
- `research.synthesize`
- `research.write_report`

General office and data nodes:

- `data.read_table`
- `data.clean_table`
- `data.analyze_table`
- `data.write_table`
- `office.create_checklist`
- `office.extract_action_items`
- `office.compare_options`
- `office.write_memo`

System nodes:

- `human.clarify`
- `human.confirm_plan`
- `human.choose_option`
- `verify.artifact_exists`
- `verify.content_format`
- `verify.requirements_covered`
- `output.final_response`

Not every first-release node needs a dedicated external tool. Nodes may be:

- existing tool-bound nodes;
- model execution nodes;
- system human interrupt nodes;
- verifier nodes;
- output nodes.

Every catalog node must compile to an executable, verifiable, or interruptible
runtime unit. It must not be a frontend-only card.

## Planning And Compilation Flow

The target flow is:

```text
User message
  -> Context Build
  -> inject NodeCatalogSnapshot summary
  -> Deep Planning creates PlanDraft
  -> Plan Review validates required capabilities
  -> Graph Compile resolves NodeDefinition entries
  -> RunGraph nodes include catalogNodeId and execution binding
  -> Agent Plan Compile produces AgentCompiledGraph
  -> Execution Runtime runs tool/model/human/verifier/output nodes
```

Planning context should receive a compact `availableNodes` summary:

```text
availableNodes
- nodeId
- kind
- displayName
- capabilities
- description
- input/output summary
- permissions/risk
- examples
- availability
```

`PlanDraft.steps[].required_capabilities` should remain useful, but planning
should also support preferred node ids or node selection hints. The compiler
then resolves a step through `NodeCatalogResolver`.

Resolver behavior:

- if one available node matches exactly, bind it;
- if multiple nodes match, rank by preferred node id, capability exactness,
  availability, risk level, and internal stability;
- if no node matches, report unsupported capability;
- if a node is unavailable, do not select it by default;
- if a high-risk node is selected, compile it with permissions and let runtime
  permission gates handle approval.

This replaces hard-coded capability binding tables such as the document binding
map in `deep_agent_graph_compile.py`.

## Frontend Read-Only Node Library

The frontend should add a read-only node library surface. It should explain what
Alita can use, not allow manual composition in the first release.

Required behavior:

- show all catalog nodes;
- search by name, capability, and description;
- filter by category;
- show node detail including ports, permissions, source, examples, and
  availability;
- explain disabled or unavailable states;
- show catalog source information in generated canvas nodes.

Canvas node metadata should include:

```text
catalogNodeId
catalogDisplayName
capabilities
execution.kind
permissions.riskLevel
nodeSelectionReason
```

`NodePopover` should show that a generated graph node came from the catalog and
why it was selected.

## Error Handling

Catalog and node failures should be explicit.

Catalog construction:

- invalid optional nodes are excluded and reported as diagnostics;
- invalid internal first-party nodes fail tests;
- frontend can show invalid or unavailable diagnostics when useful.

Availability:

- valid but unavailable nodes stay in the catalog;
- availability can be `available`, `degraded`, or `unavailable`;
- reason codes include `dependency_missing`, `provider_not_configured`,
  `permission_required`, `disabled_by_user`, and `invalid_definition`;
- planner should not select unavailable nodes by default.

Compile failures:

- unsupported capabilities should produce review or compile findings;
- generic model fallback is allowed only for pure reasoning tasks;
- graph compile must not disguise unsupported tool capabilities as executable
  model nodes.

Runtime failures:

- `binding_failed`: catalog execution binding and runtime contract disagree;
- `permission_denied`: approval or authority is missing;
- `dependency_missing`: CLI, package, provider, or API configuration is absent;
- `tool_failed`: tool invocation failed;
- `verification_failed`: output did not satisfy expected criteria.

Recovery policy:

- automatic recovery may retry once or choose a lower-risk available node;
- user-required recovery asks for approval, provider setup, dependency setup, or
  missing input;
- invalid catalog definitions are not automatically recoverable at runtime.

## Testing Strategy

Catalog unit tests:

- convert internal tool manifests into `NodeDefinition`;
- register system model, human, verifier, and output nodes;
- validate capabilities, ports, execution bindings, permissions, examples, and
  availability;
- report invalid definitions consistently.

Resolver tests:

- exact capability match;
- multiple candidate ranking;
- preferred node id priority;
- unavailable node exclusion;
- unsupported capability failure without silent model fallback.

Deep Agent compile tests:

- planning context includes catalog summaries;
- `PlanDraft` steps bind to catalog nodes;
- `RunGraphNode.metadata.catalogNodeId` is written;
- tool nodes emit `toolBinding`;
- model nodes emit model policy metadata;
- human, verifier, and output nodes emit execution metadata;
- unsupported capabilities surface as review or compile findings.

Runtime tests:

- catalog-derived fixed-tool nodes execute existing tools;
- model nodes use the selected policy;
- human nodes interrupt and resume;
- verifier nodes check artifacts, format, citations, or coverage;
- permission and dependency failures produce structured events.

Frontend tests:

- node library displays catalog snapshot;
- search, filters, and detail views work;
- unavailable nodes show reason codes;
- canvas node details show catalog provenance;
- `NodePopover` shows capabilities, ports, permissions, and selection reason.

Eval and regression cases:

- document/report: upload documents, summarize, write a report, export PDF;
- web research: search, collect evidence, check citations, write report;
- office automation: extract action items, create checklist, analyze table.

## Acceptance Criteria

- Deep Agent planning receives a catalog summary, not just loose capability
  strings.
- Graph compile resolves nodes through `NodeCatalogResolver`.
- Core graph nodes include `catalogNodeId` metadata.
- Existing document tool bindings move away from hard-coded compile tables.
- Frontend can show a read-only catalog and catalog provenance on generated
  nodes.
- Unsupported capabilities fail explicitly or ask for user action.
- Internal catalog definitions are covered by tests.

