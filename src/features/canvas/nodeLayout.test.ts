import { describe, expect, it } from "vitest";

import { SUPPORTED_NODE_TYPES } from "../../shared/types";
import type { NodeGraph, NodeType } from "../../shared/types";
import { createDocumentGraph } from "./nodeLayout";

const validPlanningNodeType: NodeType = "planning";
// @ts-expect-error NodeType must remain a closed union of supported graph node types.
const invalidNodeType: NodeType = "not_a_real_node_type";

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

    expect(graph.nodes).toHaveLength(6);
    expect(graph.nodes.map((node) => node.nodeId)).toEqual([
      "document-input",
      "document-parse",
      "content-organize",
      "report-generate",
      "typst-export",
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
    const typst = nodeById(graph, "typst-export");
    const exportNode = nodeById(graph, "file-export");

    expect(input.position.y).toBeLessThan(parse.position.y);
    expect(parse.position.y).toBeLessThan(organize.position.y);
    expect(parse.position.y).toBeLessThan(report.position.y);
    expect(organize.position.y).toBeLessThan(typst.position.y);
    expect(report.position.y).toBeLessThan(typst.position.y);
    expect(typst.position.y).toBeLessThan(exportNode.position.y);
  });

  it("branches after parsing and merges before export", () => {
    const graph = createDocumentGraph();

    expect(graph.edges).toHaveLength(6);
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
          id: "content-organize-typst-export",
          source: "content-organize",
          target: "typst-export",
        },
        {
          id: "report-generate-typst-export",
          source: "report-generate",
          target: "typst-export",
        },
        {
          id: "typst-export-file-export",
          source: "typst-export",
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

  it("accepts planning and temporary script nodes in canvas graph data", () => {
    expect(validPlanningNodeType).toBe("planning");
    expect(invalidNodeType).toBe("not_a_real_node_type");

    const graph: NodeGraph = {
      graphId: "routing-plan",
      nodes: [
        {
          nodeId: "plan-task",
          nodeType: "planning",
          displayName: "Plan task",
          status: "completed",
          inputPorts: [],
          outputPorts: [{ id: "decision", label: "Decision", dataType: "json" }],
          dependencies: [],
          summary: "Decides the execution shape.",
          createdBy: "agent",
          artifactRefs: [],
          retryCount: 0,
          estimate: {
            durationMs: 250,
            cpu: "low",
            memory: "low",
            network: "none",
          },
          resourceUsage: {
            cpu: "low",
            memory: "low",
            network: "none",
          },
          position: { x: 0, y: 0 },
        },
        {
          nodeId: "script-gap-fill",
          nodeType: "temporary_script",
          displayName: "Temporary script",
          status: "needs_permission",
          inputPorts: [{ id: "decision", label: "Decision", dataType: "json" }],
          outputPorts: [{ id: "result", label: "Result", dataType: "json" }],
          dependencies: ["plan-task"],
          summary: "Reviews a temporary script before execution.",
          createdBy: "agent",
          artifactRefs: [],
          retryCount: 0,
          scriptReview: {
            status: "not_reviewed",
            summary: "Needs approval before running.",
            permissions: ["read_workspace"],
            riskLevel: "high",
            requiresApproval: true,
            codePreview: "print('preview')",
            inputContract: { path: "string" },
            outputContract: { result: "string" },
          },
          runtimeNotice: {
            kind: "estimate_exceeded",
            message: "Node exceeded its estimate.",
            actualDurationMs: 1500,
          },
          position: { x: 120, y: 120 },
        },
      ],
      edges: [
        {
          id: "plan-task-script-gap-fill",
          source: "plan-task",
          target: "script-gap-fill",
        },
      ],
    };

    expect(SUPPORTED_NODE_TYPES).toEqual(
      expect.arrayContaining(["planning", "temporary_script"]),
    );
    expect(graph.nodes.map((node) => node.nodeType)).toEqual([
      "planning",
      "temporary_script",
    ]);
    expect(graph.nodes[1].scriptReview?.requiresApproval).toBe(true);
    expect(graph.nodes[1].runtimeNotice?.actualDurationMs).toBe(1500);
  });
});
