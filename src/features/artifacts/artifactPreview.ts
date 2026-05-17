import type { AgentNode, ArtifactRef } from "../../shared/types";

export type PreviewArtifactSelection = {
  artifactId: string;
  path: string;
  fileName: string;
  sourceNodeId: string;
};

export function resolvePreviewArtifactForNode(
  node: AgentNode | null,
  artifacts: ArtifactRef[],
): PreviewArtifactSelection | null {
  if (!node || node.nodeType !== "output") {
    return null;
  }

  for (const artifactRef of [...node.artifactRefs].reverse()) {
    const artifact = artifacts.find(
      (candidate) =>
        candidate.path === artifactRef || candidate.artifactId === artifactRef,
    );
    if (artifact) {
      return selectionFromArtifact(artifact);
    }

    return {
      artifactId: artifactRef,
      path: artifactRef,
      fileName: fileNameFromPath(artifactRef),
      sourceNodeId: node.nodeId,
    };
  }

  const latestNodeArtifact = [...artifacts]
    .reverse()
    .find((artifact) => artifact.sourceNodeId === node.nodeId);
  return latestNodeArtifact ? selectionFromArtifact(latestNodeArtifact) : null;
}

function selectionFromArtifact(
  artifact: ArtifactRef,
): PreviewArtifactSelection {
  return {
    artifactId: artifact.artifactId,
    path: artifact.path,
    fileName: fileNameFromPath(artifact.path),
    sourceNodeId: artifact.sourceNodeId,
  };
}

function fileNameFromPath(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}
