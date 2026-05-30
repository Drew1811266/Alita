import { describe, expect, it } from "vitest";
import type { AgentNode, ArtifactRef } from "../../shared/types";
import {
  createArtifactPreviewState,
  resolveArtifactPreviewRequest,
} from "./useArtifactPreviewController";

describe("artifact preview controller helpers", () => {
  it("resolves an artifact preview request from a selected node", () => {
    const artifact: ArtifactRef = {
      artifactId: "a1",
      path: "D:\\Project\\artifacts\\report.md",
      sourceNodeId: "node-1",
      createdAt: "2026-05-29T00:00:00Z",
    };
    const node = {
      nodeId: "node-1",
      nodeType: "output",
      artifactRefs: [],
    } as unknown as AgentNode;

    const request = resolveArtifactPreviewRequest(node, [artifact]);

    expect(createArtifactPreviewState().artifactPreview).toBeNull();
    expect(request?.artifact.artifactId).toBe("a1");
  });
});
