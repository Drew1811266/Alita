import { secondsToTimerLabel } from "./audioCapture";

type AudioTrackProps = {
  elapsedSeconds: number;
  maxSeconds: number;
  levels: number[];
};

export function AudioTrack({
  elapsedSeconds,
  maxSeconds,
  levels,
}: AudioTrackProps) {
  return (
    <div className="voiceTrack" aria-label="录音音轨">
      <div className="voiceLevelBars" aria-hidden="true">
        {levels.map((level, index) => (
          <span
            className="voiceLevelBar"
            key={`${index}-${level}`}
            style={{ height: `${Math.max(8, Math.round(level * 100))}%` }}
          />
        ))}
      </div>
      <span className="voiceTimer">
        {secondsToTimerLabel(elapsedSeconds)} / {secondsToTimerLabel(maxSeconds)}
      </span>
    </div>
  );
}
