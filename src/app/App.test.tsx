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
  tryBeginGraphRunForTest,
} from "./App";

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
});
