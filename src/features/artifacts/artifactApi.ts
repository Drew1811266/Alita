import { invoke } from "@tauri-apps/api/core";

export async function openArtifact(path: string): Promise<void> {
  await invoke("open_artifact", { path });
}

export async function revealArtifact(path: string): Promise<void> {
  await invoke("reveal_artifact", { path });
}
