import type { VoiceInputView } from "../chat/ChatPanel";
import type { AsrStatus } from "./asrApi";
import { MAX_RECORDING_SECONDS } from "./audioCapture";

const unavailableVoiceMessage = "未配置语音模型";

export function createInitialVoiceInput(
  status: AsrStatus | null,
): VoiceInputView {
  if (status === null) {
    return {
      available: false,
      status: "checking",
      message: "正在检查语音模型",
      elapsedSeconds: 0,
      maxSeconds: MAX_RECORDING_SECONDS,
      levels: [],
    };
  }

  if (!status.available) {
    const message = status.message.trim();

    return {
      available: false,
      status: "unavailable",
      message:
        status.errorCode === "asr_not_configured" || message.length === 0
          ? unavailableVoiceMessage
          : message,
      elapsedSeconds: 0,
      maxSeconds: MAX_RECORDING_SECONDS,
      levels: [],
    };
  }

  return {
    available: true,
    status: "idle",
    message: status.message,
    elapsedSeconds: 0,
    maxSeconds: MAX_RECORDING_SECONDS,
    levels: [],
  };
}

export function voiceRecording(
  current: VoiceInputView,
  levels = current.levels,
  elapsedSeconds = current.elapsedSeconds,
): VoiceInputView {
  return {
    ...current,
    available: true,
    status: "recording",
    message: "录音中",
    elapsedSeconds,
    levels,
  };
}

export function voiceTranscribing(current: VoiceInputView): VoiceInputView {
  return {
    ...current,
    status: "transcribing",
    message: "转写中",
  };
}

export function voiceFailed(
  current: VoiceInputView,
  message: string,
): VoiceInputView {
  return {
    ...current,
    status: "failed",
    message,
    elapsedSeconds: 0,
    levels: [],
  };
}
