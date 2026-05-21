import { useEffect, useRef, useState } from "react";
import PhotoSwipeLightbox from "photoswipe/lightbox";
import "photoswipe/style.css";

type ImageArtifactPreviewProps = {
  fileName: string;
  fileUrl: string;
};

type ImageDimensions = {
  width: number;
  height: number;
};

export default function ImageArtifactPreview({
  fileName,
  fileUrl,
}: ImageArtifactPreviewProps) {
  const galleryRef = useRef<HTMLDivElement | null>(null);
  const [dimensions, setDimensions] = useState<ImageDimensions | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    const gallery = galleryRef.current;
    if (!gallery) {
      return;
    }

    const lightbox = new PhotoSwipeLightbox({
      gallery,
      children: "a",
      pswpModule: () => import("photoswipe"),
    });
    lightbox.init();

    return () => {
      lightbox.destroy();
    };
  }, [fileUrl]);

  const previewWidth = dimensions?.width ?? 1600;
  const previewHeight = dimensions?.height ?? 1200;

  return (
    <div className="artifactPreviewImage" data-file-url={fileUrl}>
      {loadError ? (
        <div className="artifactPreviewEmpty">
          <strong>无法预览图片</strong>
          <p>{loadError}</p>
        </div>
      ) : (
        <>
          <div className="artifactPreviewImageStage" ref={galleryRef}>
            <a
              className="artifactPreviewImageLink"
              data-pswp-height={previewHeight}
              data-pswp-width={previewWidth}
              href={fileUrl}
              target="_blank"
              rel="noreferrer"
            >
              <img
                alt={fileName}
                className="artifactPreviewImageContent"
                draggable={false}
                onError={() => setLoadError("图片文件无法被当前预览器读取。")}
                onLoad={(event) => {
                  setLoadError(null);
                  const image = event.currentTarget;
                  setDimensions({
                    width: image.naturalWidth || 1600,
                    height: image.naturalHeight || 1200,
                  });
                }}
                src={fileUrl}
              />
            </a>
          </div>
          <div className="artifactPreviewMediaMeta">
            <strong>{fileName}</strong>
            {dimensions ? (
              <span>
                {dimensions.width} × {dimensions.height}
              </span>
            ) : null}
          </div>
        </>
      )}
    </div>
  );
}
