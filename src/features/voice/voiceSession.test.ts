import { describe, expect, it } from "vitest";

import type { VoiceInputView } from "../chat/ChatPanel";
import type { AsrStatus } from "./asrApi";
import {
  createInitialVoiceInput,
  voiceFailed,
  voiceRecording,
  voiceTranscribing,
} from "./voiceSession";

const availableStatus: AsrStatus = {
  available: true,
  configured: true,
  modelPath: "D:\\Models\\qwen-asr.gguf",
  message: "语音模型已就绪",
};

const unavailableStatus: AsrStatus = {
  available: false,
  configured: false,
  modelPath: null,
  message: "ASR model path is not configured",
  errorCode: "asr_not_configured",
};

const idleVoiceInput: VoiceInputView = {
  available: true,
  status: "idle",
  message: "语音模型已就绪",
  elapsedSeconds: 0,
  maxSeconds: 60,
  levels: [],
};

describe("voiceSession", () => {
  it("creates idle voice input from available ASR status", () => {
    expect(createInitialVoiceInput(availableStatus)).toEqual(idleVoiceInput);
  });

  it("creates unavailable voice input from unavailable ASR status", () => {
    expect(createInitialVoiceInput(unavailableStatus)).toEqual({
      available: false,
      status: "unavailable",
      message: "未配置语音模型",
      elapsedSeconds: 0,
      maxSeconds: 60,
      levels: [],
    });
  });

  it("keeps the unavailable fallback for unconfigured or empty ASR status messages", () => {
    expect(
      createInitialVoiceInput({
        ...unavailableStatus,
        errorCode: "asr_not_configured",
        message: "ASR model path is not configured",
      }).message,
    ).toBe("未配置语音模型");
    expect(
      createInitialVoiceInput({
        ...unavailableStatus,
        errorCode: "asr_status_unavailable",
        message: "",
      }).message,
    ).toBe("未配置语音模型");
  });

  it("preserves specific unavailable ASR status messages", () => {
    expect(
      createInitialVoiceInput({
        available: false,
        configured: true,
        modelPath: "D:\\Models\\qwen-asr.gguf",
        message: "llama.cpp runtime failed to load",
        errorCode: "asr_status_unavailable",
      }).message,
    ).toBe("llama.cpp runtime failed to load");
    expect(
      createInitialVoiceInput({
        available: false,
        configured: true,
        modelPath: "D:\\Models\\missing.gguf",
        message: "ASR model file does not exist",
        errorCode: "asr_model_missing",
      }).message,
    ).toBe("ASR model file does not exist");
  });

  it("creates checking voice input while ASR status is loading", () => {
    expect(createInitialVoiceInput(null)).toEqual({
      available: false,
      status: "checking",
      message: "正在检查语音模型",
      elapsedSeconds: 0,
      maxSeconds: 60,
      levels: [],
    });
  });

  it("updates voice input while recording", () => {
    expect(voiceRecording(idleVoiceInput, [0.1, 0.8], 4)).toEqual({
      ...idleVoiceInput,
      available: true,
      status: "recording",
      message: "录音中",
      elapsedSeconds: 4,
      levels: [0.1, 0.8],
    });
  });

  it("keeps current recording metrics when recording inputs are omitted", () => {
    const current: VoiceInputView = {
      ...idleVoiceInput,
      elapsedSeconds: 7,
      levels: [0.3, 0.5],
    };

    expect(voiceRecording(current)).toEqual({
      ...current,
      available: true,
      status: "recording",
      message: "录音中",
    });
  });

  it("updates voice input while transcribing", () => {
    expect(voiceTranscribing(idleVoiceInput)).toEqual({
      ...idleVoiceInput,
      status: "transcribing",
      message: "转写中",
    });
  });

  it("updates voice input after a recording failure", () => {
    expect(voiceFailed(idleVoiceInput, "麦克风不可用")).toEqual({
      ...idleVoiceInput,
      status: "failed",
      message: "麦克风不可用",
      elapsedSeconds: 0,
      levels: [],
    });
  });
});
