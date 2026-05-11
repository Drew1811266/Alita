import { invoke } from "@tauri-apps/api/core";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { openArtifact, revealArtifact } from "./artifactApi";

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(),
}));

const invokeMock = vi.mocked(invoke);

describe("artifactApi", () => {
  beforeEach(() => {
    invokeMock.mockResolvedValue(undefined);
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
});
