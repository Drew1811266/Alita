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
  | "temporary_placeholder"
  | "planning"
  | "temporary_script";

export const SUPPORTED_NODE_TYPES = [
  "fixed_tool",
  "model",
  "output",
  "temporary_placeholder",
  "planning",
  "temporary_script",
] as const satisfies readonly NodeType[];

export type NodeEstimate = {
  durationMs?: number | null;
  cpu?: string | null;
  memory?: string | null;
  network?: string | null;
};

export type ResourceUsage = {
  durationMs?: number | null;
  cpu?: string | null;
  memory?: string | null;
  network?: string | null;
  [key: string]: string | number | boolean | null | undefined;
};

export type RuntimeNotice = {
  kind: string;
  message: string;
  actualDurationMs?: number | null;
};

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
  estimate?: NodeEstimate | null;
  resourceUsage?: ResourceUsage | null;
  runtimeNotice?: RuntimeNotice | null;
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

export type WebSourceReference = {
  ref?: string;
  title: string;
  url: string;
  snippet?: string;
  sourceType?: string | null;
  accepted?: boolean | null;
  rejectionReason?: string | null;
};

export type MessageSourceMetadata = {
  answerStatus?: "answered" | "no-reliable-sources";
  accepted?: WebSourceReference[];
  rejected?: WebSourceReference[];
  failure?: {
    kind: string;
    message: string;
    blocked?: boolean;
    removedCategories?: string[] | null;
  } | null;
};

export type ChatMessage = {
  messageId: string;
  role: "user" | "assistant" | "system";
  content: string;
  attachments: ChatAttachment[];
  sources?: WebSourceReference[];
  rejectedSources?: WebSourceReference[];
  sourceMetadata?: MessageSourceMetadata;
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
  metadata?: Record<string, unknown>;
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
  runtimeNotices?: Array<{
    nodeId: string;
    notice: RuntimeNotice;
  }>;
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
  riskLevel?: "low" | "medium" | "high";
  requiresApproval?: boolean;
  codePreview?: string | null;
  inputContract?: Record<string, unknown>;
  outputContract?: Record<string, unknown>;
  approvalFingerprint?: string | null;
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

export type ModelKind = "agent_llm" | "speech_to_text";

export type ModelRuntime = "llama_cpp" | "qwen_asr";

export type ModelPathKind = "file" | "directory";

export type ModelSource = "manual" | "scan" | "imported" | "recovered";

export type ModelAssignments = {
  agentChatModelId: string | null;
  speechToTextModelId: string | null;
};

export type ModelEntry = {
  modelId: string;
  name: string;
  path: string;
  modelKind: ModelKind;
  source: ModelSource;
  runtime: ModelRuntime;
  pathKind: ModelPathKind;
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
  schemaVersion: 2;
  recentProjects: string[];
  modelDirectories: string[];
  modelStorageDir: string;
  models: ModelEntry[];
  defaultModelId: string | null;
  modelAssignments: ModelAssignments;
  toolEnablement: Record<string, boolean>;
};

export type PreferencesView = {
  preferences: AppPreferences;
  tools: ToolSummary[];
};
