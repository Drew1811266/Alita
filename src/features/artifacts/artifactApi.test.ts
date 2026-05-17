import { convertFileSrc, invoke } from "@tauri-apps/api/core";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  artifactFileUrl,
  openArtifact,
  readArtifactText,
  revealArtifact,
} from "./artifactApi";

vi.mock("@tauri-apps/api/core", () => ({
  convertFileSrc: vi.fn(),
  invoke: vi.fn(),
}));

const invokeMock = vi.mocked(invoke);
const convertFileSrcMock = vi.mocked(convertFileSrc);

describe("artifactApi", () => {
  beforeEach(() => {
    invokeMock.mockResolvedValue(undefined);
    convertFileSrcMock.mockReturnValue("asset://localhost/report.pdf");
  });

  it("opens an artifact through the Tauri command", async () => {
    await openArtifact("D:\\Project\\artifacts\\report.md");

    expect(invokeMock).toHaveBeenCalledWith("open_artifact", {
      path: "D:\\Project\\artifacts\\report.md",
    });
  });

  it("reveals an artifact through the Tauri command", async () => {
    await revealArtifact("D:\\Project\\artifacts\\report.md");

    expect(invokeMock).toHaveBeenCalledWith("reveal_artifact", {
      path: "D:\\Project\\artifacts\\report.md",
    });
  });

  it("reads artifact text through the Tauri command", async () => {
    invokeMock.mockResolvedValueOnce({
      path: "D:\\Project\\artifacts\\report.md",
      fileName: "report.md",
      sizeBytes: 12,
      content: "Report body",
      truncated: false,
    });

    const preview = await readArtifactText("D:\\Project\\artifacts\\report.md");

    expect(preview).toEqual({
      path: "D:\\Project\\artifacts\\report.md",
      fileName: "report.md",
      sizeBytes: 12,
      content: "Report body",
      truncated: false,
    });
    expect(invokeMock).toHaveBeenCalledWith("read_artifact_text", {
      path: "D:\\Project\\artifacts\\report.md",
    });
  });

  it("converts local artifact paths to Tauri asset URLs", () => {
    expect(artifactFileUrl("D:\\Project\\artifacts\\report.pdf")).toBe(
      "asset://localhost/report.pdf",
    );
    expect(convertFileSrcMock).toHaveBeenCalledWith(
      "D:\\Project\\artifacts\\report.pdf",
    );
  });
});
