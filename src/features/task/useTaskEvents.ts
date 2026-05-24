import { invoke } from "@tauri-apps/api/core";

import type { BackendEvent } from "../../shared/events";
import type { ChatAttachment, NodeGraph } from "../../shared/types";

const SIDECAR_URL = "http://127.0.0.1:8765";
const SIDECAR_TOKEN_HEADER = "X-Alita-Sidecar-Token";

export type SubmitMessagePayload = {
  taskId: string;
  content: string;
  attachments: ChatAttachment[];
  modelSessionId?: string | null;
};

export type RunNodeGraphPayload = {
  runId: string;
  taskId: string;
  projectPath: string;
  graph: NodeGraph;
  attachments: ChatAttachment[];
  mode: RunNodeGraphMode;
  disabledToolIds?: string[];
  approvedPermissions?: string[];
  modelSessionId?: string | null;
  signal?: AbortSignal;
};

export type RunNodeGraphMode =
  | { type: "full" }
  | { type: "failed_only"; sourceRunId: string }
  | { type: "from_node"; nodeId: string; sourceRunId?: string };

export async function submitUserMessage(
  payload: SubmitMessagePayload,
): Promise<BackendEvent[]> {
  if (isTauriRuntime() && payload.modelSessionId == null) {
    return invoke<BackendEvent[]>("submit_user_message", { payload });
  }

  return submitViaHttpSidecar(payload);
}

export async function submitUserMessageStream(
  payload: SubmitMessagePayload,
  onEvent: (event: BackendEvent) => void,
): Promise<void> {
  const response = await fetch(`${SIDECAR_URL}/agent/message/stream`, {
    method: "POST",
    headers: await sidecarJsonHeaders(),
    body: JSON.stringify(toSidecarMessage(payload)),
  });

  if (!response.ok) {
    throw new Error(`Agent sidecar returned ${response.status}`);
  }
  if (!response.body) {
    throw new Error("Agent sidecar did not return a streaming body");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parseChunk = createSseEventParser(onEvent);

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    parseChunk(decoder.decode(value, { stream: true }));
  }

  const remainder = decoder.decode();
  if (remainder) {
    parseChunk(remainder);
  }
}

export async function runNodeGraphStream(
  payload: RunNodeGraphPayload,
  onEvent: (event: BackendEvent) => void,
): Promise<void> {
  const response = await fetch(`${SIDECAR_URL}/agent/graph/run/stream`, {
    method: "POST",
    headers: await sidecarJsonHeaders(),
    signal: payload.signal,
    body: JSON.stringify({
      task_id: payload.taskId,
      run_id: payload.runId,
      project_path: payload.projectPath,
      graph: payload.graph,
      mode: toSidecarRunMode(payload.mode),
      disabled_tool_ids: payload.disabledToolIds ?? [],
      approved_permissions: payload.approvedPermissions ?? [],
      model_session_id: payload.modelSessionId ?? null,
      attachments: payload.attachments.map(toSidecarAttachment),
    }),
  });

  await readSseResponse(response, onEvent);
}

export async function cancelNodeGraphRun(
  runId: string,
): Promise<{ cancelled: boolean }> {
  const response = await fetch(`${SIDECAR_URL}/agent/graph/run/cancel`, {
    method: "POST",
    headers: await sidecarJsonHeaders(),
    body: JSON.stringify({ run_id: runId }),
  });

  if (!response.ok) {
    throw new Error(`Agent sidecar returned ${response.status}`);
  }

  return (await response.json()) as { cancelled: boolean };
}

export function createSseEventParser(onEvent: (event: BackendEvent) => void) {
  let buffer = "";

  return (chunk: string) => {
    buffer += chunk;
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() ?? "";

    for (const block of blocks) {
      const data = block
        .split(/\r?\n/)
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice("data:".length).trimStart())
        .join("\n");

      if (!data || data === "[DONE]") {
        continue;
      }

      onEvent(JSON.parse(data) as BackendEvent);
    }
  };
}

function isTauriRuntime(): boolean {
  return "__TAURI_INTERNALS__" in globalThis;
}

async function submitViaHttpSidecar(
  payload: SubmitMessagePayload,
): Promise<BackendEvent[]> {
  const response = await fetch(`${SIDECAR_URL}/agent/message`, {
    method: "POST",
    headers: await sidecarJsonHeaders(),
    body: JSON.stringify(toSidecarMessage(payload)),
  });

  if (!response.ok) {
    throw new Error(`Agent sidecar returned ${response.status}`);
  }

  return (await response.json()) as BackendEvent[];
}

async function sidecarJsonHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const token = await getSidecarAuthToken();
  if (token) {
    headers[SIDECAR_TOKEN_HEADER] = token;
  }
  return headers;
}

async function getSidecarAuthToken(): Promise<string | null> {
  if (!isTauriRuntime()) {
    return null;
  }
  return invoke<string>("get_sidecar_auth_token");
}

function toSidecarMessage(payload: SubmitMessagePayload) {
  return {
    task_id: payload.taskId,
    content: payload.content,
    model_session_id: payload.modelSessionId ?? null,
    attachments: payload.attachments.map(toSidecarAttachment),
  };
}

async function readSseResponse(
  response: Response,
  onEvent: (event: BackendEvent) => void,
): Promise<void> {
  if (!response.ok) {
    throw new Error(`Agent sidecar returned ${response.status}`);
  }
  if (!response.body) {
    throw new Error("Agent sidecar did not return a streaming body");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parseChunk = createSseEventParser(onEvent);

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    parseChunk(decoder.decode(value, { stream: true }));
  }

  const remainder = decoder.decode();
  if (remainder) {
    parseChunk(remainder);
  }
}

function toSidecarAttachment(attachment: ChatAttachment) {
  return {
    attachment_id: attachment.attachmentId,
    name: attachment.name,
    path: attachment.path,
    size_bytes: attachment.sizeBytes,
    mime_type: attachment.mimeType,
  };
}

function toSidecarRunMode(mode: RunNodeGraphMode) {
  if (mode.type === "failed_only") {
    return {
      type: mode.type,
      source_run_id: mode.sourceRunId,
    };
  }

  if (mode.type === "from_node") {
    return {
      type: mode.type,
      node_id: mode.nodeId,
      source_run_id: mode.sourceRunId,
    };
  }

  return { type: "full" };
}
