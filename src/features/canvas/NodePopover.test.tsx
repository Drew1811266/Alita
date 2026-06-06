import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

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

type ElementLike = {
  props?: {
    children?: unknown;
    className?: string;
    onClick?: () => void;
  };
};

function findElementsByClass(element: unknown, className: string): ElementLike[] {
  if (!element || typeof element !== "object") {
    return [];
  }

  const candidate = element as ElementLike;
  const matches =
    typeof candidate.props?.className === "string" &&
    candidate.props.className.split(/\s+/).includes(className)
      ? [candidate]
      : [];
  const children = candidate.props?.children;
  const nested = Array.isArray(children)
    ? children.flatMap((child) => findElementsByClass(child, className))
    : findElementsByClass(children, className);

  return [...matches, ...nested];
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

  it("marks planning nodes as non-executable and shows estimates plus runtime notices", () => {
    const markup = renderToStaticMarkup(
      <NodePopover
        node={{
          ...toolNode,
          nodeId: "plan",
          nodeType: "planning",
          displayName: "Plan research route",
          status: "completed",
          summary: "Decision: answer with a research flow.",
          estimate: {
            durationMs: 3000,
            cpu: "low",
            memory: "128MB",
          },
          runtimeNotice: {
            kind: "duration_exceeded",
            message: "Planning took longer than expected.",
            actualDurationMs: 4200,
          },
        }}
        onClose={() => undefined}
        onRunFromNode={() => undefined}
      />,
    );

    expect(markup).toContain("Decision: answer with a research flow.");
    expect(markup).toContain("不可执行");
    expect(markup).not.toContain("nodePopoverAction");
    expect(markup).toContain("3s");
    expect(markup).toContain("128MB");
    expect(markup).toContain("Planning took longer than expected.");
  });

  it("renders plan-step provenance when node metadata includes it", () => {
    const markup = renderPopover({
      ...toolNode,
      metadata: {
        sourcePlanDraftId: "plan-1",
        sourcePlanStepId: "step-risk",
        rationale: "Risk extraction is required by the user goal.",
        expectedOutput: "A severity-ranked risk list.",
        verificationCriteria: ["Every risk has a source clause."],
        requiredCapabilities: ["model.reasoning"],
      },
    });

    expect(markup).toContain("计划来源");
    expect(markup).toContain("step-risk");
    expect(markup).toContain("Risk extraction is required by the user goal.");
    expect(markup).toContain("A severity-ranked risk list.");
    expect(markup).toContain("Every risk has a source clause.");
  });

  it("renders catalog provenance when node metadata includes it", () => {
    const markup = renderPopover({
      ...toolNode,
      metadata: {
        catalogNodeId: "document.convert.markdown",
        catalogDisplayName: "Markdown converter",
        catalogCapabilities: ["document.convert", "markdown.emit"],
        catalogRiskLevel: "low",
        executionKind: "tool",
        nodeSelectionReason: "Selected because the user asked for Markdown output.",
      },
    });

    expect(markup).toContain("节点库来源");
    expect(markup).toContain("Markdown converter");
    expect(markup).toContain("document.convert.markdown");
    expect(markup).toContain("tool");
    expect(markup).toContain("low");
    expect(markup).toContain("Selected because the user asked for Markdown output.");
    expect(markup).toContain("document.convert");
  });

  it("ignores malformed plan-step provenance metadata", () => {
    const node: AgentNode = {
      ...toolNode,
      metadata: {
        sourcePlanStepId: {},
        rationale: {},
        expectedOutput: {},
        verificationCriteria: "not-an-array",
      } as unknown as AgentNode["metadata"],
    };

    expect(() => renderPopover(node)).not.toThrow();
    expect(renderPopover(node)).not.toContain("计划来源");
  });

  it("ignores malformed catalog provenance fields", () => {
    const node: AgentNode = {
      ...toolNode,
      metadata: {
        catalogNodeId: "document.convert.markdown",
        catalogDisplayName: { label: "bad display name" },
        catalogCapabilities: "document.convert",
        catalogRiskLevel: { level: "high" },
        executionKind: { type: "tool" },
        nodeSelectionReason: { reason: "bad reason" },
      } as unknown as AgentNode["metadata"],
    };

    const markup = renderPopover(node);

    expect(() => renderPopover(node)).not.toThrow();
    expect(markup).toContain("节点库来源");
    expect(markup).toContain("document.convert.markdown");
    expect(markup).not.toContain("[object Object]");
    expect(markup).not.toContain("bad display name");
    expect(markup).not.toContain("bad reason");
  });

  it("filters malformed catalog provenance capability entries", () => {
    const mixedMarkup = renderPopover({
      ...toolNode,
      metadata: {
        catalogNodeId: "document.convert.markdown",
        catalogCapabilities: [{ bad: true }, "safe.capability"],
      } as unknown as AgentNode["metadata"],
    });
    const objectOnlyMarkup = renderPopover({
      ...toolNode,
      metadata: {
        catalogNodeId: "human.clarify",
        catalogCapabilities: [{ bad: true }],
      } as unknown as AgentNode["metadata"],
    });

    expect(mixedMarkup).toContain("safe.capability");
    expect(mixedMarkup).not.toContain("[object Object]");
    expect(objectOnlyMarkup).toContain("节点库能力");
    expect(objectOnlyMarkup).toContain(
      '<span class="nodePopoverEmpty">无</span>',
    );
    expect(objectOnlyMarkup).not.toContain("[object Object]");
  });

  it("renders temporary script risk, approval, preview, contracts, and usage", () => {
    const markup = renderToStaticMarkup(
      <NodePopover
        node={{
          ...toolNode,
          nodeId: "temporary-script",
          nodeType: "temporary_script",
          displayName: "Temporary script",
          status: "needs_permission",
          summary: "Inspect CSV rows with generated code.",
          scriptReview: {
            status: "approved",
            summary: "Needs read-only access to project CSV files.",
            permissions: ["read_project_files"],
            riskLevel: "high",
            requiresApproval: true,
            approvalFingerprint: "sha256:abc123",
            codePreview: "import pandas as pd\nprint(pd.read_csv(path).head())",
            inputContract: { path: "string" },
            outputContract: { previewRows: "array" },
          },
          estimate: {
            durationMs: 8000,
            memory: "512MB",
          },
          resourceUsage: {
            durationMs: 9100,
            memory: "640MB",
            network: "none",
          },
          runtimeNotice: {
            kind: "memory_exceeded",
            message: "Memory usage exceeded estimate.",
            actualDurationMs: 9100,
          },
        }}
        onClose={() => undefined}
        onRunFromNode={() => undefined}
      />,
    );

    expect(markup).toContain("风险: high");
    expect(markup).toContain("审批: approved");
    expect(markup).toContain("sha256:abc123");
    expect(markup).toContain("import pandas as pd");
    expect(markup).toContain("&quot;path&quot;: &quot;string&quot;");
    expect(markup).toContain("&quot;previewRows&quot;: &quot;array&quot;");
    expect(markup).toContain("8s");
    expect(markup).toContain("640MB");
    expect(markup).toContain("Memory usage exceeded estimate.");
  });

  it("renders approve and reject controls for high-risk temporary scripts", () => {
    const markup = renderToStaticMarkup(
      <NodePopover
        node={{
          ...toolNode,
          nodeId: "temporary-script",
          nodeType: "temporary_script",
          displayName: "Temporary script",
          status: "needs_permission",
          scriptReview: {
            status: "reviewing",
            summary: "Needs review before execution.",
            permissions: ["read_project_files"],
            riskLevel: "high",
            requiresApproval: true,
            approvalFingerprint: "sha256:abc123",
          },
        }}
        onApproveTemporaryScript={() => undefined}
        onClose={() => undefined}
        onRejectTemporaryScript={() => undefined}
      />,
    );

    expect(markup).toContain("nodePopoverPermissionActions");
    expect(markup).toContain("nodePopoverApproveButton");
    expect(markup).toContain("nodePopoverRejectButton");
    expect(markup).toContain("批准");
    expect(markup).toContain("拒绝");
  });

  it("blocks rerun controls for high-risk temporary scripts until review", () => {
    const markup = renderToStaticMarkup(
      <NodePopover
        node={{
          ...toolNode,
          nodeId: "temporary-script",
          nodeType: "temporary_script",
          displayName: "Temporary script",
          status: "needs_permission",
          scriptReview: {
            status: "reviewing",
            summary: "Needs review before execution.",
            permissions: ["read_project_files"],
            riskLevel: "high",
            requiresApproval: true,
            approvalFingerprint: "sha256:abc123",
          },
        }}
        onApproveTemporaryScript={() => undefined}
        onClose={() => undefined}
        onRejectTemporaryScript={() => undefined}
        onRunFromNode={() => undefined}
      />,
    );

    expect(markup).not.toContain("nodePopoverAction");
    expect(markup).toContain("nodePopoverPermissionActions");
    expect(markup).toContain("sha256:abc123");
  });

  it("calls temporary script approval and rejection callbacks", () => {
    const approve = vi.fn();
    const reject = vi.fn();
    const node: AgentNode = {
      ...toolNode,
      nodeId: "temporary-script",
      nodeType: "temporary_script",
      displayName: "Temporary script",
      status: "needs_permission",
      scriptReview: {
        status: "reviewing",
        summary: "Needs review before execution.",
        permissions: ["read_project_files"],
        riskLevel: "high",
        requiresApproval: true,
      },
    };

    const rendered = NodePopover({
      node,
      onApproveTemporaryScript: approve,
      onClose: () => undefined,
      onRejectTemporaryScript: reject,
    });

    findElementsByClass(rendered, "nodePopoverApproveButton")[0].props?.onClick?.();
    findElementsByClass(rendered, "nodePopoverRejectButton")[0].props?.onClick?.();

    expect(approve).toHaveBeenCalledWith("temporary-script");
    expect(reject).toHaveBeenCalledWith("temporary-script");
  });
});
