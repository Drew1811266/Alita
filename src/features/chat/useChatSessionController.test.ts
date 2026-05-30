import { describe, expect, it } from "vitest";

import {
  appendPendingAttachments,
  collectProjectAttachments,
  createChatSessionState,
  selectAgentAttachments,
} from "./useChatSessionController";
import type { ChatAttachment, ProjectAttachmentRef } from "../../shared/types";

const attachment: ChatAttachment = {
  attachmentId: "a1",
  name: "brief.docx",
  path: "D:\\Project\\brief.docx",
  sizeBytes: 12,
  mimeType:
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
};

describe("chat session controller helpers", () => {
  it("starts with empty draft and no pending attachments", () => {
    expect(createChatSessionState()).toEqual({
      draft: "",
      pendingAttachments: [],
      contextAttachments: [],
    });
  });

  it("deduplicates pending attachments by path", () => {
    expect(appendPendingAttachments([attachment], [attachment])).toEqual([
      attachment,
    ]);
  });

  it("reuses context attachments only when the message references them", () => {
    expect(
      selectAgentAttachments({
        content: "Research current GitHub projects.",
        sentAttachments: [],
        contextAttachments: [attachment],
      }),
    ).toEqual([]);

    expect(
      selectAgentAttachments({
        content: "Please summarize the attached document.",
        sentAttachments: [],
        contextAttachments: [attachment],
      }),
    ).toEqual([attachment]);
  });

  it("merges project, context, and message attachments by path", () => {
    const existing: ProjectAttachmentRef = {
      ...attachment,
      originalPath: attachment.path,
      fileExists: true,
    };

    expect(
      collectProjectAttachments([existing], [attachment], [
        {
          messageId: "m1",
          role: "user",
          content: "hello",
          attachments: [attachment],
          createdAt: "2026-05-30T00:00:00.000Z",
        },
      ]),
    ).toEqual([existing]);
  });
});
