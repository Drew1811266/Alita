import { open, save } from "@tauri-apps/plugin-dialog";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  pickCreateProjectPath,
  pickOpenProjectPath,
  pickSaveProjectAsPath,
} from "./projectApi";

vi.mock("@tauri-apps/plugin-dialog", () => ({
  open: vi.fn(),
  save: vi.fn(),
}));

const openMock = vi.mocked(open);
const saveMock = vi.mocked(save);

afterEach(() => {
  vi.clearAllMocks();
  delete (globalThis as unknown as { window?: unknown }).window;
});

function setBrowserWindow(promptValue: string | null = null) {
  (globalThis as unknown as { window: Window }).window = {
    prompt: vi.fn(() => promptValue),
  } as unknown as Window;
}

function setTauriWindow() {
  (globalThis as unknown as { window: Window }).window = {
    __TAURI_INTERNALS__: {},
  } as unknown as Window;
}

describe("projectApi", () => {
  it("prompts for Alita project paths in browser fallback mode", async () => {
    setBrowserWindow("D:\\Projects\\demo.alita");

    await expect(pickOpenProjectPath()).resolves.toBe("D:\\Projects\\demo.alita");

    expect(window.prompt).toHaveBeenCalledWith("输入要打开的 .alita 文件路径");
  });

  it("uses only the Alita extension in Tauri project dialogs", async () => {
    setTauriWindow();
    saveMock.mockResolvedValueOnce("D:\\Projects\\new.alita");
    openMock.mockResolvedValueOnce("D:\\Projects\\existing.alita");

    await expect(pickCreateProjectPath()).resolves.toBe("D:\\Projects\\new.alita");
    await expect(pickOpenProjectPath()).resolves.toBe("D:\\Projects\\existing.alita");

    expect(saveMock).toHaveBeenCalledWith({
      defaultPath: "未命名工程.alita",
      filters: [{ name: "Alita 工程", extensions: ["alita"] }],
    });
    expect(openMock).toHaveBeenCalledWith({
      multiple: false,
      directory: false,
      filters: [{ name: "Alita 工程", extensions: ["alita"] }],
    });
  });

  it("appends the Alita extension when saving a project without one", async () => {
    setTauriWindow();
    saveMock.mockResolvedValueOnce("D:\\Projects\\demo.alita");

    await expect(pickSaveProjectAsPath("D:\\Projects\\demo")).resolves.toBe(
      "D:\\Projects\\demo.alita",
    );

    expect(saveMock).toHaveBeenCalledWith({
      defaultPath: "D:\\Projects\\demo.alita",
      filters: [{ name: "Alita 工程", extensions: ["alita"] }],
    });
  });
});
