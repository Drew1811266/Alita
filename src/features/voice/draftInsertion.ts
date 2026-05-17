export type DraftSelection = {
  start: number;
  end: number;
};

type InsertTranscriptIntoDraftArgs = {
  currentDraft: string;
  transcript: string;
  selection: DraftSelection | null;
};

export function insertTranscriptIntoDraft({
  currentDraft,
  transcript,
  selection,
}: InsertTranscriptIntoDraftArgs): string {
  const trimmedTranscript = transcript.trim();
  if (trimmedTranscript.length === 0) {
    return currentDraft;
  }

  if (currentDraft.length === 0) {
    return trimmedTranscript;
  }

  if (selection === null) {
    return `${currentDraft}\n${trimmedTranscript}`;
  }

  const clampedStart = clampOffset(selection.start, currentDraft.length);
  const clampedEnd = clampOffset(selection.end, currentDraft.length);
  const start = Math.min(clampedStart, clampedEnd);
  const end = Math.max(clampedStart, clampedEnd);

  return `${currentDraft.slice(0, start)}${trimmedTranscript}${currentDraft.slice(end)}`;
}

function clampOffset(offset: number, max: number): number {
  if (!Number.isFinite(offset)) {
    return max;
  }

  return Math.min(Math.max(Math.trunc(offset), 0), max);
}
