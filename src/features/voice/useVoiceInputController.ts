import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getAsrStatus, transcribeVoiceAudio } from "./asrApi";
import {
  buildLevelBuckets,
  encodeWav,
  MAX_RECORDING_SECONDS,
} from "./audioCapture";
import type { DraftSelection } from "./draftInsertion";
import {
  createInitialVoiceInput,
  voiceFailed,
  voiceRecording,
  voiceTranscribing,
} from "./voiceSession";
import {
  canStartVoiceRecording,
  canStopVoiceRecording,
} from "./voiceRecordingGuards";

export type VoiceInputControllerState = {
  voiceInput: ReturnType<typeof createInitialVoiceInput>;
};

type UseVoiceInputControllerArgs = {
  onTranscript: (transcript: string, selection: DraftSelection | null) => void;
};

export function createVoiceInputControllerState(): VoiceInputControllerState {
  return { voiceInput: createInitialVoiceInput(null) };
}

export function voiceControllerFailed(
  state: VoiceInputControllerState,
  error: string,
): VoiceInputControllerState {
  return { ...state, voiceInput: voiceFailed(state.voiceInput, error) };
}

export function useVoiceInputController({
  onTranscript,
}: UseVoiceInputControllerArgs) {
  const [state, setState] = useState(createVoiceInputControllerState);
  const recordingStreamRef = useRef<MediaStream | null>(null);
  const recordingStartingRef = useRef(false);
  const recordingStoppingRef = useRef(false);
  const recordingChunksRef = useRef<Float32Array[]>([]);
  const recordingSampleRateRef = useRef(16_000);
  const recordingStartedAtRef = useRef(0);
  const recordingTimerRef = useRef<number | null>(null);
  const recordingAudioContextRef = useRef<AudioContext | null>(null);
  const recordingProcessorRef = useRef<ScriptProcessorNode | null>(null);
  const lastDraftSelectionRef = useRef<DraftSelection | null>(null);

  const stopRecordingStream = useCallback(() => {
    if (recordingTimerRef.current !== null) {
      window.clearInterval(recordingTimerRef.current);
      recordingTimerRef.current = null;
    }

    recordingProcessorRef.current?.disconnect();
    recordingProcessorRef.current = null;

    const audioContext = recordingAudioContextRef.current;
    recordingAudioContextRef.current = null;
    void audioContext?.close();

    recordingStreamRef.current?.getTracks().forEach((track) => track.stop());
    recordingStreamRef.current = null;
  }, []);

  const refreshVoiceInputAvailability = useCallback(async () => {
    setState({ voiceInput: createInitialVoiceInput(null) });
    const status = await getAsrStatus();
    setState({ voiceInput: createInitialVoiceInput(status) });
  }, []);

  const handleDraftSelectionChange = useCallback(
    (selection: DraftSelection | null) => {
      lastDraftSelectionRef.current = selection;
    },
    [],
  );

  const stopVoiceRecording = useCallback(
    async (selection?: DraftSelection | null) => {
      if (recordingStoppingRef.current) {
        return;
      }

      if (recordingStreamRef.current === null) {
        return;
      }

      recordingStoppingRef.current = true;

      const capturedSelection = selection ?? lastDraftSelectionRef.current;
      const chunks = [...recordingChunksRef.current];
      const sampleRate = recordingSampleRateRef.current;

      if (
        !canStopVoiceRecording({
          stopping: false,
          hasActiveStream: recordingStreamRef.current !== null,
          chunkCount: chunks.length,
        })
      ) {
        stopRecordingStream();
        recordingChunksRef.current = [];
        setState((current) => ({
          voiceInput: createReadyVoiceInput(current.voiceInput),
        }));
        recordingStoppingRef.current = false;
        return;
      }

      stopRecordingStream();
      recordingChunksRef.current = [];
      setState((current) => ({
        voiceInput: voiceTranscribing(current.voiceInput),
      }));

      try {
        const samples = concatenateFloat32Arrays(chunks);
        const transcript = await transcribeVoiceAudio(
          encodeWav(samples, sampleRate),
        );

        onTranscript(transcript.text, capturedSelection);
        setState((current) => ({
          voiceInput: createReadyVoiceInput(current.voiceInput),
        }));
      } catch (error) {
        setState((current) =>
          voiceControllerFailed(
            current,
            `语音转写失败：${formatUnknownError(error)}`,
          ),
        );
      } finally {
        recordingChunksRef.current = [];
        recordingStoppingRef.current = false;
      }
    },
    [onTranscript, stopRecordingStream],
  );

  const startVoiceRecording = useCallback(async () => {
    if (
      !canStartVoiceRecording({
        starting: recordingStartingRef.current,
        stopping: recordingStoppingRef.current,
        hasActiveStream: recordingStreamRef.current !== null,
      })
    ) {
      return;
    }

    recordingStartingRef.current = true;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recordingStreamRef.current = stream;

      const audioContext = new AudioContext();
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      const monitorGain = audioContext.createGain();

      monitorGain.gain.value = 0;
      analyser.fftSize = 64;
      recordingChunksRef.current = [];
      recordingSampleRateRef.current = audioContext.sampleRate;
      recordingStartedAtRef.current = Date.now();
      recordingAudioContextRef.current = audioContext;
      recordingProcessorRef.current = processor;

      processor.onaudioprocess = (event) => {
        const input = event.inputBuffer.getChannelData(0);
        recordingChunksRef.current.push(new Float32Array(input));
      };

      source.connect(analyser);
      source.connect(processor);
      processor.connect(monitorGain);
      monitorGain.connect(audioContext.destination);

      setState((current) => ({
        voiceInput: voiceRecording(current.voiceInput),
      }));

      const levelData = new Uint8Array(analyser.frequencyBinCount);
      recordingTimerRef.current = window.setInterval(() => {
        analyser.getByteTimeDomainData(levelData);
        const elapsedSeconds = Math.min(
          MAX_RECORDING_SECONDS,
          Math.floor((Date.now() - recordingStartedAtRef.current) / 1000),
        );

        setState((current) => ({
          voiceInput: voiceRecording(
            current.voiceInput,
            buildLevelBuckets(levelData, 32),
            elapsedSeconds,
          ),
        }));

        if (elapsedSeconds >= MAX_RECORDING_SECONDS) {
          void stopVoiceRecording(lastDraftSelectionRef.current);
        }
      }, 250);
    } catch (error) {
      stopRecordingStream();
      setState((current) =>
        voiceControllerFailed(
          current,
          `麦克风不可用：${formatUnknownError(error)}`,
        ),
      );
    } finally {
      recordingStartingRef.current = false;
    }
  }, [stopRecordingStream, stopVoiceRecording]);

  const handleVoiceToggle = useCallback(
    async (selection: DraftSelection | null) => {
      if (
        !state.voiceInput.available ||
        state.voiceInput.status === "transcribing"
      ) {
        return;
      }

      if (state.voiceInput.status === "recording") {
        await stopVoiceRecording(selection);
        return;
      }

      await startVoiceRecording();
    },
    [startVoiceRecording, state.voiceInput, stopVoiceRecording],
  );

  useEffect(() => {
    let cancelled = false;

    getAsrStatus().then((status) => {
      if (!cancelled) {
        setState({ voiceInput: createInitialVoiceInput(status) });
      }
    });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return () => {
      stopRecordingStream();
    };
  }, [stopRecordingStream]);

  return useMemo(
    () => ({
      state,
      setState,
      refreshVoiceInputAvailability,
      handleDraftSelectionChange,
      handleVoiceToggle,
      startVoiceRecording,
      stopVoiceRecording,
    }),
    [
      handleDraftSelectionChange,
      handleVoiceToggle,
      refreshVoiceInputAvailability,
      startVoiceRecording,
      state,
      stopVoiceRecording,
    ],
  );
}

function createReadyVoiceInput(
  current: ReturnType<typeof createInitialVoiceInput>,
): ReturnType<typeof createInitialVoiceInput> {
  return {
    ...current,
    available: true,
    status: "idle",
    message: "语音模型已就绪",
    elapsedSeconds: 0,
    levels: [],
  };
}

function concatenateFloat32Arrays(chunks: Float32Array[]): Float32Array {
  const totalLength = chunks.reduce((total, chunk) => total + chunk.length, 0);
  const samples = new Float32Array(totalLength);
  let offset = 0;

  for (const chunk of chunks) {
    samples.set(chunk, offset);
    offset += chunk.length;
  }

  return samples;
}

function formatUnknownError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return String(error);
}
