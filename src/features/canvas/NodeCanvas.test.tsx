import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { NodeCanvas } from "./NodeCanvas";
import { createDocumentGraph } from "./nodeLayout";
import type { NodeGraph } from "../../shared/types";

const researchGraph: NodeGraph = {
  graphId: "research-task-graph",
  nodes: [
    {
      nodeId: "research-parallel-search",
      nodeType: "fixed_tool",
      displayName: "Parallel web search",
      status: "ready",
      inputPorts: [],
      outputPorts: [],
      dependencies: [],
      toolRef: "web.search.parallel",
      summary: "Run planned web queries.",
      createdBy: "agent",
      artifactRefs: [],
      retryCount: 1,
      position: { x: 0, y: 0 },
    },
  ],
  edges: [],
};

describe("NodeCanvas", () => {
  it("renders a run button when graph exists", () => {
    const markup = renderToStaticMarkup(
      <NodeCanvas
        graph={createDocumentGraph()}
        running={false}
        onRun={() => undefined}
      />,
    );

    expect(markup).toContain("nodeCanvasRunButton");
  });

  it("renders the running state while a graph run is active", () => {
    const markup = renderToStaticMarkup(
      <NodeCanvas
        graph={createDocumentGraph()}
        running={true}
        onRun={() => undefined}
      />,
    );

    expect(markup).toContain("nodeCanvasRunButton");
    expect(markup).toContain("disabled");
  });

  it("renders stop and retry controls while graph is running or failed", () => {
    const graph = createDocumentGraph();
    graph.nodes[1].status = "failed";

    const markup = renderToStaticMarkup(
      <NodeCanvas
        graph={graph}
        running={true}
        canRetryFailed={true}
        onRun={() => undefined}
        onStop={() => undefined}
        onRetryFailed={() => undefined}
      />,
    );

    expect(markup).toContain("nodeCanvasSecondaryButton");
  });

  it("renders run controls for an executable research graph", () => {
    const markup = renderToStaticMarkup(
      <NodeCanvas
        graph={researchGraph}
        running={false}
        onRun={() => undefined}
      />,
    );

    expect(markup).toContain("nodeCanvasRunButton");
    expect(markup).not.toContain("Research graph execution is not available yet.");
  });

  it("renders planning and temporary script labels with compact estimate chips", () => {
    const graph: NodeGraph = {
      graphId: "script-plan",
      nodes: [
        {
          nodeId: "plan",
          nodeType: "planning",
          displayName: "Decide execution path",
          status: "completed",
          inputPorts: [],
          outputPorts: [],
          dependencies: [],
          summary: "Use local files, then run a generated script.",
          createdBy: "agent",
          artifactRefs: [],
          retryCount: 0,
          estimate: {
            durationMs: 5000,
            cpu: "low",
            memory: "256MB",
          },
          position: { x: 0, y: 0 },
        },
        {
          nodeId: "temp-script",
          nodeType: "temporary_script",
          displayName: "Inspect CSV",
          status: "needs_permission",
          inputPorts: [],
          outputPorts: [],
          dependencies: ["plan"],
          summary: "Run a generated script over project data.",
          createdBy: "agent",
          artifactRefs: [],
          retryCount: 0,
          estimate: {
            durationMs: 12000,
            memory: "512MB",
            network: "none",
          },
          scriptReview: {
            status: "reviewing",
            summary: "Requires approval before execution.",
            permissions: ["read_project_files"],
            riskLevel: "high",
            requiresApproval: true,
          },
          position: { x: 240, y: 0 },
        },
      ],
      edges: [],
    };

    const markup = renderToStaticMarkup(
      <NodeCanvas graph={graph} onRun={() => undefined} />,
    );

    expect(markup).toContain("规划");
    expect(markup).toContain("临时代码");
    expect(markup).toContain("agentNode-planningQuiet");
    expect(markup).toContain("agentNode-needsPermission");
    expect(markup).toContain("agentNodeEstimateChips");
    expect(markup).toContain("5s");
    expect(markup).toContain("256MB");
  });

  it("renders task planner graphs with planning and executable nodes", () => {
    const graph: NodeGraph = {
      graphId: "task-planner-graph",
      nodes: [
        {
          nodeId: "task-analysis",
          nodeType: "planning",
          displayName: "Task Analysis",
          status: "completed",
          inputPorts: [],
          outputPorts: [],
          dependencies: [],
          summary: "Understand the user task.",
          createdBy: "agent",
          artifactRefs: [],
          retryCount: 0,
          estimate: { durationMs: 100, cpu: "low", memory: "low" },
          position: { x: 0, y: 0 },
        },
        {
          nodeId: "temporary-script-file-inspect",
          nodeType: "temporary_script",
          displayName: "Inspect CSV with temporary script",
          status: "needs_permission",
          inputPorts: [],
          outputPorts: [],
          dependencies: ["task-analysis"],
          summary: "Run generated code only after approval.",
          createdBy: "agent",
          artifactRefs: [],
          retryCount: 0,
          estimate: { durationMs: 1500, memory: "256MB", network: "none" },
          scriptReview: {
            status: "reviewing",
            summary: "High-risk script needs approval.",
            permissions: ["read_project_files"],
            riskLevel: "high",
            requiresApproval: true,
          },
          position: { x: 240, y: 0 },
        },
        {
          nodeId: "task-output",
          nodeType: "output",
          displayName: "Task Output",
          status: "waiting",
          inputPorts: [],
          outputPorts: [],
          dependencies: ["temporary-script-file-inspect"],
          summary: "Return the result.",
          createdBy: "agent",
          artifactRefs: [],
          retryCount: 0,
          position: { x: 480, y: 0 },
        },
      ],
      edges: [
        {
          id: "task-analysis-temporary-script-file-inspect",
          source: "task-analysis",
          target: "temporary-script-file-inspect",
        },
        {
          id: "temporary-script-file-inspect-task-output",
          source: "temporary-script-file-inspect",
          target: "task-output",
        },
      ],
    };

    const markup = renderToStaticMarkup(
      <NodeCanvas graph={graph} running={false} onRun={() => undefined} />,
    );

    expect(markup).toContain("nodeCanvasRunButton");
    expect(markup).toContain("agentNode-planningQuiet");
    expect(markup).toContain("agentNode-needsPermission");
    expect(markup).toContain("agentNode-riskHigh");
    expect(markup).toContain("Inspect CSV with temporary script");
    expect(markup).toContain("Task Output");
  });
});
