import { invoke } from "@tauri-apps/api/core";
import { open, save } from "@tauri-apps/plugin-dialog";

import type { AlitaProject, ProjectOpenResult } from "../../shared/types";

export async function pickCreateProjectPath(): Promise<string | null> {
  if (!isTauriRuntime()) {
    return window.prompt("输入要创建的 .alita 文件路径");
  }

  const selected = await save({
    defaultPath: "未命名工程.alita",
    filters: [{ name: "Alita 工程", extensions: ["alita"] }],
  });
  return typeof selected === "string" ? selected : null;
}

export async function pickOpenProjectPath(): Promise<string | null> {
  if (!isTauriRuntime()) {
    return window.prompt("输入要打开的 .alita 文件路径");
  }

  const selected = await open({
    multiple: false,
    directory: false,
    filters: [{ name: "Alita 工程", extensions: ["alita"] }],
  });
  return typeof selected === "string" ? selected : null;
}

export async function pickSaveProjectAsPath(
  currentPath: string,
): Promise<string | null> {
  if (!isTauriRuntime()) {
    return window.prompt("输入另存为 .alita 文件路径", ensureAlitaProjectPath(currentPath));
  }

  const selected = await save({
    defaultPath: ensureAlitaProjectPath(currentPath),
    filters: [{ name: "Alita 工程", extensions: ["alita"] }],
  });
  return typeof selected === "string" ? selected : null;
}

export async function createProject(
  path: string,
  name: string,
): Promise<ProjectOpenResult> {
  return invoke<ProjectOpenResult>("create_project", {
    payload: { path, name },
  });
}

export async function openProject(path: string): Promise<ProjectOpenResult> {
  return invoke<ProjectOpenResult>("open_project", { path });
}

export async function saveProject(
  project: AlitaProject,
  path = project.path,
): Promise<ProjectOpenResult> {
  return invoke<ProjectOpenResult>("save_project", {
    payload: { path, project: { ...project, path } },
  });
}

function isTauriRuntime(): boolean {
  return "__TAURI_INTERNALS__" in window;
}

function ensureAlitaProjectPath(path: string): string {
  return /\.alita$/i.test(path) ? path : `${path}.alita`;
}
