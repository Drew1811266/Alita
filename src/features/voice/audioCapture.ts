export const MAX_RECORDING_SECONDS = 60;
export const TARGET_SAMPLE_RATE = 16_000;

const WAV_HEADER_BYTES = 44;
const BYTES_PER_SAMPLE = 2;
const BASE64_CHUNK_SIZE = 0x8000;

export function secondsToTimerLabel(seconds: number): string {
  const elapsedSeconds = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(elapsedSeconds / 60);
  const remainingSeconds = elapsedSeconds % 60;

  return `${padTimerPart(minutes)}:${padTimerPart(remainingSeconds)}`;
}

export function buildLevelBuckets(
  data: Uint8Array,
  bucketCount: number,
): number[] {
  if (bucketCount <= 0) {
    return [];
  }

  if (data.length === 0) {
    return Array.from({ length: bucketCount }, () => 0);
  }

  return Array.from({ length: bucketCount }, (_, bucketIndex) => {
    const start = Math.floor((bucketIndex * data.length) / bucketCount);
    const end = Math.max(
      start + 1,
      Math.floor(((bucketIndex + 1) * data.length) / bucketCount),
    );
    let peak = 0;

    for (let index = start; index < Math.min(end, data.length); index += 1) {
      const amplitude = Math.min(1, Math.abs(data[index] - 128) / 127);
      peak = Math.max(peak, amplitude);
    }

    return Number(peak.toFixed(3));
  });
}

export function encodeWav(
  samples: Float32Array,
  sampleRate: number,
): Uint8Array {
  const pcmSamples =
    sampleRate === TARGET_SAMPLE_RATE
      ? samples
      : resampleLinear(samples, sampleRate, TARGET_SAMPLE_RATE);
  const dataSize = pcmSamples.length * BYTES_PER_SAMPLE;
  const wav = new Uint8Array(WAV_HEADER_BYTES + dataSize);
  const view = new DataView(wav.buffer);

  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeAscii(view, 8, "WAVE");
  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, TARGET_SAMPLE_RATE, true);
  view.setUint32(28, TARGET_SAMPLE_RATE * BYTES_PER_SAMPLE, true);
  view.setUint16(32, BYTES_PER_SAMPLE, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, "data");
  view.setUint32(40, dataSize, true);

  for (let index = 0; index < pcmSamples.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, pcmSamples[index]));
    const value = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
    view.setInt16(WAV_HEADER_BYTES + index * BYTES_PER_SAMPLE, value, true);
  }

  return wav;
}

export function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";

  for (let index = 0; index < bytes.length; index += BASE64_CHUNK_SIZE) {
    const chunk = bytes.subarray(index, index + BASE64_CHUNK_SIZE);
    let chunkText = "";

    for (let chunkIndex = 0; chunkIndex < chunk.length; chunkIndex += 1) {
      chunkText += String.fromCharCode(chunk[chunkIndex]);
    }

    binary += chunkText;
  }

  return btoa(binary);
}

function padTimerPart(value: number): string {
  return value.toString().padStart(2, "0");
}

function resampleLinear(
  samples: Float32Array,
  sourceRate: number,
  targetRate: number,
): Float32Array {
  if (samples.length === 0) {
    return samples;
  }

  if (!Number.isFinite(sourceRate) || sourceRate <= 0) {
    throw new RangeError("sampleRate must be a positive number");
  }

  const outputLength = Math.max(
    1,
    Math.round((samples.length * targetRate) / sourceRate),
  );
  const output = new Float32Array(outputLength);

  for (let index = 0; index < outputLength; index += 1) {
    const sourcePosition = (index * sourceRate) / targetRate;
    const sourceIndex = Math.floor(sourcePosition);
    const nextIndex = Math.min(sourceIndex + 1, samples.length - 1);
    const fraction = sourcePosition - sourceIndex;
    const start = samples[Math.min(sourceIndex, samples.length - 1)];
    const end = samples[nextIndex];

    output[index] = start + (end - start) * fraction;
  }

  return output;
}

function writeAscii(view: DataView, offset: number, value: string): void {
  for (let index = 0; index < value.length; index += 1) {
    view.setUint8(offset + index, value.charCodeAt(index));
  }
}
