import { invoke } from "@tauri-apps/api/core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { getAsrStatus, transcribeVoiceAudio } from "./asrApi";

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(),
}));

const invokeMock = vi.mocked(invoke);

afterEach(() => {
  vi.restoreAllMocks();
});

describe("getAsrStatus", () => {
  it("returns unavailable status with the Error rejection message", async () => {
    invokeMock.mockRejectedValue(new Error("sidecar offline"));

    await expect(getAsrStatus()).resolves.toMatchObject({
      available: false,
      message: "sidecar offline",
      errorCode: "asr_status_unavailable",
    });
  });

  it("returns unavailable status with the string rejection message", async () => {
    invokeMock.mockRejectedValue("sidecar unavailable");

    await expect(getAsrStatus()).resolves.toMatchObject({
      available: false,
      message: "sidecar unavailable",
      errorCode: "asr_status_unavailable",
    });
  });
});

describe("transcribeVoiceAudio", () => {
  it("sends base64 WAV bytes to the Tauri command", async () => {
    invokeMock.mockResolvedValue({ text: "转写文本" });

    const result = await transcribeVoiceAudio(new Uint8Array([82, 73, 70, 70]));

    expect(result.text).toBe("转写文本");
    expect(invokeMock).toHaveBeenCalledWith("transcribe_voice_audio", {
      payload: { wavBase64: "UklGRg==" },
    });
  });
});
