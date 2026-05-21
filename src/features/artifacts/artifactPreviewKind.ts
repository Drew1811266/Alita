export type ArtifactPreviewKind =
  | "markdown"
  | "text"
  | "pdf"
  | "image"
  | "video"
  | "unsupported";

const markdownExtensions = new Set(["md", "markdown", "mdown", "mkdn"]);
const imageExtensions = new Set([
  "png",
  "jpg",
  "jpeg",
  "webp",
  "gif",
  "svg",
  "avif",
]);
const videoExtensions = new Set(["mp4", "webm", "ogg", "mov", "m4v"]);
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

  if (imageExtensions.has(extension)) {
    return "image";
  }

  if (videoExtensions.has(extension)) {
    return "video";
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
