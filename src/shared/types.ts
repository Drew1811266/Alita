export type NodeStatus =
  | "waiting"
  | "ready"
  | "running"
  | "completed"
  | "failed"
  | "needs_user_input"
  | "needs_permission"
  | "skipped";

export type NodeType =
  | "fixed_tool"
  | "model"
  | "output"
  | "temporary_placeholder";

export type NodePort = {
  id: string;
  label: string;
  dataType: "text" | "document" | "artifact" | "json";
};

export type AgentNode = {
  nodeId: string;
  nodeType: NodeType;
  displayName: string;
  status: NodeStatus;
  inputPorts: NodePort[];
  outputPorts: NodePort[];
  dependencies: string[];
  toolRef?: string;
  modelRef?: string;
  summary: string;
  createdBy: "agent" | "system";
  artifactRefs: string[];
  retryCount: number;
  lastRun?: NodeRunRecord;
  scriptReview?: ScriptReviewState;
  position: {
    x: number;
    y: number;
  };
};

export type ChatAttachment = {
  attachmentId: string;
  name: string;
  path: string;
  sizeBytes: number;
  mimeType: string;
};

export type ChatMessage = {
  messageId: string;
  role: "user" | "assistant" | "system";
  content: string;
  attachments: ChatAttachment[];
  createdAt: string;
};

export type NodeGraph = {
  graphId: string;
  nodes: AgentNode[];
  edges: Array<{
    id: string;
    source: string;
    target: string;
  }>;
};

export type ProjectAttachmentRef = ChatAttachment & {
  originalPath: string;
  fileExists: boolean;
};

export type ToolSnapshotEntry = {
  toolId: string;
  name: string;
  version: string;
  enabled: boolean;
};

export type RunHistoryEntry = {
  runId: string;
  startedAt: string;
  completedAt?: string;
  status: "completed" | "failed" | "cancelled";
  summary: string;
  nodeRunIds?: string[];
  artifactRefs?: string[];
};

export type RunStatus = "running" | "completed" | "failed" | "cancelled";

export type ArtifactRef = {
  artifactId: string;
  path: string;
  sourceNodeId: string;
  createdAt: string;
};

export type NodeRunRecord = {
  nodeRunId: string;
  runId: string;
  nodeId: string;
  status: NodeStatus;
  startedAt: string;
  completedAt?: string;
  artifactRefs: string[];
  error?: string;
  errorCode?: string;
};

export type ScriptReviewState = {
  status: "not_reviewed" | "reviewing" | "approved" | "rejected";
  summary: string;
  permissions: string[];
};

export type AlitaProject = {
  schemaVersion: 1;
  projectId: string;
  name: string;
  path: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
  graph: NodeGraph | null;
  attachments: ProjectAttachmentRef[];
  modelRef: string | null;
  toolSnapshot: ToolSnapshotEntry[];
  runHistory: RunHistoryEntry[];
};

export type ProjectOpenWarning = {
  code: "missing_attachment";
  message: string;
  path: string;
};

export type ProjectOpenResult = {
  project: AlitaProject;
  warnings: ProjectOpenWarning[];
};

export type ModelSource = "manual" | "scan" | "imported";

export type ModelEntry = {
  modelId: string;
  name: string;
  path: string;
  source: ModelSource;
  runtime: "llama_cpp";
  fileExists: boolean;
  createdAt: string;
  updatedAt: string;
};

export type ToolSummary = {
  toolId: string;
  name: string;
  description: string;
  version: string;
  sourceType: string;
  license: string;
  runtime?: string;
  packageName?: string;
  packageSource?: string;
  upstreamUrl?: string;
  capabilities: string[];
  permissions: string[];
  enabled: boolean;
  valid: boolean;
  error?: string;
};

export type AppPreferences = {
  schemaVersion: 1;
  recentProjects: string[];
  modelDirectories: string[];
  modelStorageDir: string;
  models: ModelEntry[];
  defaultModelId: string | null;
  toolEnablement: Record<string, boolean>;
};
