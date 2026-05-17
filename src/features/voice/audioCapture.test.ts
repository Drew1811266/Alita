import { describe, expect, it } from "vitest";

import { buildLevelBuckets, encodeWav, secondsToTimerLabel } from "./audioCapture";

describe("encodeWav", () => {
  it("encodes mono PCM as a WAV file", () => {
    const wav = encodeWav(new Float32Array([0, 0.5, -0.5]), 16000);
    const text = new TextDecoder("ascii").decode(wav.slice(0, 12));

    expect(text).toBe("RIFF*\u0000\u0000\u0000WAVE");
    expect(wav.byteLength).toBe(50);
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
