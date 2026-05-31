import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-pdf", () => ({
  Document: () => null,
  Page: () => null,
  pdfjs: { GlobalWorkerOptions: {} },
}));

vi.mock("pdfjs-dist/build/pdf.worker.min.mjs?url", () => ({
  default: "pdf-worker.js",
}));

vi.mock("./ImageArtifactPreview", () => ({
  default: ({ fileName, fileUrl }: { fileName: string; fileUrl: string }) => (
    <div className="artifactPreviewImage" data-file-url={fileUrl}>
      {fileName}
    </div>
  ),
}));

vi.mock("./VideoArtifactPreview", () => ({
  default: ({ fileName, fileUrl }: { fileName: string; fileUrl: string }) => (
    <div className="artifactPreviewVideo" data-file-url={fileUrl}>
      {fileName}
    </div>
  ),
}));

import { ArtifactPreviewPanel } from "./ArtifactPreviewPanel";
import type { ArtifactTextPreview } from "./artifactApi";
import type { PreviewArtifactSelection } from "./artifactPreview";
import { detectArtifactPreviewKind } from "./artifactPreviewKind";
import type { AgentNode } from "../../shared/types";

const outputNode: AgentNode = {
  nodeId: "file-export",
  nodeType: "output",
  displayName: "导出文件",
  status: "completed",
  inputPorts: [],
  outputPorts: [],
  dependencies: [],
  summary: "导出最终文件",
  createdBy: "agent",
  artifactRefs: ["D:\\Project\\artifacts\\report.md"],
  retryCount: 0,
  position: { x: 0, y: 0 },
};

const artifact: PreviewArtifactSelection = {
  artifactId: "report",
  fileName: "report.md",
  path: "D:\\Project\\artifacts\\report.md",
  sourceNodeId: "file-export",
};

const preview: ArtifactTextPreview = {
  path: "D:\\Project\\artifacts\\report.md",
  fileName: "report.md",
  sizeBytes: 42,
  content: "# Report\n\nAlpha",
  truncated: false,
};

describe("ArtifactPreviewPanel", () => {
  it("renders an empty state before an output artifact is selected", () => {
    const markup = renderToStaticMarkup(
      <ArtifactPreviewPanel
        artifact={null}
        error={null}
        fileUrl={null}
        loading={false}
        preview={null}
        previewKind="unsupported"
        selectedNode={null}
      />,
    );

    expect(markup).toContain("文件预览");
    expect(markup).toContain("未选择导出文件");
  });

  it("renders text preview content for the selected artifact", () => {
    const markup = renderToStaticMarkup(
      <ArtifactPreviewPanel
        artifact={artifact}
        error={null}
        fileUrl={null}
        loading={false}
        preview={preview}
        previewKind="text"
        selectedNode={outputNode}
        onOpenArtifact={() => undefined}
        onRevealArtifact={() => undefined}
      />,
    );

    expect(markup).toContain("report.md");
    expect(markup).toContain("D:\\Project\\artifacts\\report.md");
    expect(markup).toContain("# Report");
    expect(markup).toContain("Alpha");
    expect(markup).toContain("打开");
    expect(markup).toContain("定位");
  });

  it("routes markdown files to a markdown preview surface", () => {
    const markup = renderToStaticMarkup(
      <ArtifactPreviewPanel
        artifact={artifact}
        error={null}
        fileUrl={null}
        loading={false}
        preview={preview}
        previewKind="markdown"
        selectedNode={outputNode}
      />,
    );

    expect(markup).toContain("artifactPreviewMarkdown");
  });

  it("renders a pdf preview surface when the selected artifact is a PDF", () => {
    const markup = renderToStaticMarkup(
      <ArtifactPreviewPanel
        artifact={{ ...artifact, fileName: "report.pdf", path: "D:\\Project\\artifacts\\report.pdf" }}
        error={null}
        fileUrl="asset://localhost/report.pdf"
        loading={false}
        preview={null}
        previewKind="pdf"
        selectedNode={{
          ...outputNode,
          artifactRefs: ["D:\\Project\\artifacts\\report.pdf"],
        }}
      />,
    );

    expect(markup).toContain("artifactPreviewPdf");
    expect(markup).toContain("PDF 预览");
  });
  it("renders an image preview surface when the selected artifact is an image", () => {
    const markup = renderToStaticMarkup(
      <ArtifactPreviewPanel
        artifact={{
          ...artifact,
          fileName: "diagram.png",
          path: "D:\\Project\\artifacts\\diagram.png",
        }}
        error={null}
        fileUrl="asset://localhost/diagram.png"
        loading={false}
        preview={null}
        previewKind="image"
        selectedNode={{
          ...outputNode,
          artifactRefs: ["D:\\Project\\artifacts\\diagram.png"],
        }}
      />,
    );

    expect(markup).toContain("artifactPreviewImage");
    expect(markup).toContain("diagram.png");
  });

  it("renders a video preview surface when the selected artifact is a video", () => {
    const markup = renderToStaticMarkup(
      <ArtifactPreviewPanel
        artifact={{
          ...artifact,
          fileName: "demo.mp4",
          path: "D:\\Project\\artifacts\\demo.mp4",
        }}
        error={null}
        fileUrl="asset://localhost/demo.mp4"
        loading={false}
        preview={null}
        previewKind="video"
        selectedNode={{
          ...outputNode,
          artifactRefs: ["D:\\Project\\artifacts\\demo.mp4"],
        }}
      />,
    );

    expect(markup).toContain("artifactPreviewVideo");
    expect(markup).toContain("demo.mp4");
  });

  it("renders unsupported state and system actions for a wav artifact", () => {
    const wavArtifact = {
      ...artifact,
      fileName: "voice-note.wav",
      path: "D:\\Project\\artifacts\\voice-note.wav",
    };

    const markup = renderToStaticMarkup(
      <ArtifactPreviewPanel
        artifact={wavArtifact}
        error={null}
        fileUrl="asset://localhost/voice-note.wav"
        loading={false}
        preview={null}
        previewKind={detectArtifactPreviewKind(wavArtifact.path)}
        selectedNode={{
          ...outputNode,
          artifactRefs: [wavArtifact.path],
        }}
        onOpenArtifact={() => undefined}
        onRevealArtifact={() => undefined}
      />,
    );

    expect(markup).toContain("voice-note.wav");
    expect(markup).toContain("暂不支持内嵌预览");
    expect(markup).toContain("打开");
    expect(markup).toContain("定位");
    expect(markup).toContain("artifactPreviewEmpty");
  });
});
