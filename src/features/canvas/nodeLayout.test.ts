import { describe, expect, it } from "vitest";

import { createDocumentGraph } from "./nodeLayout";

function nodeById(graph: ReturnType<typeof createDocumentGraph>, nodeId: string) {
  const node = graph.nodes.find((candidate) => candidate.nodeId === nodeId);
  if (!node) {
    throw new Error(`Missing node ${nodeId}`);
  }
  return node;
}

describe("createDocumentGraph", () => {
  it("creates a document graph with the required nodes and node types", () => {
    const graph = createDocumentGraph();

    expect(graph.nodes).toHaveLength(5);
    expect(graph.nodes.map((node) => node.nodeId)).toEqual([
      "document-input",
      "document-parse",
      "content-organize",
      "report-generate",
      "file-export",
    ]);
    expect(new Set(graph.nodes.map((node) => node.nodeType))).toEqual(
      new Set(["fixed_tool", "model", "output"]),
    );
  });

  it("positions nodes in a top-down document workflow", () => {
    const graph = createDocumentGraph();
    const input = nodeById(graph, "document-input");
    const parse = nodeById(graph, "document-parse");
    const organize = nodeById(graph, "content-organize");
    const report = nodeById(graph, "report-generate");
    const exportNode = nodeById(graph, "file-export");

    expect(input.position.y).toBeLessThan(parse.position.y);
    expect(parse.position.y).toBeLessThan(organize.position.y);
    expect(parse.position.y).toBeLessThan(report.position.y);
    expect(organize.position.y).toBeLessThan(exportNode.position.y);
    expect(report.position.y).toBeLessThan(exportNode.position.y);
  });

  it("branches after parsing and merges before export", () => {
    const graph = createDocumentGraph();

    expect(graph.edges).toHaveLength(5);
    expect(graph.edges).toEqual(
      expect.arrayContaining([
        {
          id: "document-input-document-parse",
          source: "document-input",
          target: "document-parse",
        },
        {
          id: "document-parse-content-organize",
          source: "document-parse",
          target: "content-organize",
        },
        {
          id: "document-parse-report-generate",
          source: "document-parse",
          target: "report-generate",
        },
        {
          id: "content-organize-file-export",
          source: "content-organize",
          target: "file-export",
        },
        {
          id: "report-generate-file-export",
          source: "report-generate",
          target: "file-export",
        },
      ]),
    );
  });

  it("connects every edge to existing nodes and mirrors dependencies", () => {
    const graph = createDocumentGraph();
    const nodeIds = new Set(graph.nodes.map((node) => node.nodeId));

    for (const edge of graph.edges) {
      expect(nodeIds.has(edge.source)).toBe(true);
      expect(nodeIds.has(edge.target)).toBe(true);
    }

    for (const node of graph.nodes) {
      for (const dependency of node.dependencies) {
        expect(graph.edges).toContainEqual(
          expect.objectContaining({
            source: dependency,
            target: node.nodeId,
          }),
        );
      }
    }
  });

  it("fills summaries, ports, and references for every node", () => {
    const graph = createDocumentGraph();

    for (const node of graph.nodes) {
      expect(node.summary).toMatch(/[\u4e00-\u9fff]/);
      expect(node.inputPorts.length + node.outputPorts.length).toBeGreaterThan(0);

      for (const port of [...node.inputPorts, ...node.outputPorts]) {
        expect(port.label).toMatch(/[\u4e00-\u9fff]/);
      }

      if (node.nodeType === "fixed_tool") {
        expect(node.toolRef).toBeTruthy();
      }

      if (node.nodeType === "model") {
        expect(node.modelRef).toBeTruthy();
      }
    }
  });
});
