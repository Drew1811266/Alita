import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { NodePopover } from "./NodePopover";
import type { AgentNode } from "../../shared/types";

const toolNode: AgentNode = {
  nodeId: "document-parse",
  nodeType: "fixed_tool",
  displayName: "文档解析",
  status: "ready",
  inputPorts: [{ id: "document", label: "原始文档", dataType: "document" }],
  outputPorts: [{ id: "structured", label: "结构化内容", dataType: "json" }],
  dependencies: ["document-input"],
  toolRef: "document.extract_text",
  summary: "读取文档正文、标题层级和基础元数据。",
  createdBy: "agent",
  artifactRefs: [],
  retryCount: 2,
  position: { x: 0, y: 0 },
};

const modelNode: AgentNode = {
  ...toolNode,
  nodeId: "report-generate",
  nodeType: "model",
  displayName: "报告生成",
  toolRef: undefined,
  modelRef: "gpt-report-writer",
  summary: "根据整理后的内容生成中文报告初稿。",
  inputPorts: [{ id: "outline", label: "报告提纲", dataType: "json" }],
  outputPorts: [{ id: "report", label: "报告正文", dataType: "text" }],
  retryCount: 0,
};

const unknownToolNode: AgentNode = {
  ...toolNode,
  nodeId: "unknown-tool",
  toolRef: "external.raw_unknown_tool",
};

const unknownModelNode: AgentNode = {
  ...modelNode,
  nodeId: "unknown-model",
  modelRef: "raw-unknown-model",
};

function renderPopover(node: AgentNode) {
  return renderToStaticMarkup(
    <NodePopover node={node} onClose={() => undefined} />,
  );
}

describe("NodePopover", () => {
  it("renders Chinese tool node details", () => {
    const markup = renderPopover(toolNode);

    expect(markup).toContain("文档解析");
    expect(markup).toContain('aria-label="关闭节点信息"');
    expect(markup).toContain("关闭");
    expect(markup).toContain("固定工具");
    expect(markup).toContain("准备中");
    expect(markup).toContain("读取文档正文、标题层级和基础元数据。");
    expect(markup).toContain("提取文档正文和结构");
    expect(markup).not.toContain("document.extract_text");
    expect(markup).toContain("原始文档");
    expect(markup).toContain("结构化内容");
    expect(markup).toContain("2 次");
  });

  it("renders Chinese model node details", () => {
    const markup = renderPopover(modelNode);

    expect(markup).toContain("报告生成");
    expect(markup).toContain("模型调用");
    expect(markup).toContain("根据整理后的内容生成中文报告初稿。");
    expect(markup).toContain("生成报告初稿");
    expect(markup).not.toContain("gpt-report-writer");
    expect(markup).toContain("报告提纲");
    expect(markup).toContain("报告正文");
    expect(markup).toContain("0 次");
  });

  it("renders a Chinese fallback for unknown tool refs", () => {
    const markup = renderPopover(unknownToolNode);

    expect(markup).toContain("已注册工具能力");
    expect(markup).not.toContain("external.raw_unknown_tool");
  });

  it("renders a Chinese fallback for unknown model refs", () => {
    const markup = renderPopover(unknownModelNode);

    expect(markup).toContain("模型推理能力");
    expect(markup).not.toContain("raw-unknown-model");
  });
  it("renders artifact references when a node has outputs", () => {
    const markup = renderPopover({
      ...toolNode,
      status: "completed",
      artifactRefs: ["D:\\Project\\artifacts\\report.md"],
    });

    expect(markup).toContain("D:\\Project\\artifacts\\report.md");
  });

  it("renders artifact open and reveal actions when handlers are available", () => {
    const markup = renderToStaticMarkup(
      <NodePopover
        node={{
          ...toolNode,
          status: "completed",
          artifactRefs: ["D:\\Project\\artifacts\\report.md"],
        }}
        onClose={() => undefined}
        onOpenArtifact={() => undefined}
        onRevealArtifact={() => undefined}
      />,
    );

    expect(markup).toContain("打开");
    expect(markup).toContain("定位");
  });

  it("renders last run error and rerun-from-node action", () => {
    const markup = renderToStaticMarkup(
      <NodePopover
        node={{
          ...toolNode,
          status: "failed",
          lastRun: {
            nodeRunId: "nr-1",
            runId: "run-1",
            nodeId: "document-parse",
            status: "failed",
            startedAt: "2026-05-10T00:00:00.000Z",
            completedAt: "2026-05-10T00:00:01.000Z",
            artifactRefs: [],
            error: "读取失败",
          },
        }}
        onClose={() => undefined}
        onRunFromNode={() => undefined}
      />,
    );

    expect(markup).toContain("读取失败");
    expect(markup).toContain("从此节点重跑");
  });

  it("hides execution controls for temporary script review nodes even when rerun is available", () => {
    const markup = renderToStaticMarkup(
      <NodePopover
        node={{
          ...toolNode,
          nodeId: "temporary-script",
          nodeType: "temporary_placeholder",
          displayName: "临时脚本",
          status: "needs_permission",
          scriptReview: {
            status: "reviewing",
            summary: "Temporary script needs file read permission.",
            permissions: ["read_project_files"],
          },
        }}
        onClose={() => undefined}
        onRunFromNode={() => undefined}
      />,
    );

    expect(markup).not.toContain("从此节点重跑");
    expect(markup).not.toContain("运行脚本");
  });

  it("renders temporary script safety state and last run error code without execution controls", () => {
    const markup = renderPopover({
      ...toolNode,
      nodeType: "temporary_placeholder",
      displayName: "临时脚本",
      status: "needs_permission",
      lastRun: {
        nodeRunId: "nr-2",
        runId: "run-2",
        nodeId: "temporary-script",
        status: "failed",
        startedAt: "2026-05-10T00:00:00.000Z",
        completedAt: "2026-05-10T00:00:01.000Z",
        artifactRefs: [],
        error: "调用已停用",
        errorCode: "tool_disabled",
      },
      scriptReview: {
        status: "reviewing",
        summary: "Temporary script needs file read permission.",
        permissions: ["read_project_files"],
      },
    });

    expect(markup).toContain("tool_disabled");
    expect(markup).toContain("Temporary script needs file read permission.");
    expect(markup).toContain("read_project_files");
    expect(markup).not.toContain("运行脚本");
  });
});
