import { describe, expect, it } from "vitest";

import { resolvePreviewArtifactForNode } from "./artifactPreview";
import type { AgentNode, ArtifactRef } from "../../shared/types";

const outputNode: AgentNode = {
  nodeId: "file-export",
  nodeType: "output",
  displayName: "导出文件",
  status: "completed",
  inputPorts: [],
  outputPorts: [],
  dependencies: [],
  summary: "导出最终文件",
  createdBy: "agent",
  artifactRefs: ["D:\\Project\\artifacts\\report.md"],
  retryCount: 0,
  position: { x: 0, y: 0 },
};

const artifacts: ArtifactRef[] = [
  {
    artifactId: "report",
    path: "D:\\Project\\artifacts\\report.md",
    sourceNodeId: "file-export",
    createdAt: "2026-05-12T00:00:00.000Z",
  },
];

describe("resolvePreviewArtifactForNode", () => {
  it("returns the exported artifact path for an output node", () => {
    expect(resolvePreviewArtifactForNode(outputNode, artifacts)).toEqual({
      artifactId: "report",
      fileName: "report.md",
      path: "D:\\Project\\artifacts\\report.md",
      sourceNodeId: "file-export",
    });
  });

  it("falls back to the node artifact ref when the artifact list has not caught up", () => {
    expect(resolvePreviewArtifactForNode(outputNode, [])).toEqual({
      artifactId: "D:\\Project\\artifacts\\report.md",
      fileName: "report.md",
      path: "D:\\Project\\artifacts\\report.md",
      sourceNodeId: "file-export",
    });
  });

  it("does not preview non-output nodes", () => {
    expect(
      resolvePreviewArtifactForNode(
        { ...outputNode, nodeId: "report-generate", nodeType: "model" },
        artifacts,
      ),
    ).toBeNull();
  });
});
