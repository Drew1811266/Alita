import { invoke } from "@tauri-apps/api/core";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  deleteApiProviderConfig,
  deleteMcpToolProviderConfig,
  fetchApiProviderModels,
  prepareAgentModelSession,
  refreshMcpToolProviderTools,
  saveApiProviderConfig,
  saveMcpToolProviderConfig,
  setActiveApiProvider,
  setAgentModelMode,
  testApiProviderConnection,
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
    toolProviderConfigs: [
      {
        providerId: "internal",
        source: "internal",
        displayName: "Internal Tools",
        args: [],
        enabled: true,
        createdAt: "system",
        updatedAt: "system",
      },
    ],
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

  it("tests API provider connections with the expected command", async () => {
    const payload: SaveApiProviderPayload = {
      providerId: "provider-1",
      providerType: "openai",
      displayName: "OpenAI",
      baseUrl: "https://api.openai.com/v1",
      model: "gpt-4.1",
      enabled: true,
      apiKey: "secret",
    };
    const result = {
      ok: true,
      message: "Connection successful",
      models: ["gpt-4.1"],
    };
    invokeMock.mockResolvedValue(result);

    await expect(testApiProviderConnection(payload)).resolves.toBe(result);

    expect(invokeMock).toHaveBeenCalledWith("test_api_provider_connection", {
      payload,
    });
  });

  it("fetches API provider models with the expected command", async () => {
    const payload: SaveApiProviderPayload = {
      providerType: "deepseek",
      displayName: "DeepSeek",
      baseUrl: "https://api.deepseek.com",
      model: "",
      enabled: true,
      apiKey: "secret",
    };
    const result = {
      ok: true,
      message: "Fetched 2 models",
      models: ["deepseek-chat", "deepseek-reasoner"],
    };
    invokeMock.mockResolvedValue(result);

    await expect(fetchApiProviderModels(payload)).resolves.toBe(result);

    expect(invokeMock).toHaveBeenCalledWith("fetch_api_provider_models", {
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

  it("saves MCP tool provider configs", async () => {
    const payload = {
      displayName: "Docs MCP",
      transport: "stdio" as const,
      command: "npx",
      args: ["@example/docs-mcp"],
      enabled: true,
    };
    invokeMock.mockResolvedValue(preferencesView);

    await expect(saveMcpToolProviderConfig(payload)).resolves.toBe(
      preferencesView,
    );

    expect(invokeMock).toHaveBeenCalledWith("save_mcp_tool_provider_config", {
      payload,
    });
  });

  it("deletes MCP tool provider configs", async () => {
    invokeMock.mockResolvedValue(preferencesView);

    await expect(deleteMcpToolProviderConfig("mcp-1")).resolves.toBe(
      preferencesView,
    );

    expect(invokeMock).toHaveBeenCalledWith(
      "delete_mcp_tool_provider_config_command",
      {
        payload: { providerId: "mcp-1" },
      },
    );
  });

  it("refreshes MCP tool provider tools", async () => {
    const tools = [{ toolId: "mcp:mcp-1:search", providerId: "mcp-1" }];
    invokeMock.mockResolvedValue(tools);

    await expect(refreshMcpToolProviderTools("mcp-1")).resolves.toBe(tools);

    expect(invokeMock).toHaveBeenCalledWith("refresh_mcp_tool_provider_tools", {
      payload: { providerId: "mcp-1" },
    });
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
