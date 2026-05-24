import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";

import type {
  AgentModelMode,
  ApiProviderType,
  PreferencesView,
} from "../../shared/types";

export type { PreferencesView } from "../../shared/types";

export type ModelAssignmentRole = "agentChat" | "speechToText";

export type SaveApiProviderPayload = {
  providerId?: string;
  providerType: ApiProviderType;
  displayName: string;
  baseUrl: string;
  model: string;
  enabled: boolean;
  apiKey?: string;
};

export type ApiProviderConnectionResult = {
  ok: boolean;
  message: string;
  models: string[];
};

export async function getPreferences(): Promise<PreferencesView> {
  return invoke<PreferencesView>("get_preferences");
}

export async function pickModelFile(): Promise<string | null> {
  if (!isTauriRuntime()) {
    return window.prompt("输入 GGUF 模型文件路径");
  }

  const selected = await open({
    multiple: false,
    directory: false,
    filters: [{ name: "GGUF 模型", extensions: ["gguf"] }],
  });
  return typeof selected === "string" ? selected : null;
}

export async function pickModelDirectory(): Promise<string | null> {
  if (!isTauriRuntime()) {
    return window.prompt("输入模型目录路径");
  }

  const selected = await open({
    multiple: false,
    directory: true,
  });
  return typeof selected === "string" ? selected : null;
}

export async function pickSpeechToTextModelDirectory(): Promise<string | null> {
  if (!isTauriRuntime()) {
    return window.prompt("Enter speech-to-text model directory path");
  }

  const selected = await open({
    multiple: false,
    directory: true,
  });
  return typeof selected === "string" ? selected : null;
}

export async function addModelFile(path: string): Promise<PreferencesView> {
  return invoke<PreferencesView>("add_model_file", { payload: { path } });
}

export async function addSpeechToTextModelDirectory(
  path: string,
): Promise<PreferencesView> {
  return invoke<PreferencesView>("add_speech_to_text_model_directory", {
    payload: { path },
  });
}

export async function importModelFile(path: string): Promise<PreferencesView> {
  return invoke<PreferencesView>("import_model_file", { payload: { path } });
}

export async function scanModelDirectory(
  path: string,
): Promise<PreferencesView> {
  return invoke<PreferencesView>("scan_model_directory_command", {
    payload: { path },
  });
}

export async function setModelStorageDirectory(
  path: string,
): Promise<PreferencesView> {
  return invoke<PreferencesView>("set_model_storage_directory", {
    payload: { path },
  });
}

export async function setDefaultModel(
  modelId: string | null,
): Promise<PreferencesView> {
  return invoke<PreferencesView>("set_default_model_command", {
    payload: { modelId },
  });
}

export async function setModelAssignment(
  role: ModelAssignmentRole,
  modelId: string | null,
): Promise<PreferencesView> {
  return invoke<PreferencesView>("set_model_assignment_command", {
    payload: { role, modelId },
  });
}

export async function setToolEnabled(
  toolId: string,
  enabled: boolean,
): Promise<PreferencesView> {
  return invoke<PreferencesView>("set_tool_enabled", {
    payload: { toolId, enabled },
  });
}

export async function setAgentModelMode(
  mode: AgentModelMode,
): Promise<PreferencesView> {
  return invoke<PreferencesView>("set_agent_model_mode_command", {
    payload: { mode },
  });
}

export async function saveApiProviderConfig(
  payload: SaveApiProviderPayload,
): Promise<PreferencesView> {
  return invoke<PreferencesView>("save_api_provider_config", { payload });
}

export async function deleteApiProviderConfig(
  providerId: string,
): Promise<PreferencesView> {
  return invoke<PreferencesView>("delete_api_provider_config_command", {
    payload: { providerId },
  });
}

export async function setActiveApiProvider(
  providerId: string,
): Promise<PreferencesView> {
  return invoke<PreferencesView>("set_active_api_provider_command", {
    payload: { providerId },
  });
}

export async function prepareAgentModelSession(): Promise<string | null> {
  if (!isTauriRuntime()) {
    return null;
  }

  const response = await invoke<{ modelSessionId: string | null }>(
    "prepare_agent_model_session",
  );
  return response.modelSessionId;
}

function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}
