import { useEffect, useRef, useState } from "react";
import Plyr from "plyr";
import "plyr/dist/plyr.css";

type VideoArtifactPreviewProps = {
  fileName: string;
  fileUrl: string;
};

export default function VideoArtifactPreview({
  fileName,
  fileUrl,
}: VideoArtifactPreviewProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) {
      return;
    }

    const player = new Plyr(video, {
      controls: [
        "play-large",
        "play",
        "progress",
        "current-time",
        "duration",
        "mute",
        "volume",
        "settings",
        "fullscreen",
      ],
      fullscreen: {
        enabled: true,
        fallback: true,
        iosNative: true,
      },
      keyboard: { focused: true, global: false },
      seekTime: 10,
      tooltips: { controls: true, seek: true },
    });

    return () => {
      player.destroy();
    };
  }, [fileUrl]);

  return (
    <div className="artifactPreviewVideo" data-file-url={fileUrl}>
      {loadError ? (
        <div className="artifactPreviewEmpty">
          <strong>无法预览视频</strong>
          <p>{loadError}</p>
        </div>
      ) : (
        <>
          <div className="artifactPreviewVideoStage">
            <video
              aria-label={fileName}
              className="artifactPreviewVideoContent"
              controls
              onCanPlay={() => setLoadError(null)}
              onError={() =>
                setLoadError("视频文件无法被当前内嵌播放器读取。")
              }
              playsInline
              preload="metadata"
              ref={videoRef}
              src={fileUrl}
            />
          </div>
          <div className="artifactPreviewMediaMeta">
            <strong>{fileName}</strong>
          </div>
        </>
      )}
    </div>
  );
}
