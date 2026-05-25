import { invoke } from "@tauri-apps/api/core";

import type { BackendEvent, ResearchChoiceId } from "../../shared/events";
import type { ChatAttachment, NodeGraph } from "../../shared/types";

const SIDECAR_URL = "http://127.0.0.1:8765";
const SIDECAR_TOKEN_HEADER = "X-Alita-Sidecar-Token";

export type SubmitMessagePayload = {
  taskId: string;
  content: string;
  attachments: ChatAttachment[];
  inquiryChoice?: "quick_answer" | "research_flow";
  currentGraph?: NodeGraph;
  hasRunHistory?: boolean;
  artifactRefs?: string[];
  pendingChoice?: Record<string, unknown>;
  modelSessionId?: string | null;
};

export type ResearchChoiceSubmitActionPayload = Omit<
  SubmitMessagePayload,
  "inquiryChoice"
>;

export type TemporaryScriptPermissionDecision = "approve" | "reject";

export type TemporaryScriptPermissionPayload = {
  type: "temporary_script.permission";
  taskId: string;
  nodeId: string;
  decision: TemporaryScriptPermissionDecision;
  approvalFingerprint?: string | null;
  reason?: string;
  currentGraph?: NodeGraph;
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

export async function submitResearchChoice(
  payload: SubmitMessagePayload & { inquiryChoice: ResearchChoiceId },
): Promise<BackendEvent[]> {
  const response = await fetch(`${SIDECAR_URL}/agent/research/choose`, {
    method: "POST",
    headers: await sidecarJsonHeaders(),
    body: JSON.stringify(toSidecarMessage(payload)),
  });

  if (!response.ok) {
    throw new Error(`Agent sidecar returned ${response.status}`);
  }

  return (await response.json()) as BackendEvent[];
}

export function createResearchQuickAnswerPayload(
  payload: ResearchChoiceSubmitActionPayload,
): SubmitMessagePayload {
  return createResearchChoicePayload(payload, "quick_answer");
}

export function createResearchFlowPayload(
  payload: ResearchChoiceSubmitActionPayload,
): SubmitMessagePayload {
  return createResearchChoicePayload(payload, "research_flow");
}

export function createTemporaryScriptPermissionPayload(
  payload: Omit<TemporaryScriptPermissionPayload, "type">,
): TemporaryScriptPermissionPayload {
  return {
    type: "temporary_script.permission",
    taskId: payload.taskId,
    nodeId: payload.nodeId,
    decision: payload.decision,
    ...(payload.approvalFingerprint !== undefined
      ? { approvalFingerprint: payload.approvalFingerprint }
      : {}),
    ...(payload.reason !== undefined ? { reason: payload.reason } : {}),
    ...(payload.currentGraph !== undefined
      ? { currentGraph: payload.currentGraph }
      : {}),
  };
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

export async function submitTemporaryScriptPermission(
  payload: TemporaryScriptPermissionPayload,
): Promise<BackendEvent[]> {
  if (payload.decision === "approve" && !payload.approvalFingerprint) {
    throw new Error("temporary script approval fingerprint is missing");
  }

  const command =
    payload.decision === "approve" ? "scripts/approve" : "scripts/reject";
  const response = await fetch(`${SIDECAR_URL}/agent/${command}`, {
    method: "POST",
    headers: await sidecarJsonHeaders(),
    body: JSON.stringify(toSidecarTemporaryScriptPermission(payload)),
  });

  if (!response.ok) {
    throw new Error(`Agent sidecar returned ${response.status}`);
  }

  return (await response.json()) as BackendEvent[];
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

function createResearchChoicePayload(
  payload: ResearchChoiceSubmitActionPayload,
  inquiryChoice: ResearchChoiceId,
): SubmitMessagePayload {
  return {
    ...payload,
    inquiryChoice,
  };
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
    ...(payload.inquiryChoice ? { inquiry_choice: payload.inquiryChoice } : {}),
    ...(payload.currentGraph ? { current_graph: payload.currentGraph } : {}),
    ...(payload.hasRunHistory !== undefined
      ? { has_run_history: payload.hasRunHistory }
      : {}),
    ...(payload.artifactRefs ? { artifact_refs: payload.artifactRefs } : {}),
    ...(payload.pendingChoice ? { pending_choice: payload.pendingChoice } : {}),
  };
}

export const toSidecarMessageForTest = toSidecarMessage;

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

function toSidecarTemporaryScriptPermission(
  payload: TemporaryScriptPermissionPayload,
) {
  return {
    task_id: payload.taskId,
    node_id: payload.nodeId,
    ...(payload.approvalFingerprint !== undefined
      ? { approval_fingerprint: payload.approvalFingerprint }
      : {}),
    ...(payload.reason !== undefined ? { reason: payload.reason } : {}),
    ...(payload.currentGraph !== undefined
      ? { current_graph: payload.currentGraph }
      : {}),
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
