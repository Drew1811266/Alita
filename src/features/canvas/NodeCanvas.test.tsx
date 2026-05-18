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
    expect(markup).toContain("运行流程");
  });

  it("renders the running state while a graph run is active", () => {
    const markup = renderToStaticMarkup(
      <NodeCanvas
        graph={createDocumentGraph()}
        running={true}
        onRun={() => undefined}
      />,
    );

    expect(markup).toContain("运行中");
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

    expect(markup).toContain("停止运行");
    expect(markup).toContain("重试失败节点");
  });

  it("renders a non-runnable notice instead of run controls for a research graph", () => {
    const markup = renderToStaticMarkup(
      <NodeCanvas
        graph={researchGraph}
        running={false}
        onRun={() => undefined}
      />,
    );

    expect(markup).toContain("Research graph execution is not available yet.");
    expect(markup).not.toContain("nodeCanvasRunButton");
    expect(markup).not.toContain("运行流程");
  });
});
