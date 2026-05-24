import { invoke } from "@tauri-apps/api/core";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  deleteApiProviderConfig,
  prepareAgentModelSession,
  saveApiProviderConfig,
  setActiveApiProvider,
  setAgentModelMode,
  type SaveApiProviderPayload,
} from "./preferencesApi";
import type { PreferencesView } from "../../shared/types";

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(),
}));

vi.mock("@tauri-apps/plugin-dialog", () => ({
  open: vi.fn(),
}));

const invokeMock = vi.mocked(invoke);

const preferencesView: PreferencesView = {
  preferences: {
    schemaVersion: 3,
    recentProjects: [],
    modelDirectories: [],
    modelStorageDir: "",
    models: [],
    defaultModelId: null,
    modelAssignments: {
      agentChatModelId: null,
      speechToTextModelId: null,
    },
    agentModelMode: "local",
    activeApiProviderId: null,
    apiProviderConfigs: [],
    toolEnablement: {},
  },
  tools: [],
};

afterEach(() => {
  delete (globalThis as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
  delete (globalThis as unknown as Record<string, unknown>).window;
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("preferences API provider commands", () => {
  it("sets the agent model mode", async () => {
    invokeMock.mockResolvedValue(preferencesView);

    await expect(setAgentModelMode("api")).resolves.toBe(preferencesView);

    expect(invokeMock).toHaveBeenCalledWith("set_agent_model_mode_command", {
      payload: { mode: "api" },
    });
  });

  it("saves API provider config payloads", async () => {
    const payload: SaveApiProviderPayload = {
      providerId: "provider-1",
      providerType: "openai",
      displayName: "OpenAI",
      baseUrl: "https://api.openai.com/v1",
      model: "gpt-4.1",
      enabled: true,
      apiKey: "secret",
    };
    invokeMock.mockResolvedValue(preferencesView);

    await expect(saveApiProviderConfig(payload)).resolves.toBe(preferencesView);

    expect(invokeMock).toHaveBeenCalledWith("save_api_provider_config", {
      payload,
    });
  });

  it("deletes API provider configs", async () => {
    invokeMock.mockResolvedValue(preferencesView);

    await expect(deleteApiProviderConfig("provider-1")).resolves.toBe(
      preferencesView,
    );

    expect(invokeMock).toHaveBeenCalledWith(
      "delete_api_provider_config_command",
      {
        payload: { providerId: "provider-1" },
      },
    );
  });

  it("sets the active API provider", async () => {
    invokeMock.mockResolvedValue(preferencesView);

    await expect(setActiveApiProvider("provider-1")).resolves.toBe(
      preferencesView,
    );

    expect(invokeMock).toHaveBeenCalledWith(
      "set_active_api_provider_command",
      {
        payload: { providerId: "provider-1" },
      },
    );
  });
});

describe("prepareAgentModelSession", () => {
  it("returns null without invoking outside Tauri", async () => {
    await expect(prepareAgentModelSession()).resolves.toBeNull();

    expect(invokeMock).not.toHaveBeenCalled();
  });

  it("returns the prepared model session id inside Tauri", async () => {
    Object.defineProperty(globalThis, "window", {
      value: globalThis,
      configurable: true,
    });
    Object.defineProperty(globalThis, "__TAURI_INTERNALS__", {
      value: {},
      configurable: true,
    });
    invokeMock.mockResolvedValue({ modelSessionId: "session-1" });

    await expect(prepareAgentModelSession()).resolves.toBe("session-1");

    expect(invokeMock).toHaveBeenCalledWith("prepare_agent_model_session");
  });
});
