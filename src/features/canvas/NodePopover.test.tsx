import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { NodePopover } from "./NodePopover";
import type { AgentNode } from "../../shared/types";

const toolNode: AgentNode = {
  nodeId: "document-parse",
  nodeType: "fixed_tool",
  displayName: "Document parse",
  status: "ready",
  inputPorts: [{ id: "document", label: "Source document", dataType: "document" }],
  outputPorts: [{ id: "structured", label: "Structured content", dataType: "json" }],
  dependencies: ["document-input"],
  toolRef: "document.extract_text",
  summary: "Read document text.",
  createdBy: "agent",
  artifactRefs: [],
  retryCount: 2,
  position: { x: 0, y: 0 },
};

const modelNode: AgentNode = {
  ...toolNode,
  nodeId: "report-generate",
  nodeType: "model",
  displayName: "Report generate",
  toolRef: undefined,
  modelRef: "gpt-report-writer",
  summary: "Generate report.",
  inputPorts: [{ id: "outline", label: "Report outline", dataType: "json" }],
  outputPorts: [{ id: "report", label: "Report body", dataType: "text" }],
  retryCount: 0,
};

const researchToolNode: AgentNode = {
  ...toolNode,
  nodeId: "research-parallel-search",
  toolRef: "web.search.parallel",
  displayName: "Parallel web search",
};

function renderPopover(node: AgentNode) {
  return renderToStaticMarkup(
    <NodePopover node={node} onClose={() => undefined} />,
  );
}

describe("NodePopover", () => {
  it("renders tool node details without raw known tool refs", () => {
    const markup = renderPopover(toolNode);

    expect(markup).toContain("Document parse");
    expect(markup).not.toContain("document.extract_text");
    expect(markup).toContain("Source document");
    expect(markup).toContain("Structured content");
  });

  it("renders model node details without raw known model refs", () => {
    const markup = renderPopover(modelNode);

    expect(markup).toContain("Report generate");
    expect(markup).not.toContain("gpt-report-writer");
    expect(markup).toContain("Report outline");
    expect(markup).toContain("Report body");
  });

  it("renders artifact references and artifact actions", () => {
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

    expect(markup).toContain("D:\\Project\\artifacts\\report.md");
    expect(markup).toContain("nodePopoverInlineButton");
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
            error: "read failed",
            errorCode: "tool_disabled",
          },
        }}
        onClose={() => undefined}
        onRunFromNode={() => undefined}
      />,
    );

    expect(markup).toContain("read failed");
    expect(markup).toContain("tool_disabled");
    expect(markup).toContain("nodePopoverAction");
  });

  it("hides execution controls for temporary script review nodes", () => {
    const markup = renderToStaticMarkup(
      <NodePopover
        node={{
          ...toolNode,
          nodeId: "temporary-script",
          nodeType: "temporary_placeholder",
          displayName: "Temporary script",
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

    expect(markup).toContain("Temporary script needs file read permission.");
    expect(markup).not.toContain("nodePopoverAction");
  });

  it("renders rerun-from-node action for research graph nodes", () => {
    const markup = renderToStaticMarkup(
      <NodePopover
        node={researchToolNode}
        onClose={() => undefined}
        onRunFromNode={() => undefined}
      />,
    );

    expect(markup).toContain("Parallel web search");
    expect(markup).toContain("nodePopoverAction");
  });
});
