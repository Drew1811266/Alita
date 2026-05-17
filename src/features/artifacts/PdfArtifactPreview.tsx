import { useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import pdfWorker from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjs.GlobalWorkerOptions.workerSrc = pdfWorker;

type PdfArtifactPreviewProps = {
  fileName: string;
  fileUrl: string;
};

export default function PdfArtifactPreview({
  fileName,
  fileUrl,
}: PdfArtifactPreviewProps) {
  const [pageNumber, setPageNumber] = useState(1);
  const [pageCount, setPageCount] = useState<number | null>(null);
  const [pageWidth, setPageWidth] = useState<number | undefined>();
  const [loadError, setLoadError] = useState<string | null>(null);
  const documentFrameRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const frame = documentFrameRef.current;
    if (!frame) {
      return;
    }

    const updatePageWidth = () => {
      setPageWidth(Math.max(240, Math.min(920, frame.clientWidth - 4)));
    };
    updatePageWidth();

    if (typeof ResizeObserver === "undefined") {
      return;
    }

    const observer = new ResizeObserver(updatePageWidth);
    observer.observe(frame);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="artifactPreviewPdf" data-file-url={fileUrl}>
      <div className="artifactPreviewPdfToolbar">
        <strong>PDF 预览</strong>
        {pageCount ? (
          <span>
            {pageNumber} / {pageCount}
          </span>
        ) : null}
      </div>
      {loadError ? (
        <div className="artifactPreviewEmpty">
          <strong>无法预览 PDF</strong>
          <p>{loadError}</p>
        </div>
      ) : (
        <div className="artifactPreviewPdfDocumentFrame" ref={documentFrameRef}>
          <Document
            file={fileUrl}
            loading={
              <div className="artifactPreviewEmpty">
                <strong>正在读取 PDF</strong>
                <p>{fileName}</p>
              </div>
            }
            onLoadError={(error) => setLoadError(String(error))}
            onLoadSuccess={({ numPages }) => {
              setPageCount(numPages);
              setPageNumber(1);
            }}
          >
            <Page
              pageNumber={pageNumber}
              renderAnnotationLayer
              renderTextLayer
              width={pageWidth}
            />
          </Document>
        </div>
      )}
      {pageCount && pageCount > 1 ? (
        <div className="artifactPreviewPdfPager">
          <button
            className="secondaryButton compactButton"
            disabled={pageNumber <= 1}
            onClick={() => setPageNumber((current) => Math.max(1, current - 1))}
            type="button"
          >
            上一页
          </button>
          <button
            className="secondaryButton compactButton"
            disabled={pageNumber >= pageCount}
            onClick={() =>
              setPageNumber((current) => Math.min(pageCount, current + 1))
            }
            type="button"
          >
            下一页
          </button>
        </div>
      ) : null}
    </div>
  );
}
