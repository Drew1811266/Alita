import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";

import type { ChatAttachment } from "../../shared/types";

type DialogSelection = string | string[] | null;

export function normalizeSelectedAttachmentPaths(
  selected: DialogSelection,
): string[] {
  if (!selected) {
    return [];
  }

  return Array.isArray(selected) ? selected : [selected];
}

export function createBrowserAttachmentFromPath(path: string): ChatAttachment {
  const name = path.split(/[\\/]/).pop() || path;
  return {
    attachmentId: `attachment-${crypto.randomUUID()}`,
    name,
    path,
    sizeBytes: 0,
    mimeType: "application/octet-stream",
  };
}

export async function pickChatAttachments(): Promise<ChatAttachment[]> {
  if (!isTauriRuntime()) {
    const value = window.prompt("输入要添加的文件路径，多个路径用分号分隔");
    if (!value) {
      return [];
    }

    return value
      .split(";")
      .map((path) => path.trim())
      .filter(Boolean)
      .map(createBrowserAttachmentFromPath);
  }

  const selected = await open({
    multiple: true,
    directory: false,
  });
  const paths = normalizeSelectedAttachmentPaths(selected);
  if (paths.length === 0) {
    return [];
  }

  return invoke<ChatAttachment[]>("get_attachment_metadata", {
    payload: { paths },
  });
}

function isTauriRuntime(): boolean {
  return "__TAURI_INTERNALS__" in window;
}
