import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";

import type { AppPreferences, ToolSummary } from "../../shared/types";

export type PreferencesView = {
  preferences: AppPreferences;
  tools: ToolSummary[];
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

export async function addModelFile(path: string): Promise<PreferencesView> {
  return invoke<PreferencesView>("add_model_file", { payload: { path } });
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

export async function setToolEnabled(
  toolId: string,
  enabled: boolean,
): Promise<PreferencesView> {
  return invoke<PreferencesView>("set_tool_enabled", {
    payload: { toolId, enabled },
  });
}

function isTauriRuntime(): boolean {
  return "__TAURI_INTERNALS__" in window;
}
