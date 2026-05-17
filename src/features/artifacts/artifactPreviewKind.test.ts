import { describe, expect, it } from "vitest";

import { detectArtifactPreviewKind } from "./artifactPreviewKind";

describe("detectArtifactPreviewKind", () => {
  it.each([
    ["D:\\Project\\artifacts\\report.md", "markdown"],
    ["D:\\Project\\artifacts\\README.markdown", "markdown"],
    ["D:\\Project\\artifacts\\notes.txt", "text"],
    ["D:\\Project\\artifacts\\data.json", "text"],
    ["D:\\Project\\artifacts\\table.csv", "text"],
    ["D:\\Project\\artifacts\\run.log", "text"],
    ["D:\\Project\\artifacts\\paper.pdf", "pdf"],
    ["D:\\Project\\artifacts\\image.png", "unsupported"],
  ] as const)("detects %s as %s", (path, expectedKind) => {
    expect(detectArtifactPreviewKind(path)).toBe(expectedKind);
  });
});
