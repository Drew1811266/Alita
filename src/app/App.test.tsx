import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  App,
  buildResearchChoiceSubmitPayload,
  shouldRefreshAsrForPreferencesUpdate,
} from "./App";
import type { ChatAttachment, ChatMessage } from "../shared/types";
import type { PreferencesView } from "../features/preferences/preferencesApi";

function preferencesViewWithSpeechModel(
  speechToTextModelId: string | null,
): PreferencesView {
  return {
    preferences: {
      schemaVersion: 2,
      recentProjects: [],
      modelDirectories: [],
      modelStorageDir: "D:\\Models",
      models: [],
      defaultModelId: null,
      modelAssignments: {
        agentChatModelId: null,
        speechToTextModelId,
      },
      toolEnablement: {},
    },
    tools: [],
  };
}

describe("App", () => {
  it("starts on the project home before a project is active", () => {
    const markup = renderToStaticMarkup(<App />);

    expect(markup).toContain("新建工程");
    expect(markup).toContain("打开工程");
    expect(markup).toContain("最近工程");
    expect(markup).not.toContain("消息内容");
  });
  it("refreshes ASR status when the speech-to-text assignment changes", () => {
    const withoutSpeechModel = preferencesViewWithSpeechModel(null);
    const withSpeechModel = preferencesViewWithSpeechModel("asr-1");

    expect(
      shouldRefreshAsrForPreferencesUpdate(null, withSpeechModel),
    ).toBe(true);
    expect(
      shouldRefreshAsrForPreferencesUpdate(
        withoutSpeechModel,
        withSpeechModel,
      ),
    ).toBe(true);
    expect(
      shouldRefreshAsrForPreferencesUpdate(withSpeechModel, withSpeechModel),
    ).toBe(false);
  });

  it("builds research choice submit payload from the latest user message", () => {
    const contextAttachment: ChatAttachment = {
      attachmentId: "context-1",
      name: "context.md",
      path: "D:\\Project\\context.md",
      sizeBytes: 10,
      mimeType: "text/markdown",
    };
    const messages: ChatMessage[] = [
      {
        messageId: "assistant-1",
        role: "assistant",
        content: "Choose how to proceed.",
        attachments: [],
        createdAt: "2026-05-09T00:00:00.000Z",
      },
      {
        messageId: "user-1",
        role: "user",
        content: "Research current packaging tools",
        attachments: [],
        createdAt: "2026-05-09T00:00:01.000Z",
      },
    ];

    expect(
      buildResearchChoiceSubmitPayload({
        taskId: "task-1",
        messages,
        contextAttachments: [contextAttachment],
        choiceId: "research_flow",
      }),
    ).toEqual({
      taskId: "task-1",
      content: "Research current packaging tools",
      attachments: [contextAttachment],
      inquiryChoice: "research_flow",
    });
  });
});
