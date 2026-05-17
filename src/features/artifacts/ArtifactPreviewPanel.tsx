import { lazy, Suspense } from "react";

import type { AgentNode } from "../../shared/types";
import type { ArtifactTextPreview } from "./artifactApi";
import type { PreviewArtifactSelection } from "./artifactPreview";
import type { ArtifactPreviewKind } from "./artifactPreviewKind";

const MarkdownArtifactPreview = lazy(() =>
  import("./MarkdownArtifactPreview").then((module) => ({
    default: module.MarkdownArtifactPreview,
  })),
);
const PdfArtifactPreview = lazy(() => import("./PdfArtifactPreview"));

type ArtifactPreviewPanelProps = {
  selectedNode: AgentNode | null;
  artifact: PreviewArtifactSelection | null;
  previewKind: ArtifactPreviewKind;
  fileUrl: string | null;
  preview: ArtifactTextPreview | null;
  loading: boolean;
  error: string | null;
  onOpenArtifact?: (path: string) => void;
  onRevealArtifact?: (path: string) => void;
};

export function ArtifactPreviewPanel({
  selectedNode,
  artifact,
  previewKind,
  fileUrl,
  preview,
  loading,
  error,
  onOpenArtifact,
  onRevealArtifact,
}: ArtifactPreviewPanelProps) {
  return (
    <div className="artifactPreviewPanel">
      <header className="artifactPreviewHeader">
        <div>
          <p className="artifactPreviewKicker">文件预览</p>
          <h2>{artifact?.fileName ?? "未选择导出文件"}</h2>
          {artifact ? <p title={artifact.path}>{artifact.path}</p> : null}
        </div>
        <span className="statusBadge">
          {loading ? "读取中" : artifact ? "已选择" : "等待"}
        </span>
      </header>

      <div className="artifactPreviewBody">
        {!selectedNode ? (
          <EmptyPreviewState
            title="未选择导出文件"
            body="选择导出文件节点后，这里显示本地文件内容。"
          />
        ) : !artifact ? (
          <EmptyPreviewState
            title={
              selectedNode.nodeType === "output"
                ? "导出文件尚未生成"
                : "当前节点没有可预览文件"
            }
            body={`当前节点：${selectedNode.displayName}`}
          />
        ) : (
          <>
            <div className="artifactPreviewMeta">
              <span>{formatBytes(preview?.sizeBytes ?? 0)}</span>
              <div className="artifactPreviewActions">
                {onOpenArtifact ? (
                  <button
                    className="secondaryButton compactButton"
                    onClick={() => onOpenArtifact(artifact.path)}
                    type="button"
                  >
                    打开
                  </button>
                ) : null}
                {onRevealArtifact ? (
                  <button
                    className="secondaryButton compactButton"
                    onClick={() => onRevealArtifact(artifact.path)}
                    type="button"
                  >
                    定位
                  </button>
                ) : null}
              </div>
            </div>

            <PreviewBody
              artifact={artifact}
              error={error}
              fileUrl={fileUrl}
              loading={loading}
              preview={preview}
              previewKind={previewKind}
            />
          </>
        )}
      </div>
    </div>
  );
}

function PreviewBody({
  artifact,
  error,
  fileUrl,
  loading,
  preview,
  previewKind,
}: {
  artifact: PreviewArtifactSelection;
  error: string | null;
  fileUrl: string | null;
  loading: boolean;
  preview: ArtifactTextPreview | null;
  previewKind: ArtifactPreviewKind;
}) {
  if (previewKind === "pdf") {
    return fileUrl ? (
      <Suspense
        fallback={
          <PdfPreviewShell fileName={artifact.fileName} fileUrl={fileUrl} />
        }
      >
        <PdfArtifactPreview fileName={artifact.fileName} fileUrl={fileUrl} />
      </Suspense>
    ) : (
      <EmptyPreviewState title="无法预览 PDF" body="本地文件 URL 生成失败。" />
    );
  }

  if (previewKind === "unsupported") {
    return (
      <EmptyPreviewState
        title="暂不支持内嵌预览"
        body="可以使用打开或定位按钮在系统应用中查看这个文件。"
      />
    );
  }

  if (loading) {
    return <EmptyPreviewState title="正在读取文件" body={artifact.fileName} />;
  }

  if (error) {
    return <EmptyPreviewState title="无法预览文件" body={error} />;
  }

  if (!preview) {
    return <EmptyPreviewState title="暂无内容" body={artifact.fileName} />;
  }

  return (
    <>
      {preview.truncated ? (
        <p className="artifactPreviewNotice">
          文件较大，当前只显示前半部分内容。
        </p>
      ) : null}
      {previewKind === "markdown" ? (
        <Suspense fallback={<MarkdownPreviewShell />}>
          <MarkdownArtifactPreview content={preview.content} />
        </Suspense>
      ) : (
        <pre className="artifactPreviewContent">{preview.content}</pre>
      )}
    </>
  );
}

function MarkdownPreviewShell() {
  return (
    <div className="artifactPreviewMarkdown">
      <p>正在渲染 Markdown</p>
    </div>
  );
}

function PdfPreviewShell({
  fileName,
  fileUrl,
}: {
  fileName: string;
  fileUrl: string;
}) {
  return (
    <div className="artifactPreviewPdf" data-file-url={fileUrl}>
      <div className="artifactPreviewPdfToolbar">
        <strong>PDF 预览</strong>
        <span>加载中</span>
      </div>
      <p className="artifactPreviewPdfFallback">{fileName}</p>
    </div>
  );
}

function EmptyPreviewState({
  title,
  body,
}: {
  title: string;
  body: string;
}) {
  return (
    <div className="artifactPreviewEmpty">
      <strong>{title}</strong>
      <p>{body}</p>
    </div>
  );
}

function formatBytes(sizeBytes: number): string {
  if (sizeBytes <= 0) {
    return "大小未知";
  }

  if (sizeBytes < 1024) {
    return `${sizeBytes} B`;
  }

  if (sizeBytes < 1024 * 1024) {
    return `${(sizeBytes / 1024).toFixed(1)} KB`;
  }

  return `${(sizeBytes / 1024 / 1024).toFixed(1)} MB`;
}
