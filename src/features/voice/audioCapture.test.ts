import { describe, expect, it } from "vitest";

import { buildLevelBuckets, encodeWav, secondsToTimerLabel } from "./audioCapture";
import {
  canStartVoiceRecording,
  canStopVoiceRecording,
} from "./voiceRecordingGuards";

describe("encodeWav", () => {
  it("encodes mono 16-bit PCM WAV fields at the target sample rate", () => {
    const wav = encodeWav(new Float32Array([0, 1, -1]), 16000);
    const view = new DataView(wav.buffer);

    expect(ascii(wav, 0, 4)).toBe("RIFF");
    expect(view.getUint32(4, true)).toBe(42);
    expect(ascii(wav, 8, 4)).toBe("WAVE");
    expect(ascii(wav, 12, 4)).toBe("fmt ");
    expect(view.getUint16(20, true)).toBe(1);
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint32(24, true)).toBe(16000);
    expect(view.getUint32(28, true)).toBe(32000);
    expect(view.getUint16(32, true)).toBe(2);
    expect(view.getUint16(34, true)).toBe(16);
    expect(ascii(wav, 36, 4)).toBe("data");
    expect(view.getUint32(40, true)).toBe(6);
    expect(wav.byteLength).toBe(50);
    expect(pcmSamples(wav)).toEqual([0, 32767, -32768]);
  });

  it("downsamples 48k audio to 16k without changing the target WAV rate", () => {
    const wav = encodeWav(new Float32Array(48), 48000);
    const view = new DataView(wav.buffer);

    expect(view.getUint32(24, true)).toBe(16000);
    expect(view.getUint32(40, true)).toBe(32);
    expect(pcmSamples(wav)).toHaveLength(16);
  });

  it("uses linear interpolation for non-integer resampling ratios", () => {
    const wav = encodeWav(new Float32Array([0, 0, 0, 1, 1]), 44100);

    expect(pcmSamples(wav)).toEqual([0, 24780]);
  });

  it("upsamples 8k audio to 16k without collapsing duration", () => {
    const wav = encodeWav(new Float32Array([0, 1]), 8000);

    expect(pcmSamples(wav)).toEqual([0, 16383, 32767, 32767]);
  });
});

describe("buildLevelBuckets", () => {
  it("creates stable normalized waveform levels", () => {
    const levels = buildLevelBuckets(new Uint8Array([128, 255, 0, 128]), 4);

    expect(levels).toEqual([0, 1, 1, 0]);
  });
});

describe("secondsToTimerLabel", () => {
  it("formats elapsed seconds as mm:ss", () => {
    expect(secondsToTimerLabel(0)).toBe("00:00");
    expect(secondsToTimerLabel(65)).toBe("01:05");
  });
});

describe("voice recording guards", () => {
  it("blocks recording start while setup, recording, or stop is in progress", () => {
    expect(
      canStartVoiceRecording({
        starting: true,
        stopping: false,
        hasActiveStream: false,
      }),
    ).toBe(false);
    expect(
      canStartVoiceRecording({
        starting: false,
        stopping: false,
        hasActiveStream: true,
      }),
    ).toBe(false);
    expect(
      canStartVoiceRecording({
        starting: false,
        stopping: true,
        hasActiveStream: false,
      }),
    ).toBe(false);
  });

  it("allows recording start only when no lifecycle operation is active", () => {
    expect(
      canStartVoiceRecording({
        starting: false,
        stopping: false,
        hasActiveStream: false,
      }),
    ).toBe(true);
  });

  it("blocks duplicate or empty stops before transcription", () => {
    expect(
      canStopVoiceRecording({
        stopping: true,
        hasActiveStream: true,
        chunkCount: 3,
      }),
    ).toBe(false);
    expect(
      canStopVoiceRecording({
        stopping: false,
        hasActiveStream: false,
        chunkCount: 3,
      }),
    ).toBe(false);
    expect(
      canStopVoiceRecording({
        stopping: false,
        hasActiveStream: true,
        chunkCount: 0,
      }),
    ).toBe(false);
  });

  it("allows stop only for one active recording with audio chunks", () => {
    expect(
      canStopVoiceRecording({
        stopping: false,
        hasActiveStream: true,
        chunkCount: 1,
      }),
    ).toBe(true);
  });
});

function ascii(bytes: Uint8Array, offset: number, length: number): string {
  return new TextDecoder("ascii").decode(bytes.slice(offset, offset + length));
}

function pcmSamples(wav: Uint8Array): number[] {
  const view = new DataView(wav.buffer);
  const sampleCount = view.getUint32(40, true) / 2;

  return Array.from({ length: sampleCount }, (_, index) =>
    view.getInt16(44 + index * 2, true),
  );
}
