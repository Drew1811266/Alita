import { invoke } from "@tauri-apps/api/core";

import { bytesToBase64 } from "./audioCapture";

export type AsrStatus = {
  available: boolean;
  configured: boolean;
  modelPath: string | null;
  message: string;
  errorCode?: string | null;
};

export type AsrTranscription = {
  text: string;
};

export async function getAsrStatus(): Promise<AsrStatus> {
  try {
    return await invoke<AsrStatus>("get_asr_status");
  } catch (error) {
    return {
      available: false,
      configured: false,
      modelPath: null,
      message:
        error instanceof Error ? error.message : "ASR status is unavailable",
      errorCode: "asr_status_unavailable",
    };
  }
}

export async function transcribeVoiceAudio(
  wavBytes: Uint8Array,
): Promise<AsrTranscription> {
  return await invoke<AsrTranscription>("transcribe_voice_audio", {
    payload: { wavBase64: bytesToBase64(wavBytes) },
  });
}
