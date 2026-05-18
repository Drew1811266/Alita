import type {
  BackendEvent,
  ResearchChoiceId,
  ResearchChoicePayload,
} from "../shared/events";
import type {
  AgentNode,
  ArtifactRef,
  ChatAttachment,
  ChatMessage,
  NodeGraph,
  RunHistoryEntry,
} from "../shared/types";

export type BackendEventState = {
  messages: ChatMessage[];
  graph: NodeGraph | null;
  dirty: boolean;
  pendingResearchChoice?: PendingResearchChoice | null;
  activeRunId?: string | null;
  runHistory?: RunHistoryEntry[];
  artifacts?: ArtifactRef[];
};

export type ResearchChoiceSubmitPayload = {
  taskId: string;
  content: string;
  attachments: ChatAttachment[];
  inquiryChoice?: ResearchChoiceId;
};

export type PendingResearchChoice = ResearchChoicePayload & {
  submittedPayload?: ResearchChoiceSubmitPayload;
};

export function reduceBackendEvents(
  state: BackendEventState,
  events: BackendEvent[],
  createAssistantMessage: (content: string) => ChatMessage,
  submittedPayload?: ResearchChoiceSubmitPayload,
): BackendEventState {
  return events.reduce<BackendEventState>((current, event) => {
    if (event.type === "run.started") {
      return {
        ...current,
        activeRunId: event.payload.runId,
        dirty: true,
      };
    }

    if (event.type === "run.cancelled") {
      return {
        ...current,
        activeRunId: null,
        runHistory: appendRunHistory(current, {
          runId: event.payload.runId,
          startedAt: event.payload.completedAt,
          completedAt: event.payload.completedAt,
          status: "cancelled",
          summary: "流程已停止。",
          nodeRunIds: [],
          artifactRefs: [],
        }),
        messages: [...current.messages, createAssistantMessage("流程已停止。")],
        dirty: true,
      };
    }

    if (event.type === "message.started") {
      return {
        ...current,
        messages: [...current.messages, event.payload.message],
        pendingResearchChoice: null,
        dirty: true,
      };
    }

    if (event.type === "message.delta") {
      return {
        ...current,
        messages: current.messages.map((message) =>
          message.messageId === event.payload.messageId
            ? { ...message, content: `${message.content}${event.payload.delta}` }
            : message,
        ),
        dirty: true,
      };
    }

    if (event.type === "message.completed") {
      return {
        ...current,
        dirty: true,
      };
    }

    if (event.type === "message.created") {
      return {
        ...current,
        messages: [...current.messages, event.payload.message],
        pendingResearchChoice: null,
        dirty: true,
      };
    }

    if (event.type === "input.required") {
      return {
        ...current,
        messages: [
          ...current.messages,
          createAssistantMessage(event.payload.prompt),
        ],
        pendingResearchChoice: null,
        dirty: true,
      };
    }

    if (event.type === "research.choice_required") {
      return {
        ...current,
        messages: [
          ...current.messages,
          createAssistantMessage(formatResearchChoicePrompt(event.payload)),
        ],
        pendingResearchChoice: {
          ...event.payload,
          ...(submittedPayload ? { submittedPayload } : {}),
        },
        dirty: true,
      };
    }

    if (event.type === "node_graph.created") {
      return {
        ...current,
        graph: event.payload.graph,
        messages: [
          ...current.messages,
          createAssistantMessage("已生成右侧工具流程。"),
        ],
        pendingResearchChoice: null,
        dirty: true,
      };
    }

    if (event.type === "node.running") {
      return updateNode(current, event.payload.nodeId, { status: "running" });
    }

    if (event.type === "node.completed") {
      return updateNode(current, event.payload.nodeId, {
        status: "completed",
        artifactRefs: event.payload.artifactRefs,
      });
    }

    if (event.type === "node.failed") {
      const node = current.graph?.nodes.find(
        (candidate) => candidate.nodeId === event.payload.nodeId,
      );
      const failedAt = new Date().toISOString();
      const lastRun =
        event.payload.error || event.payload.errorCode
          ? {
              nodeRunId:
                node?.lastRun?.nodeRunId ?? `${event.payload.nodeId}:failed`,
              runId:
                event.payload.runId ??
                current.activeRunId ??
                node?.lastRun?.runId ??
                "",
              nodeId: event.payload.nodeId,
              status: "failed" as const,
              startedAt: node?.lastRun?.startedAt ?? failedAt,
              completedAt: failedAt,
              artifactRefs: node?.lastRun?.artifactRefs ?? [],
              error: event.payload.error ?? node?.lastRun?.error,
              errorCode: event.payload.errorCode ?? node?.lastRun?.errorCode,
            }
          : node?.lastRun;

      return updateNode(current, event.payload.nodeId, {
        status: "failed",
        ...(lastRun ? { lastRun } : {}),
      });
    }

    if (event.type === "node.skipped") {
      return updateNode(current, event.payload.nodeId, { status: "skipped" });
    }

    if (event.type === "node.run_recorded") {
      return updateNode(current, event.payload.record.nodeId, {
        status: event.payload.record.status,
        artifactRefs: event.payload.record.artifactRefs,
        lastRun: event.payload.record,
      });
    }

    if (event.type === "artifact.created") {
      const artifact: ArtifactRef = {
        artifactId: event.payload.artifactId,
        path: event.payload.path,
        sourceNodeId: event.payload.sourceNodeId ?? "",
        createdAt: event.payload.createdAt ?? new Date(0).toISOString(),
      };

      return {
        ...current,
        artifacts: [...(current.artifacts ?? []), artifact],
        messages: [
          ...current.messages,
          createAssistantMessage(`已生成产物：${event.payload.path}`),
        ],
        dirty: true,
      };
    }

    if (event.type === "task.completed") {
      const runId = event.payload.runId ?? current.activeRunId;
      return {
        ...current,
        activeRunId: runId ? null : current.activeRunId,
        runHistory: runId
          ? appendRunHistory(current, {
              runId,
              startedAt: new Date(0).toISOString(),
              completedAt: new Date().toISOString(),
              status: "completed",
              summary: "流程执行完成。",
              nodeRunIds: [],
              artifactRefs: current.artifacts?.map((artifact) => artifact.path) ?? [],
            })
          : current.runHistory,
        messages: [...current.messages, createAssistantMessage("流程执行完成。")],
        dirty: true,
      };
    }

    if (event.type === "task.failed") {
      const runId = event.payload.runId ?? current.activeRunId;
      return {
        ...current,
        activeRunId: runId ? null : current.activeRunId,
        runHistory: runId
          ? appendRunHistory(current, {
              runId,
              startedAt: new Date(0).toISOString(),
              completedAt: new Date().toISOString(),
              status: "failed",
              summary: event.payload.error,
              nodeRunIds: [],
              artifactRefs: current.artifacts?.map((artifact) => artifact.path) ?? [],
            })
          : current.runHistory,
        messages: [
          ...current.messages,
          createAssistantMessage(`流程执行失败：${event.payload.error}`),
        ],
        dirty: true,
      };
    }

    return current;
  }, state);
}

function formatResearchChoicePrompt(
  payload: Extract<BackendEvent, { type: "research.choice_required" }>["payload"],
): string {
  const choices = payload.choices
    .map((choice, index) => {
      const description = choice.description ? ` - ${choice.description}` : "";
      return `${index + 1}. ${choice.label}${description}`;
    })
    .join("\n");
  return `${payload.prompt}\n\n${choices}`;
}

function updateNode(
  state: BackendEventState,
  nodeId: string,
  patch: Partial<AgentNode>,
): BackendEventState {
  if (!state.graph) {
    return state;
  }

  return {
    ...state,
    graph: {
      ...state.graph,
      nodes: state.graph.nodes.map((node) =>
        node.nodeId === nodeId ? { ...node, ...patch } : node,
      ),
    },
    dirty: true,
  };
}

function appendRunHistory(
  state: BackendEventState,
  entry: RunHistoryEntry,
): RunHistoryEntry[] {
  return [
    ...(state.runHistory ?? []).filter((run) => run.runId !== entry.runId),
    entry,
  ];
}
