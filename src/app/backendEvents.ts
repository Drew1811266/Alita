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
  pendingGraphOverwriteChoice?: PendingGraphOverwriteChoice | null;
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

export type PendingGraphOverwriteChoice = Extract<
  BackendEvent,
  { type: "graph.overwrite_confirmation_required" }
>["payload"];

export function toGraphOverwriteSubmitChoice(
  pendingChoice: PendingGraphOverwriteChoice,
  content: string,
): Record<string, unknown> {
  const normalized = content.trim().toLowerCase();
  const selectedChoiceId =
    normalized === "cancel" || normalized === "no"
      ? "cancel"
      : normalized === "confirm" ||
          normalized === "yes" ||
          normalized.includes("overwrite") ||
          normalized.includes("proceed")
        ? "confirm_overwrite"
        : pendingChoice.pendingChoice["id"];

  return {
    ...pendingChoice.pendingChoice,
    id: selectedChoiceId,
  };
}

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
        pendingGraphOverwriteChoice: null,
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
        messages: [
          ...current.messages,
          {
            ...event.payload.message,
            ...(event.payload.sources
              ? { sources: event.payload.sources }
              : {}),
            ...(event.payload.rejectedSources
              ? { rejectedSources: event.payload.rejectedSources }
              : {}),
            ...(event.payload.sourceMetadata
              ? { sourceMetadata: event.payload.sourceMetadata }
              : {}),
          },
        ],
        pendingResearchChoice: null,
        pendingGraphOverwriteChoice: null,
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
        pendingGraphOverwriteChoice: null,
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
        pendingGraphOverwriteChoice: null,
        dirty: true,
      };
    }

    if (event.type === "graph.replanned") {
      const summary =
        event.payload.summary ??
        `Graph replanned from ${event.payload.previousGraphId ?? "previous graph"} to ${event.payload.graph.graphId}.`;
      return {
        ...current,
        graph: event.payload.graph,
        messages: [...current.messages, createAssistantMessage(summary)],
        pendingResearchChoice: null,
        pendingGraphOverwriteChoice: null,
        dirty: true,
      };
    }

    if (event.type === "graph.overwrite_confirmation_required") {
      return {
        ...current,
        messages: [
          ...current.messages,
          createAssistantMessage(formatGraphOverwritePrompt(event.payload)),
        ],
        pendingResearchChoice: null,
        pendingGraphOverwriteChoice: event.payload,
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
      const node = current.graph?.nodes.find(
        (candidate) => candidate.nodeId === event.payload.record.nodeId,
      );
      const record =
        event.payload.record.status === "failed" &&
        node?.lastRun?.errorCode &&
        !event.payload.record.errorCode
          ? {
              ...event.payload.record,
              errorCode: node.lastRun.errorCode,
            }
          : event.payload.record;

      return updateNode(current, event.payload.record.nodeId, {
        status: record.status,
        artifactRefs: record.artifactRefs,
        lastRun: record,
      });
    }

    if (event.type === "node.needs_permission") {
      const updated = updateNode(current, event.payload.nodeId, {
        status: "needs_permission",
        ...(event.payload.scriptReview
          ? { scriptReview: event.payload.scriptReview }
          : {}),
      });

      return {
        ...updated,
        messages: [
          ...updated.messages,
          createAssistantMessage(formatPermissionPrompt(event.payload)),
        ],
        dirty: true,
      };
    }

    if (event.type === "node.runtime_notice") {
      const updated = updateNode(current, event.payload.nodeId, {
        runtimeNotice: event.payload.notice,
      });

      return {
        ...updated,
        runHistory: appendRuntimeNoticeToRunHistory(
          updated,
          event.payload.nodeId,
          event.payload.notice,
        ),
        dirty: true,
      };
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

    if (event.type === "research.completed") {
      const artifact =
        event.payload.reportArtifactId && event.payload.reportArtifactPath
          ? {
              artifactId: event.payload.reportArtifactId,
              path: event.payload.reportArtifactPath,
              sourceNodeId: "research-markdown-output",
              createdAt: new Date(0).toISOString(),
            }
          : null;
      const summary = event.payload.summary || "Research completed.";
      const reportLine = event.payload.reportArtifactPath
        ? `\n${event.payload.reportArtifactPath}`
        : "";
      const acceptedSources = event.payload.acceptedSources ?? [];
      const rejectedSources = event.payload.rejectedSources ?? [];
      const message = {
        ...createAssistantMessage(`${summary}${reportLine}`),
        sources: acceptedSources,
        rejectedSources,
        sourceMetadata: {
          answerStatus:
            acceptedSources.length > 0 ? "answered" : "no-reliable-sources",
          accepted: acceptedSources,
          rejected: rejectedSources,
        },
      } satisfies ChatMessage;
      const existingArtifacts = current.artifacts ?? [];
      const artifacts =
        artifact &&
        !existingArtifacts.some(
          (existing) =>
            existing.artifactId === artifact.artifactId ||
            existing.path === artifact.path,
        )
          ? [...existingArtifacts, artifact]
          : current.artifacts;

      return {
        ...current,
        artifacts,
        messages: [...current.messages, message],
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

function formatGraphOverwritePrompt(
  payload: PendingGraphOverwriteChoice,
): string {
  const choices = payload.choices
    .map((choice, index) => {
      const description = choice.description ? ` - ${choice.description}` : "";
      return `${index + 1}. ${choice.label}${description}`;
    })
    .join("\n");
  return `${payload.summary}\n\n${choices}`;
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

function formatPermissionPrompt(
  payload: Extract<BackendEvent, { type: "node.needs_permission" }>["payload"],
): string {
  const permissions =
    payload.permissions.length > 0 ? payload.permissions.join(", ") : "none";
  const summary = payload.scriptReview?.summary
    ? `\n${payload.scriptReview.summary}`
    : "";
  return `Node ${payload.nodeId} needs permission before it can run.\nPermissions: ${permissions}${summary}`;
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

function appendRuntimeNoticeToRunHistory(
  state: BackendEventState,
  nodeId: string,
  notice: NonNullable<AgentNode["runtimeNotice"]>,
): RunHistoryEntry[] | undefined {
  if (!state.activeRunId || !state.runHistory) {
    return state.runHistory;
  }

  return state.runHistory.map((entry) =>
    entry.runId === state.activeRunId
      ? {
          ...entry,
          runtimeNotices: [
            ...(entry.runtimeNotices ?? []),
            {
              nodeId,
              notice,
            },
          ],
        }
      : entry,
  );
}
