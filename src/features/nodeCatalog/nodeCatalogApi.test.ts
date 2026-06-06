import { invoke } from "@tauri-apps/api/core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { getNodeCatalog } from "./nodeCatalogApi";

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(),
}));

const invokeMock = vi.mocked(invoke);

afterEach(() => {
  delete (globalThis as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
  vi.restoreAllMocks();
});

describe("node catalog API", () => {
  it("maps sidecar snake_case catalog payload to frontend camelCase", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          schema_version: 1,
          generated_at: "2026-06-06T00:00:00+00:00",
          nodes: [
            {
              node_id: "document.convert.markdown",
              kind: "tool",
              display_name: "Document to Markdown",
              description: "Convert document.",
              category: "document",
              capabilities: ["document.convert.markdown"],
              input_ports: [
                {
                  id: "document-input",
                  label: "Document",
                  data_type: "document",
                  required: true,
                  multiple: false,
                  description: "Input document.",
                },
              ],
              output_ports: [
                {
                  id: "markdown-output",
                  label: "Markdown",
                  data_type: "markdown",
                  required: true,
                  multiple: false,
                  description: "Converted markdown.",
                },
              ],
              execution: {
                type: "tool",
                tool_id: "document.markitdown_convert",
                operation: "convert_local_file",
                binding_ref: "document.markitdown_convert.convert_local_file",
              },
              permissions: {
                permissions: ["read_project_files"],
                risk_level: "medium",
                requires_approval: false,
                filesystem: "project_read",
                network: "none",
                sandbox: "sidecar",
              },
              examples: [
                {
                  title: "Convert a brief",
                  input: { path: "brief.docx" },
                },
              ],
              source: "internal_tool",
              version: "0.1.0",
              availability: {
                status: "available",
                reason_code: null,
                message: null,
              },
            },
          ],
          diagnostics: [
            {
              code: "duplicate_node_id",
              node_id: "document.convert.markdown",
              message: "Duplicate node ignored.",
            },
          ],
          source_summary: {
            internal_tool_count: 1,
            system_node_count: 2,
            mcp_node_count: 3,
            plugin_node_count: 4,
            available_node_count: 5,
          },
        }),
        { headers: { "Content-Type": "application/json" } },
      ),
    );

    const catalog = await getNodeCatalog();

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/agent/node-catalog",
      expect.objectContaining({
        method: "GET",
        headers: {},
      }),
    );
    expect(invokeMock).not.toHaveBeenCalled();
    expect(catalog.schemaVersion).toBe(1);
    expect(catalog.generatedAt).toBe("2026-06-06T00:00:00+00:00");
    expect(catalog.nodes[0]).toMatchObject({
      nodeId: "document.convert.markdown",
      displayName: "Document to Markdown",
      capabilities: ["document.convert.markdown"],
      source: "internal_tool",
      version: "0.1.0",
      availability: {
        status: "available",
        reasonCode: null,
        message: null,
      },
    });
    expect(catalog.nodes[0].inputPorts[0].dataType).toBe("document");
    expect(catalog.nodes[0].outputPorts[0].dataType).toBe("markdown");
    expect(catalog.nodes[0].execution).toMatchObject({
      type: "tool",
      toolId: "document.markitdown_convert",
      operation: "convert_local_file",
      bindingRef: "document.markitdown_convert.convert_local_file",
    });
    expect(catalog.nodes[0].permissions).toMatchObject({
      permissions: ["read_project_files"],
      riskLevel: "medium",
      requiresApproval: false,
      filesystem: "project_read",
      network: "none",
      sandbox: "sidecar",
    });
    expect(catalog.nodes[0].examples).toEqual([
      { title: "Convert a brief", input: { path: "brief.docx" } },
    ]);
    expect(catalog.diagnostics[0]).toEqual({
      code: "duplicate_node_id",
      nodeId: "document.convert.markdown",
      message: "Duplicate node ignored.",
    });
    expect(catalog.sourceSummary).toEqual({
      internalToolCount: 1,
      systemNodeCount: 2,
      mcpNodeCount: 3,
      pluginNodeCount: 4,
      availableNodeCount: 5,
    });
  });

  it("adds the sidecar auth token when running inside Tauri", async () => {
    Object.defineProperty(globalThis, "__TAURI_INTERNALS__", {
      value: {},
      configurable: true,
    });
    invokeMock.mockResolvedValue("sidecar-token");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          schema_version: 1,
          generated_at: "2026-06-06T00:00:00+00:00",
          nodes: [],
          diagnostics: [],
          source_summary: {},
        }),
      ),
    );

    await getNodeCatalog();

    expect(invokeMock).toHaveBeenCalledWith("get_sidecar_auth_token");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/agent/node-catalog",
      expect.objectContaining({
        headers: { "X-Alita-Sidecar-Token": "sidecar-token" },
      }),
    );
  });

  it("throws when the sidecar returns a non-success status", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("no", { status: 503 }),
    );

    await expect(getNodeCatalog()).rejects.toThrow(
      "Agent sidecar returned 503",
    );
  });
});
