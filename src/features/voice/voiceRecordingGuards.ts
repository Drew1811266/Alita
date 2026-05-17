export type StartVoiceRecordingGuardState = {
  starting: boolean;
  stopping: boolean;
  hasActiveStream: boolean;
};

export type StopVoiceRecordingGuardState = {
  stopping: boolean;
  hasActiveStream: boolean;
  chunkCount: number;
};

export function canStartVoiceRecording(
  state: StartVoiceRecordingGuardState,
): boolean {
  return !state.starting && !state.stopping && !state.hasActiveStream;
}

export function canStopVoiceRecording(
  state: StopVoiceRecordingGuardState,
): boolean {
  return !state.stopping && state.hasActiveStream && state.chunkCount > 0;
}
