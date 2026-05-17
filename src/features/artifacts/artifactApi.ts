import { convertFileSrc, invoke } from "@tauri-apps/api/core";

export type ArtifactTextPreview = {
  path: string;
  fileName: string;
  sizeBytes: number;
  content: string;
  truncated: boolean;
};

export async function openArtifact(path: string): Promise<void> {
  await invoke("open_artifact", { path });
}

export async function revealArtifact(path: string): Promise<void> {
  await invoke("reveal_artifact", { path });
}

export async function readArtifactText(
  path: string,
): Promise<ArtifactTextPreview> {
  return await invoke<ArtifactTextPreview>("read_artifact_text", { path });
}

export function artifactFileUrl(path: string): string {
  return convertFileSrc(path);
}
