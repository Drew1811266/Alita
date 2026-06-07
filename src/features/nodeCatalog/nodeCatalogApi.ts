import { invoke } from "@tauri-apps/api/core";

import type {
  CatalogNodeExample,
  CatalogNodePort,
  NodeCatalogEntry,
  NodeCatalogSnapshot,
} from "../../shared/types";

const SIDECAR_URL = "http://127.0.0.1:8765";
const SIDECAR_TOKEN_HEADER = "X-Alita-Sidecar-Token";

const nodeKinds = ["tool", "model", "human", "verifier", "output"] as const;
const nodeCategories = [
  "document",
  "web",
  "data",
  "reasoning",
  "human",
  "verification",
  "output",
] as const;
const portDataTypes = [
  "text",
  "markdown",
  "document",
  "table",
  "json",
  "artifact",
  "url",
  "query",
  "decision",
] as const;
const executionTypes = ["tool", "model", "human", "verifier", "output"] as const;
const riskLevels = ["low", "medium", "high"] as const;
const filesystemModes = ["none", "project_read", "project_write"] as const;
const networkModes = ["none", "external"] as const;
const sandboxModes = ["none", "sidecar", "external"] as const;
const nodeSources = ["internal_tool", "system", "mcp", "plugin"] as const;
const modelPolicies = [
  "deep_reasoning",
  "node_reasoning",
  "fast_chat",
  "fast_factual",
] as const;
const verifierTypes = [
  "artifact_exists",
  "citation_check",
  "schema_check",
  "coverage_check",
] as const;
const outputTypes = [
  "markdown",
  "docx",
  "pdf",
  "table",
  "checklist",
  "final_response",
] as const;
const availabilityStatuses = [
  "available",
  "degraded",
  "unavailable",
] as const;

type JsonRecord = Record<string, unknown>;

export async function getNodeCatalog(): Promise<NodeCatalogSnapshot> {
  const response = await fetch(`${SIDECAR_URL}/agent/node-catalog`, {
    method: "GET",
    headers: await sidecarHeaders(),
  });

  if (!response.ok) {
    throw new Error(`Agent sidecar returned ${response.status}`);
  }

  return toCatalogSnapshot(await response.json());
}

async function sidecarHeaders(): Promise<Record<string, string>> {
  const token = await getSidecarAuthToken();
  return token ? { [SIDECAR_TOKEN_HEADER]: token } : {};
}

async function getSidecarAuthToken(): Promise<string | null> {
  if (!isTauriRuntime()) {
    return null;
  }
  return invoke<string>("get_sidecar_auth_token");
}

function isTauriRuntime(): boolean {
  return "__TAURI_INTERNALS__" in globalThis;
}

function toCatalogSnapshot(payload: unknown): NodeCatalogSnapshot {
  const data = requiredObject(payload, "root");
  const sourceSummary = requiredObject(data.source_summary, "source_summary");
  const availableNodeCount = optionalFiniteNumber(
    sourceSummary.available_node_count,
    "source_summary.available_node_count",
  );

  return {
    schemaVersion: requiredFiniteNumber(data.schema_version, "schema_version"),
    generatedAt: requiredString(data.generated_at, "generated_at"),
    nodes: requiredArray(data.nodes, "nodes").map((node, index) =>
      toCatalogNode(node, `nodes[${index}]`),
    ),
    diagnostics: requiredArray(data.diagnostics, "diagnostics").map(
      (diagnostic, index) => toDiagnostic(diagnostic, `diagnostics[${index}]`),
    ),
    sourceSummary: {
      internalToolCount: requiredFiniteNumber(
        sourceSummary.internal_tool_count,
        "source_summary.internal_tool_count",
      ),
      systemNodeCount: requiredFiniteNumber(
        sourceSummary.system_node_count,
        "source_summary.system_node_count",
      ),
      mcpNodeCount: requiredFiniteNumber(
        sourceSummary.mcp_node_count,
        "source_summary.mcp_node_count",
      ),
      pluginNodeCount: requiredFiniteNumber(
        sourceSummary.plugin_node_count,
        "source_summary.plugin_node_count",
      ),
      ...(availableNodeCount !== undefined ? { availableNodeCount } : {}),
    },
  };
}

function toCatalogNode(value: unknown, path: string): NodeCatalogEntry {
  const node = requiredObject(value, path);
  const execution = requiredObject(node.execution, `${path}.execution`);
  const permissions = requiredObject(node.permissions, `${path}.permissions`);
  const availability = requiredObject(node.availability, `${path}.availability`);

  return {
    nodeId: requiredString(node.node_id, `${path}.node_id`),
    kind: requiredEnum(node.kind, `${path}.kind`, nodeKinds),
    displayName: requiredString(node.display_name, `${path}.display_name`),
    description: requiredString(node.description, `${path}.description`),
    category: requiredEnum(node.category, `${path}.category`, nodeCategories),
    capabilities: requiredStringArray(
      node.capabilities,
      `${path}.capabilities`,
    ),
    inputPorts: requiredArray(node.input_ports, `${path}.input_ports`).map(
      (port, index) => toPort(port, `${path}.input_ports[${index}]`),
    ),
    outputPorts: requiredArray(node.output_ports, `${path}.output_ports`).map(
      (port, index) => toPort(port, `${path}.output_ports[${index}]`),
    ),
    execution: {
      type: requiredEnum(
        execution.type,
        `${path}.execution.type`,
        executionTypes,
      ),
      toolId: optionalNullableString(
        execution.tool_id,
        `${path}.execution.tool_id`,
      ),
      operation: optionalNullableString(
        execution.operation,
        `${path}.execution.operation`,
      ),
      bindingRef: optionalNullableString(
        execution.binding_ref,
        `${path}.execution.binding_ref`,
      ),
      modelPolicy: optionalNullableEnum(
        execution.model_policy,
        `${path}.execution.model_policy`,
        modelPolicies,
      ),
      verifierType: optionalNullableEnum(
        execution.verifier_type,
        `${path}.execution.verifier_type`,
        verifierTypes,
      ),
      outputType: optionalNullableEnum(
        execution.output_type,
        `${path}.execution.output_type`,
        outputTypes,
      ),
    },
    permissions: {
      permissions: requiredStringArray(
        permissions.permissions,
        `${path}.permissions.permissions`,
      ),
      riskLevel: requiredEnum(
        permissions.risk_level,
        `${path}.permissions.risk_level`,
        riskLevels,
      ),
      requiresApproval: requiredBoolean(
        permissions.requires_approval,
        `${path}.permissions.requires_approval`,
      ),
      filesystem: requiredEnum(
        permissions.filesystem,
        `${path}.permissions.filesystem`,
        filesystemModes,
      ),
      network: requiredEnum(
        permissions.network,
        `${path}.permissions.network`,
        networkModes,
      ),
      sandbox: requiredEnum(
        permissions.sandbox,
        `${path}.permissions.sandbox`,
        sandboxModes,
      ),
    },
    examples: requiredArray(node.examples, `${path}.examples`).map(
      (example, index) => toExample(example, `${path}.examples[${index}]`),
    ),
    source: requiredEnum(node.source, `${path}.source`, nodeSources),
    version: requiredString(node.version, `${path}.version`),
    availability: {
      status: requiredEnum(
        availability.status,
        `${path}.availability.status`,
        availabilityStatuses,
      ),
      reasonCode: optionalNullableString(
        availability.reason_code,
        `${path}.availability.reason_code`,
      ),
      message: optionalNullableString(
        availability.message,
        `${path}.availability.message`,
      ),
    },
  };
}

function toPort(value: unknown, path: string): CatalogNodePort {
  const port = requiredObject(value, path);
  return {
    id: requiredString(port.id, `${path}.id`),
    label: requiredString(port.label, `${path}.label`),
    dataType: requiredEnum(port.data_type, `${path}.data_type`, portDataTypes),
    required: requiredBoolean(port.required, `${path}.required`),
    multiple: requiredBoolean(port.multiple, `${path}.multiple`),
    description: requiredString(port.description, `${path}.description`),
  };
}

function toExample(value: unknown, path: string): CatalogNodeExample {
  const example = requiredObject(value, path);
  return {
    title: requiredString(example.title, `${path}.title`),
    input: requiredObject(example.input, `${path}.input`),
  };
}

function toDiagnostic(
  value: unknown,
  path: string,
): NodeCatalogSnapshot["diagnostics"][number] {
  const diagnostic = requiredObject(value, path);
  return {
    code: requiredString(diagnostic.code, `${path}.code`),
    nodeId: optionalNullableString(diagnostic.node_id, `${path}.node_id`),
    message: requiredString(diagnostic.message, `${path}.message`),
  };
}

function requiredObject(value: unknown, path: string): JsonRecord {
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    return value as JsonRecord;
  }
  malformed(path, "expected object");
}

function requiredArray(value: unknown, path: string): unknown[] {
  if (Array.isArray(value)) {
    return value;
  }
  malformed(path, "expected array");
}

function requiredString(value: unknown, path: string): string {
  if (typeof value === "string") {
    return value;
  }
  malformed(path, "expected string");
}

function requiredStringArray(value: unknown, path: string): string[] {
  return requiredArray(value, path).map((item, index) =>
    requiredString(item, `${path}[${index}]`),
  );
}

function optionalNullableString(value: unknown, path: string): string | null {
  if (value == null) {
    return null;
  }
  if (typeof value === "string") {
    return value;
  }
  malformed(path, "expected string or null");
}

function requiredFiniteNumber(value: unknown, path: string): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  malformed(path, "expected finite number");
}

function optionalFiniteNumber(
  value: unknown,
  path: string,
): number | undefined {
  if (value == null) {
    return undefined;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  malformed(path, "expected finite number or null");
}

function requiredBoolean(value: unknown, path: string): boolean {
  if (typeof value === "boolean") {
    return value;
  }
  malformed(path, "expected boolean");
}

function requiredEnum<T extends string>(
  value: unknown,
  path: string,
  allowed: readonly T[],
): T {
  if (typeof value === "string" && allowed.includes(value as T)) {
    return value as T;
  }
  malformed(path, `expected one of ${allowed.join(", ")}`);
}

function optionalNullableEnum<T extends string>(
  value: unknown,
  path: string,
  allowed: readonly T[],
): T | null {
  if (value == null) {
    return null;
  }
  return requiredEnum(value, path, allowed);
}

function malformed(path: string, reason: string): never {
  throw new Error(`Malformed node catalog payload at ${path}: ${reason}`);
}
