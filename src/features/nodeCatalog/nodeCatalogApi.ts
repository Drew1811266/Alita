import { invoke } from "@tauri-apps/api/core";

import type {
  CatalogNodeExample,
  CatalogNodePort,
  NodeCatalogEntry,
  NodeCatalogSnapshot,
} from "../../shared/types";

const SIDECAR_URL = "http://127.0.0.1:8765";
const SIDECAR_TOKEN_HEADER = "X-Alita-Sidecar-Token";

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
  const data = asRecord(payload);
  const sourceSummary = asRecord(data.source_summary);
  const availableNodeCount = optionalNumber(sourceSummary.available_node_count);

  return {
    schemaVersion: numberValue(data.schema_version),
    generatedAt: stringValue(data.generated_at),
    nodes: arrayValue(data.nodes).map(toCatalogNode),
    diagnostics: arrayValue(data.diagnostics).map(toDiagnostic),
    sourceSummary: {
      internalToolCount: numberValue(sourceSummary.internal_tool_count),
      systemNodeCount: numberValue(sourceSummary.system_node_count),
      mcpNodeCount: numberValue(sourceSummary.mcp_node_count),
      pluginNodeCount: numberValue(sourceSummary.plugin_node_count),
      ...(availableNodeCount !== undefined ? { availableNodeCount } : {}),
    },
  };
}

function toCatalogNode(value: unknown): NodeCatalogEntry {
  const node = asRecord(value);
  const execution = asRecord(node.execution);
  const permissions = asRecord(node.permissions);
  const availability = asRecord(node.availability);

  return {
    nodeId: stringValue(node.node_id),
    kind: stringValue(node.kind, "tool") as NodeCatalogEntry["kind"],
    displayName: stringValue(node.display_name),
    description: stringValue(node.description),
    category: stringValue(
      node.category,
      "reasoning",
    ) as NodeCatalogEntry["category"],
    capabilities: stringArray(node.capabilities),
    inputPorts: arrayValue(node.input_ports).map(toPort),
    outputPorts: arrayValue(node.output_ports).map(toPort),
    execution: {
      type: stringValue(
        execution.type,
        "tool",
      ) as NodeCatalogEntry["execution"]["type"],
      toolId: nullableString(execution.tool_id),
      operation: nullableString(execution.operation),
      bindingRef: nullableString(execution.binding_ref),
      modelPolicy: nullableString(execution.model_policy),
      verifierType: nullableString(execution.verifier_type),
      outputType: nullableString(execution.output_type),
    },
    permissions: {
      permissions: stringArray(permissions.permissions),
      riskLevel: stringValue(
        permissions.risk_level,
        "low",
      ) as NodeCatalogEntry["permissions"]["riskLevel"],
      requiresApproval: Boolean(permissions.requires_approval),
      filesystem: stringValue(
        permissions.filesystem,
        "none",
      ) as NodeCatalogEntry["permissions"]["filesystem"],
      network: stringValue(
        permissions.network,
        "none",
      ) as NodeCatalogEntry["permissions"]["network"],
      sandbox: stringValue(
        permissions.sandbox,
        "none",
      ) as NodeCatalogEntry["permissions"]["sandbox"],
    },
    examples: arrayValue(node.examples).map(toExample),
    source: stringValue(node.source, "system") as NodeCatalogEntry["source"],
    version: stringValue(node.version),
    availability: {
      status: stringValue(
        availability.status,
        "unavailable",
      ) as NodeCatalogEntry["availability"]["status"],
      reasonCode: nullableString(availability.reason_code),
      message: nullableString(availability.message),
    },
  };
}

function toPort(value: unknown): CatalogNodePort {
  const port = asRecord(value);
  return {
    id: stringValue(port.id),
    label: stringValue(port.label),
    dataType: stringValue(
      port.data_type,
      "text",
    ) as CatalogNodePort["dataType"],
    required: Boolean(port.required),
    multiple: Boolean(port.multiple),
    description: stringValue(port.description),
  };
}

function toExample(value: unknown): CatalogNodeExample {
  const example = asRecord(value);
  return {
    title: stringValue(example.title),
    input: asRecord(example.input),
  };
}

function toDiagnostic(value: unknown): NodeCatalogSnapshot["diagnostics"][number] {
  const diagnostic = asRecord(value);
  return {
    code: stringValue(diagnostic.code),
    nodeId: nullableString(diagnostic.node_id),
    message: stringValue(diagnostic.message),
  };
}

function asRecord(value: unknown): JsonRecord {
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    return value as JsonRecord;
  }
  return {};
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function stringArray(value: unknown): string[] {
  return arrayValue(value).map(String);
}

function stringValue(value: unknown, fallback = ""): string {
  return value == null ? fallback : String(value);
}

function nullableString(value: unknown): string | null {
  return value == null ? null : String(value);
}

function numberValue(value: unknown): number {
  return Number(value ?? 0);
}

function optionalNumber(value: unknown): number | undefined {
  return value == null ? undefined : Number(value);
}
