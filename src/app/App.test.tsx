import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  prepareAgentModelSession,
  type PreferencesView,
} from "../features/preferences/preferencesApi";
import {
  App,
  createAgentSession,
  endGraphRunForTest,
  shouldRefreshAsrForPreferencesUpdate,
  submitUserMessageWithStreamFallbackForTest,
  tryBeginGraphRunForTest,
} from "./App";
import type { BackendEvent } from "../shared/events";
import type { SubmitMessagePayload } from "../features/task/useTaskEvents";

vi.mock("../features/preferences/preferencesApi", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../features/preferences/preferencesApi")>();
  return {
    ...actual,
    prepareAgentModelSession: vi.fn(),
  };
});

const prepareAgentModelSessionMock = vi.mocked(prepareAgentModelSession);

beforeEach(() => {
  prepareAgentModelSessionMock.mockReset();
});

function preferencesViewWithSpeechModel(
  speechToTextModelId: string | null,
): PreferencesView {
  return {
    preferences: {
      schemaVersion: 3,
      recentProjects: [],
      modelDirectories: [],
      modelStorageDir: "D:\\Models",
      models: [],
      defaultModelId: null,
      modelAssignments: {
        agentChatModelId: null,
        speechToTextModelId,
      },
      agentModelMode: "local",
      activeApiProviderId: null,
      apiProviderConfigs: [],
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

  it("creates agent model sessions through preferences", async () => {
    prepareAgentModelSessionMock.mockResolvedValue("model-session-1");

    await expect(createAgentSession()).resolves.toBe("model-session-1");

    expect(prepareAgentModelSessionMock).toHaveBeenCalledOnce();
  });

  it("wraps unavailable agent model configuration errors", async () => {
    prepareAgentModelSessionMock.mockRejectedValue(new Error("missing config"));

    await expect(createAgentSession()).rejects.toThrow(
      "Agent 模型配置不可用：missing config",
    );
  });

  it("locks graph runs synchronously until cleanup", () => {
    const inFlightRef = { current: false };

    expect(tryBeginGraphRunForTest(inFlightRef)).toBe(true);
    expect(inFlightRef.current).toBe(true);
    expect(tryBeginGraphRunForTest(inFlightRef)).toBe(false);

    endGraphRunForTest(inFlightRef);

    expect(inFlightRef.current).toBe(false);
    expect(tryBeginGraphRunForTest(inFlightRef)).toBe(true);
  });

  it("does not fall back when stream session preparation fails", async () => {
    const payload: SubmitMessagePayload = {
      taskId: "task-1",
      content: "Run this",
      attachments: [],
    };
    const sessionError = new Error("missing config");
    const createSession = vi.fn().mockRejectedValue(sessionError);
    const submitStream = vi.fn();
    const submitFallback = vi.fn();

    await expect(
      submitUserMessageWithStreamFallbackForTest({
        payload,
        createSession,
        submitStream,
        submitFallback,
        onEvent: vi.fn(),
      }),
    ).rejects.toBe(sessionError);

    expect(createSession).toHaveBeenCalledOnce();
    expect(submitStream).not.toHaveBeenCalled();
    expect(submitFallback).not.toHaveBeenCalled();
  });

  it("uses a fresh fallback session after stream submission fails before events", async () => {
    const payload: SubmitMessagePayload = {
      taskId: "task-1",
      content: "Run this",
      attachments: [],
    };
    const fallbackEvent: BackendEvent = {
      type: "task.completed",
      payload: { taskId: "task-1" },
    };
    const createSession = vi
      .fn()
      .mockResolvedValueOnce("stream-session")
      .mockResolvedValueOnce("fallback-session");
    const submitStream = vi.fn().mockRejectedValue(new Error("stream failed"));
    const submitFallback = vi.fn().mockResolvedValue([fallbackEvent]);
    const onEvent = vi.fn();

    await submitUserMessageWithStreamFallbackForTest({
      payload,
      createSession,
      submitStream,
      submitFallback,
      onEvent,
    });

    expect(createSession).toHaveBeenCalledTimes(2);
    expect(submitStream).toHaveBeenCalledWith(
      { ...payload, modelSessionId: "stream-session" },
      expect.any(Function),
    );
    expect(submitFallback).toHaveBeenCalledWith({
      ...payload,
      modelSessionId: "fallback-session",
    });
    expect(onEvent).toHaveBeenCalledWith(fallbackEvent);
  });

  it("does not fall back after receiving a partial stream event", async () => {
    const payload: SubmitMessagePayload = {
      taskId: "task-1",
      content: "Run this",
      attachments: [],
    };
    const streamEvent: BackendEvent = {
      type: "message.delta",
      payload: { messageId: "assistant-1", delta: "partial" },
    };
    const streamError = new Error("stream interrupted");
    const createSession = vi.fn().mockResolvedValue("stream-session");
    const submitStream = vi.fn(
      async (
        _payload: SubmitMessagePayload,
        onStreamEvent: (event: BackendEvent) => void,
      ) => {
        onStreamEvent(streamEvent);
        throw streamError;
      },
    );
    const submitFallback = vi.fn();
    const onEvent = vi.fn();

    await expect(
      submitUserMessageWithStreamFallbackForTest({
        payload,
        createSession,
        submitStream,
        submitFallback,
        onEvent,
      }),
    ).rejects.toBe(streamError);

    expect(createSession).toHaveBeenCalledOnce();
    expect(onEvent).toHaveBeenCalledWith(streamEvent);
    expect(submitFallback).not.toHaveBeenCalled();
  });
});
