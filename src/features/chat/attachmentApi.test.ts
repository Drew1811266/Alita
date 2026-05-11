import { describe, expect, it } from "vitest";

import {
  createBrowserAttachmentFromPath,
  normalizeSelectedAttachmentPaths,
} from "./attachmentApi";

describe("attachmentApi", () => {
  it("normalizes cancelled, single, and multiple file selections", () => {
    expect(normalizeSelectedAttachmentPaths(null)).toEqual([]);
    expect(normalizeSelectedAttachmentPaths("D:\\Docs\\input.docx")).toEqual([
      "D:\\Docs\\input.docx",
    ]);
    expect(
      normalizeSelectedAttachmentPaths([
        "D:\\Docs\\input.docx",
        "D:\\Images\\cover.png",
      ]),
    ).toEqual(["D:\\Docs\\input.docx", "D:\\Images\\cover.png"]);
  });

  it("creates browser fallback attachment metadata from a file path", () => {
    const attachment = createBrowserAttachmentFromPath("D:\\Docs\\input.docx");

    expect(attachment.name).toBe("input.docx");
    expect(attachment.path).toBe("D:\\Docs\\input.docx");
    expect(attachment.sizeBytes).toBe(0);
    expect(attachment.mimeType).toBe("application/octet-stream");
    expect(attachment.attachmentId).toMatch(/^attachment-/);
  });
});
