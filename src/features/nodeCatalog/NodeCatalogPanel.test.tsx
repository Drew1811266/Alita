import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { NodeCatalogPanel } from "./NodeCatalogPanel";
import type { NodeCatalogSnapshot } from "../../shared/types";

const catalog: NodeCatalogSnapshot = {
  schemaVersion: 1,
  generatedAt: "2026-06-06T00:00:00+00:00",
  nodes: [
    {
      nodeId: "document.convert.markdown",
      kind: "tool",
      displayName: "文档转 Markdown",
      description: "把文档转换为 Markdown。",
      category: "document",
      capabilities: ["document.convert.markdown", "document.convert"],
      inputPorts: [
        {
          id: "document-input",
          label: "文档",
          dataType: "document",
          required: true,
          multiple: false,
          description: "待转换的文档。",
        },
      ],
      outputPorts: [
        {
          id: "markdown-output",
          label: "Markdown",
          dataType: "markdown",
          required: true,
          multiple: false,
          description: "转换后的 Markdown。",
        },
      ],
      execution: {
        type: "tool",
        toolId: "document.markitdown_convert",
        operation: "convert_local_file",
        bindingRef: "document.markitdown_convert.convert_local_file",
      },
      permissions: {
        permissions: ["read_project_files"],
        riskLevel: "medium",
        requiresApproval: false,
        filesystem: "project_read",
        network: "none",
        sandbox: "sidecar",
      },
      examples: [],
      source: "internal_tool",
      version: "0.1.0",
      availability: { status: "available" },
    },
    {
      nodeId: "human.clarify",
      kind: "human",
      displayName: "澄清问题",
      description: "向用户澄清缺失信息。",
      category: "human",
      capabilities: ["human.clarify"],
      inputPorts: [],
      outputPorts: [],
      execution: { type: "human" },
      permissions: {
        permissions: [],
        riskLevel: "low",
        requiresApproval: false,
        filesystem: "none",
        network: "none",
        sandbox: "none",
      },
      examples: [],
      source: "system",
      version: "1.0.0",
      availability: { status: "unavailable", reasonCode: "manual_only" },
    },
  ],
  diagnostics: [],
  sourceSummary: {
    internalToolCount: 1,
    systemNodeCount: 1,
    mcpNodeCount: 0,
    pluginNodeCount: 0,
    availableNodeCount: 1,
  },
};

describe("NodeCatalogPanel", () => {
  it("renders search controls, category filter, and read-only node details", () => {
    const markup = renderToStaticMarkup(
      <NodeCatalogPanel
        catalog={catalog}
        error={null}
        loading={false}
        onClose={() => undefined}
        onReload={() => undefined}
      />,
    );

    expect(markup).toContain("节点库");
    expect(markup).toContain("搜索节点、能力或说明");
    expect(markup).toContain("节点分类");
    expect(markup).toContain("文档转 Markdown");
    expect(markup).toContain("document.convert.markdown");
    expect(markup).toContain("把文档转换为 Markdown。");
    expect(markup).toContain("document.convert");
    expect(markup).toContain("文档 · document");
    expect(markup).toContain("Markdown · markdown");
    expect(markup).toContain("read_project_files");
    expect(markup).toContain("project_read");
    expect(markup).toContain("sidecar");
    expect(markup).toContain("internal_tool");
    expect(markup).toContain("document.markitdown_convert");
    expect(markup).toContain("澄清问题");
    expect(markup).toContain("manual_only");
  });

  it("renders loading and error states", () => {
    const markup = renderToStaticMarkup(
      <NodeCatalogPanel
        catalog={null}
        error="load failed"
        loading
        onClose={() => undefined}
        onReload={() => undefined}
      />,
    );

    expect(markup).toContain("正在加载节点库");
    expect(markup).toContain("load failed");
    expect(markup).toContain("重新加载");
    expect(markup).toContain("关闭");
  });
});
