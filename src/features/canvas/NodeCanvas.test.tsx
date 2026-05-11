import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { NodeCanvas } from "./NodeCanvas";
import { createDocumentGraph } from "./nodeLayout";

describe("NodeCanvas", () => {
  it("renders a run button when graph exists", () => {
    const markup = renderToStaticMarkup(
      <NodeCanvas
        graph={createDocumentGraph()}
        running={false}
        onRun={() => undefined}
      />,
    );

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
});
