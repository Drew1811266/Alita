export type ArtifactPreviewKind =
  | "markdown"
  | "text"
  | "pdf"
  | "unsupported";

const markdownExtensions = new Set(["md", "markdown", "mdown", "mkdn"]);
const textExtensions = new Set([
  "txt",
  "text",
  "json",
  "csv",
  "tsv",
  "log",
  "xml",
  "yaml",
  "yml",
]);

export function detectArtifactPreviewKind(path: string): ArtifactPreviewKind {
  const extension = extensionFromPath(path);
  if (markdownExtensions.has(extension)) {
    return "markdown";
  }

  if (extension === "pdf") {
    return "pdf";
  }

  if (textExtensions.has(extension)) {
    return "text";
  }

  return "unsupported";
}

export function shouldReadArtifactText(kind: ArtifactPreviewKind): boolean {
  return kind === "markdown" || kind === "text";
}

function extensionFromPath(path: string): string {
  const fileName = path.split(/[\\/]/).filter(Boolean).pop() ?? "";
  const lastDot = fileName.lastIndexOf(".");
  if (lastDot < 0 || lastDot === fileName.length - 1) {
    return "";
  }

  return fileName.slice(lastDot + 1).toLowerCase();
}
