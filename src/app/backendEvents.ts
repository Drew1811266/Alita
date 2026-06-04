import type {
  AgentExecutionFailedPayload,
  AgentExecutionFinalPayload,
  AgentExecutionRepairProposedPayload,
  AgentPlanGraphCompileFailedPayload,
  AgentPlanGraphExecutionReadyPayload,
  BackendEvent,
  PlanningConfirmationChoiceId,
  PlanningConfirmationSubmitChoice,
  PlanningCheckpointRecord,
  ResearchChoiceId,
  ResearchChoicePayload,
} from "../shared/events";
import type {
  AgentNode,
  ArtifactRef,
  ChatAttachment,
  ChatMessage,
  NodeGraph,
  RuntimeNotice,
  RunHistoryEntry,
} from "../shared/types";

export type {
  AgentExecutionCompletedPayload,
  AgentExecutionFailedPayload,
  AgentExecutionFinalPayload,
  AgentExecutionInterruptedPayload,
  AgentExecutionRepairProposedPayload,
  AgentExecutionStartedPayload,
  AgentExecutionVerifyCompletedPayload,
  AgentPlanGraphCompileFailedPayload,
  AgentPlanGraphExecutionReadyPayload,
} from "../shared/events";

export type AgentCompileStatus =
  | "idle"
  | "compiling"
  | "compiled"
  | "reviewed"
  | "execution_ready"
  | "failed";

export type BackendEventState = {
  messages: ChatMessage[];
  graph: NodeGraph | null;
  dirty: boolean;
  pendingResearchChoice?: PendingResearchChoice | null;
  pendingGraphOverwriteChoice?: PendingGraphOverwriteChoice | null;
  pendingPlanningChoice?: PendingPlanningChoice | null;
  planningCheckpoints?: PlanningCheckpointRecord[];
  activeRunId?: string | null;
  runHistory?: RunHistoryEntry[];
  pendingRuntimeNotices?: PendingRuntimeNotice[];
  artifacts?: ArtifactRef[];
  agentCompileStatus?: AgentCompileStatus;
  agentExecutionReadySummary?: AgentPlanGraphExecutionReadyPayload | null;
  agentCompileFailure?: AgentPlanGraphCompileFailedPayload | null;
  activeAgentExecutionFlow?: ActiveAgentExecutionFlow | null;
};

export type ResearchChoiceSubmitPayload = {
  taskId: string;
  projectPath?: string;
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

export type PendingPlanningConfirmationChoice = Extract<
  BackendEvent,
  { type: "planning.confirmation_required" }
>["payload"];

export type PendingPlanningClarificationChoice = Extract<
  BackendEvent,
  { type: "planning.clarification_required" }
>["payload"];

export type PendingPlanningChoice =
  | PendingPlanningConfirmationChoice
  | PendingPlanningClarificationChoice;

export type PlanningClarificationSubmitChoice = {
  kind: "planning.clarification";
  runId: string;
  threadId: string;
  answer: string;
};

type PendingRuntimeNotice = {
  runId: string;
  nodeId: string;
  notice: RuntimeNotice;
};

const LEGACY_GRAPH_BLOCKED_MESSAGE =
  "Legacy graph fallback was blocked. The Agent must produce the task graph through deep planning.";

const DEEP_AGENT_PRODUCT_PATH_BLOCKED_MESSAGE =
  "Deep Agent planning did not reach a valid terminal state, and legacy graph fallback is blocked.";

type BlockedTaskFailureSuppression = {
  runId: string;
  taskId: string;
  errorCode: "legacy_graph_blocked" | "deep_agent_product_path_incomplete";
};

export type ActiveAgentExecutionFlow = {
  runId: string;
  taskId: string;
};

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

export function toPlanningConfirmationSubmitChoice(
  pendingChoice: PendingPlanningConfirmationChoice,
  choiceId: PlanningConfirmationChoiceId,
  revisionInstructions: string[] = [],
): PlanningConfirmationSubmitChoice {
  return {
    ...pendingChoice.pendingChoice,
    kind: "planning.confirmation",
    decision: choiceId,
    revisionInstructions,
  };
}

export function toPlanningClarificationSubmitChoice(
  pendingChoice: PendingPlanningClarificationChoice,
  answer: string,
): PlanningClarificationSubmitChoice {
  return {
    kind: "planning.clarification",
    runId: pendingChoice.runId,
    threadId: pendingChoice.threadId,
    answer: answer.trim(),
  };
}

export function reduceBackendEvents(
  state: BackendEventState,
  events: BackendEvent[],
  createAssistantMessage: (content: string) => ChatMessage,
  submittedPayload?: ResearchChoiceSubmitPayload,
): BackendEventState {
  let blockedTaskFailureSuppression: BlockedTaskFailureSuppression | null =
    null;
  let activeAgentExecutionFlow: ActiveAgentExecutionFlow | null =
    state.activeAgentExecutionFlow ?? null;

  return events.reduce<BackendEventState>((current, event) => {
    const taskFailureSuppression = blockedTaskFailureSuppression;
    blockedTaskFailureSuppression = null;

    if (event.type === "run.started") {
      return {
        ...current,
        activeRunId: event.payload.runId,
        runHistory: appendRunHistory(current, {
          runId: event.payload.runId,
          startedAt: event.payload.startedAt,
          status: "running",
          summary: "流程执行中。",
          nodeRunIds: [],
          artifactRefs: [],
        }),
        dirty: true,
      };
    }

    if (event.type === "run.cancelled") {
      const existingRun = findRunHistoryEntry(current, event.payload.runId);
      const runtimeNotices = collectRuntimeNoticesForRun(
        current,
        event.payload.runId,
      );
      return {
        ...current,
        activeRunId: null,
        pendingRuntimeNotices: filterPendingRuntimeNotices(
          current,
          event.payload.runId,
        ),
        runHistory: appendRunHistory(current, {
          runId: event.payload.runId,
          startedAt: existingRun?.startedAt ?? event.payload.completedAt,
          completedAt: event.payload.completedAt,
          status: "cancelled",
          summary: "流程已停止。",
          nodeRunIds: existingRun?.nodeRunIds ?? [],
          artifactRefs: existingRun?.artifactRefs ?? [],
          ...(runtimeNotices.length > 0 ? { runtimeNotices } : {}),
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
        pendingPlanningChoice: null,
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
        pendingPlanningChoice: null,
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
        pendingPlanningChoice: null,
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

    if (event.type === "planning.stage_changed") {
      return {
        ...current,
        dirty: true,
      };
    }

    if (event.type === "planning.checkpoint_recorded") {
      return {
        ...current,
        planningCheckpoints: [
          ...(current.planningCheckpoints ?? []),
          event.payload.checkpoint,
        ],
        dirty: true,
      };
    }

    if (event.type === "planning.confirmation_required") {
      return {
        ...current,
        messages: [
          ...current.messages,
          createAssistantMessage(formatPlanningConfirmationPrompt(event.payload)),
        ],
        pendingResearchChoice: null,
        pendingGraphOverwriteChoice: null,
        pendingPlanningChoice: event.payload,
        dirty: true,
      };
    }

    if (event.type === "planning.confirmed") {
      return {
        ...current,
        messages: [
          ...current.messages,
          createAssistantMessage("规划已确认，正在编译执行准备。"),
        ],
        pendingResearchChoice: null,
        pendingGraphOverwriteChoice: null,
        pendingPlanningChoice: null,
        dirty: true,
      };
    }

    if (event.type === "agent_plan_graph.compile_started") {
      return {
        ...current,
        agentCompileStatus: "compiling",
        agentExecutionReadySummary: null,
        agentCompileFailure: null,
        dirty: true,
      };
    }

    if (event.type === "agent_plan_graph.compiled") {
      return {
        ...current,
        agentCompileStatus: "compiled",
        dirty: true,
      };
    }

    if (event.type === "agent_plan_graph.compile_review_completed") {
      return {
        ...current,
        agentCompileStatus: "reviewed",
        dirty: true,
      };
    }

    if (event.type === "agent_plan_graph.execution_ready") {
      return {
        ...current,
        agentCompileStatus: "execution_ready",
        agentExecutionReadySummary: event.payload,
        agentCompileFailure: null,
        dirty: true,
      };
    }

    if (event.type === "agent_plan_graph.compile_failed") {
      return {
        ...current,
        messages: [
          ...current.messages,
          createAssistantMessage(
            formatAgentPlanGraphCompileFailure(event.payload),
          ),
        ],
        pendingPlanningChoice: null,
        agentCompileStatus: "failed",
        agentExecutionReadySummary: null,
        agentCompileFailure: event.payload,
        dirty: true,
      };
    }

    if (event.type === "agent_execution.started") {
      activeAgentExecutionFlow = {
        runId: event.payload.runId,
        taskId: event.payload.taskId,
      };

      return {
        ...current,
        activeAgentExecutionFlow,
        messages: [
          ...current.messages,
          createAssistantMessage("Agent 开始执行已确认的计划。"),
        ],
        dirty: true,
      };
    }

    if (event.type === "agent_execution.completed") {
      return {
        ...current,
        dirty: true,
      };
    }

    if (event.type === "agent_execution.failed") {
      const isExceptionFailure = isAgentExecutionExceptionFailure(event.payload);
      const hasRepairPath =
        "recoveryActions" in event.payload &&
        event.payload.recoveryActions.length > 0;
      const isMatchingActiveFlow = isMatchingAgentExecutionFlow(
        activeAgentExecutionFlow,
        event.payload.taskId,
        event.payload.runId,
      );
      const shouldShowFailure =
        isExceptionFailure || !isMatchingActiveFlow || !hasRepairPath;
      const shouldClearActiveFlow =
        isExceptionFailure || (isMatchingActiveFlow && !hasRepairPath);
      if (shouldClearActiveFlow) {
        activeAgentExecutionFlow = null;
      }

      return {
        ...current,
        activeAgentExecutionFlow,
        messages: shouldShowFailure
          ? [
              ...current.messages,
              createAssistantMessage(formatAgentExecutionFailure(event.payload)),
            ]
          : current.messages,
        dirty: true,
      };
    }

    if (event.type === "agent_execution.interrupted") {
      if (
        isMatchingAgentExecutionFlow(
          activeAgentExecutionFlow,
          event.payload.taskId,
          event.payload.runId,
        )
      ) {
        activeAgentExecutionFlow = null;
      }

      return {
        ...current,
        activeAgentExecutionFlow,
        messages: [
          ...current.messages,
          createAssistantMessage(
            `Agent 执行已中断：${event.payload.reason || "unknown"}`,
          ),
        ],
        dirty: true,
      };
    }

    if (event.type === "agent_execution.verify_completed") {
      return {
        ...current,
        dirty: true,
      };
    }

    if (event.type === "agent_execution.repair_proposed") {
      if (
        isMatchingAgentExecutionFlow(
          activeAgentExecutionFlow,
          event.payload.taskId,
          event.payload.runId,
        )
      ) {
        activeAgentExecutionFlow = null;
      }

      return {
        ...current,
        activeAgentExecutionFlow,
        messages: [
          ...current.messages,
          createAssistantMessage(formatAgentExecutionRepair(event.payload)),
        ],
        dirty: true,
      };
    }

    if (event.type === "agent_execution.final") {
      if (
        isMatchingAgentExecutionFlow(
          activeAgentExecutionFlow,
          event.payload.taskId,
          event.payload.runId,
        )
      ) {
        activeAgentExecutionFlow = null;
      }

      return {
        ...current,
        activeAgentExecutionFlow,
        messages: [
          ...current.messages,
          createAssistantMessage(formatAgentExecutionFinal(event.payload)),
        ],
        dirty: true,
      };
    }

    if (event.type === "planning.cancelled") {
      return {
        ...current,
        messages: [
          ...current.messages,
          createAssistantMessage("规划已取消。"),
        ],
        pendingResearchChoice: null,
        pendingGraphOverwriteChoice: null,
        pendingPlanningChoice: null,
        dirty: true,
      };
    }

    if (event.type === "planning.interrupted") {
      if (event.payload.kind === "planning.confirmation") {
        if (
          current.pendingPlanningChoice &&
          current.pendingPlanningChoice.kind === "planning.confirmation" &&
          isSamePlanningConfirmationChoice(
            current.pendingPlanningChoice,
            event.payload,
          )
        ) {
          return {
            ...current,
            dirty: true,
          };
        }

        return {
          ...current,
          messages: [
            ...current.messages,
            createAssistantMessage(formatPlanningConfirmationPrompt(event.payload)),
          ],
          pendingResearchChoice: null,
          pendingGraphOverwriteChoice: null,
          pendingPlanningChoice: event.payload,
          dirty: true,
        };
      }

      if (lastMessageContent(current) === event.payload.prompt) {
        return {
          ...current,
          pendingPlanningChoice: event.payload,
          dirty: true,
        };
      }

      return {
        ...current,
        messages: [
          ...current.messages,
          createAssistantMessage(event.payload.prompt),
        ],
        pendingResearchChoice: null,
        pendingGraphOverwriteChoice: null,
        pendingPlanningChoice: event.payload,
        dirty: true,
      };
    }

    if (
      event.type === "planning.resumed" ||
      event.type === "planning.revision_requested" ||
      event.type === "planning.revision_started" ||
      event.type === "planning.revision_completed" ||
      event.type === "planning.revision_exhausted"
    ) {
      return {
        ...current,
        pendingPlanningChoice:
          event.type === "planning.resumed" ? null : current.pendingPlanningChoice,
        dirty: true,
      };
    }

    if (event.type === "planning.progress") {
      return {
        ...current,
        messages: [
          ...current.messages,
          createAssistantMessage(formatPlanningProgress(event.payload)),
        ],
        pendingResearchChoice: null,
        pendingGraphOverwriteChoice: null,
        pendingPlanningChoice: null,
        dirty: true,
      };
    }

    if (event.type === "planning.clarification_required") {
      return {
        ...current,
        messages: [
          ...current.messages,
          createAssistantMessage(event.payload.prompt),
        ],
        pendingResearchChoice: null,
        pendingGraphOverwriteChoice: null,
        pendingPlanningChoice: event.payload,
        dirty: true,
      };
    }

    if (event.type === "planning.failed") {
      return {
        ...current,
        messages: [
          ...current.messages,
          createAssistantMessage(formatPlanningFailure(event.payload)),
        ],
        pendingResearchChoice: null,
        pendingGraphOverwriteChoice: null,
        pendingPlanningChoice: null,
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
        pendingPlanningChoice: null,
        agentCompileStatus: "idle",
        agentExecutionReadySummary: null,
        agentCompileFailure: null,
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
        pendingPlanningChoice: null,
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
        pendingPlanningChoice: null,
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
        pendingRuntimeNotices: appendPendingRuntimeNotice(
          updated,
          event.payload.nodeId,
          event.payload.notice,
        ),
        runHistory: appendRuntimeNoticeToRunHistory(
          updated,
          event.payload.nodeId,
          event.payload.notice,
        ),
        dirty: true,
      };
    }

    if (event.type === "permission.required") {
      const updated = updateNode(current, event.payload.nodeId, {
        status: "needs_permission",
        scriptReview: {
          status: "reviewing",
          summary: "节点需要授权后才能继续执行。",
          permissions: event.payload.permissions,
        },
      });

      return {
        ...updated,
        messages: [
          ...updated.messages,
          createAssistantMessage(
            `Node ${event.payload.nodeId} needs permission before it can run.\nPermissions: ${event.payload.permissions.join(", ")}`,
          ),
        ],
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

    if (event.type === "graph.patch_suggested") {
      const operations = event.payload.operations
        .map((operation) => `${operation.op}:${operation.node_id}`)
        .join("、");
      return {
        ...current,
        messages: [
          ...current.messages,
          createAssistantMessage(
            `建议修复：${event.payload.reason}（${operations}）`,
          ),
        ],
        dirty: true,
      };
    }

    if (event.type === "runtime.legacy_graph_blocked") {
      blockedTaskFailureSuppression = {
        runId: event.payload.runId,
        taskId: event.payload.taskId,
        errorCode: "legacy_graph_blocked",
      };

      return {
        ...current,
        activeRunId: event.payload.runId,
        messages: [
          ...current.messages,
          createAssistantMessage(LEGACY_GRAPH_BLOCKED_MESSAGE),
        ],
        pendingResearchChoice: null,
        pendingGraphOverwriteChoice: null,
        pendingPlanningChoice: null,
        agentCompileStatus: "failed",
        agentExecutionReadySummary: null,
        agentCompileFailure: null,
        dirty: true,
      };
    }

    if (event.type === "runtime.deep_agent_product_path_blocked") {
      blockedTaskFailureSuppression = {
        runId: event.payload.runId,
        taskId: event.payload.taskId,
        errorCode: "deep_agent_product_path_incomplete",
      };

      return {
        ...current,
        activeRunId: event.payload.runId,
        messages: [
          ...current.messages,
          createAssistantMessage(DEEP_AGENT_PRODUCT_PATH_BLOCKED_MESSAGE),
        ],
        pendingResearchChoice: null,
        pendingGraphOverwriteChoice: null,
        pendingPlanningChoice: null,
        agentCompileStatus: "failed",
        agentExecutionReadySummary: null,
        agentCompileFailure: null,
        dirty: true,
      };
    }

    if (event.type === "task.completed") {
      const runId = event.payload.runId ?? current.activeRunId;
      const existingRun = runId ? findRunHistoryEntry(current, runId) : null;
      const artifactRefs = collectArtifactRefs(current, existingRun);
      const runtimeNotices = runId
        ? collectRuntimeNoticesForRun(current, runId)
        : [];
      const shouldSuppressMessage = isMatchingAgentExecutionFlow(
        activeAgentExecutionFlow,
        event.payload.taskId,
        runId,
      );
      return {
        ...current,
        activeRunId: runId ? null : current.activeRunId,
        pendingRuntimeNotices: runId
          ? filterPendingRuntimeNotices(current, runId)
          : current.pendingRuntimeNotices,
        runHistory: runId
          ? appendRunHistory(current, {
              runId,
              startedAt: existingRun?.startedAt ?? new Date(0).toISOString(),
              completedAt: new Date().toISOString(),
              status: "completed",
              summary: "流程执行完成。",
              nodeRunIds: existingRun?.nodeRunIds ?? [],
              artifactRefs,
              ...(runtimeNotices.length > 0 ? { runtimeNotices } : {}),
            })
          : current.runHistory,
        messages: shouldSuppressMessage
          ? current.messages
          : [...current.messages, createAssistantMessage("流程执行完成。")],
        dirty: true,
      };
    }

    if (event.type === "task.failed") {
      const runId = event.payload.runId ?? current.activeRunId;
      const existingRun = runId ? findRunHistoryEntry(current, runId) : null;
      const artifactRefs = collectArtifactRefs(current, existingRun);
      const runtimeNotices = runId
        ? collectRuntimeNoticesForRun(current, runId)
        : [];
      const messages = shouldSuppressGenericTaskFailureMessage(
        taskFailureSuppression,
        event,
      ) ||
        isMatchingAgentExecutionFlow(
          activeAgentExecutionFlow,
          event.payload.taskId,
          runId,
        )
        ? current.messages
        : [
            ...current.messages,
            createAssistantMessage(`流程执行失败：${event.payload.error}`),
          ];
      return {
        ...current,
        activeRunId: runId ? null : current.activeRunId,
        pendingRuntimeNotices: runId
          ? filterPendingRuntimeNotices(current, runId)
          : current.pendingRuntimeNotices,
        runHistory: runId
          ? appendRunHistory(current, {
              runId,
              startedAt: existingRun?.startedAt ?? new Date(0).toISOString(),
              completedAt: new Date().toISOString(),
              status: "failed",
              summary: event.payload.error,
              nodeRunIds: existingRun?.nodeRunIds ?? [],
              artifactRefs,
              ...(runtimeNotices.length > 0 ? { runtimeNotices } : {}),
            })
          : current.runHistory,
        messages,
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

function formatPlanningConfirmationPrompt(
  payload: PendingPlanningConfirmationChoice,
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

function formatPlanningProgress(
  payload: Extract<BackendEvent, { type: "planning.progress" }>["payload"],
): string {
  return `Planning progress ${payload.sequence}/${payload.total}: ${payload.label}\n${payload.summary}`;
}

function formatPlanningFailure(
  payload: Extract<BackendEvent, { type: "planning.failed" }>["payload"],
): string {
  return `规划失败：${payload.message ?? payload.reason}`;
}

function formatAgentPlanGraphCompileFailure(
  payload: AgentPlanGraphCompileFailedPayload,
): string {
  return `执行准备编译失败：${payload.reason}`;
}

function formatAgentExecutionFailure(
  payload: AgentExecutionFailedPayload,
): string {
  const reason =
    "errorCode" in payload
      ? payload.errorCode
      : payload.reason || "unknown";
  const issueMessage =
    "issues" in payload ? getFirstIssueMessage(payload.issues) : null;
  return issueMessage
    ? `Agent 执行失败：${reason}\n${issueMessage}`
    : `Agent 执行失败：${reason}`;
}

function formatAgentExecutionRepair(
  payload: AgentExecutionRepairProposedPayload,
): string {
  const actionCount =
    payload.actions.length > 0 ? `（${payload.actions.length} 个动作）` : "";
  return `Agent 已提出执行修复方案。${actionCount}`;
}

function formatAgentExecutionFinal(
  payload: AgentExecutionFinalPayload,
): string {
  const artifactLine =
    payload.artifactRefs.length > 0
      ? `\n产物：${payload.artifactRefs.join("、")}`
      : "";
  return `Agent 执行完成并通过验证。${artifactLine}`;
}

function isAgentExecutionExceptionFailure(
  payload: AgentExecutionFailedPayload,
): boolean {
  return "errorCode" in payload || !("artifactRefs" in payload);
}

function isMatchingAgentExecutionFlow(
  flow: ActiveAgentExecutionFlow | null,
  taskId: string,
  runId: string | null | undefined,
): boolean {
  return Boolean(flow && flow.taskId === taskId && flow.runId === runId);
}

function getFirstIssueMessage(issues: unknown[]): string | null {
  const firstIssue = issues[0];
  if (
    typeof firstIssue === "object" &&
    firstIssue !== null &&
    "message" in firstIssue &&
    typeof firstIssue.message === "string"
  ) {
    return firstIssue.message;
  }

  return null;
}

function shouldSuppressGenericTaskFailureMessage(
  suppression: BlockedTaskFailureSuppression | null,
  event: Extract<BackendEvent, { type: "task.failed" }>,
): boolean {
  if (!suppression) {
    return false;
  }

  return (
    event.payload.runId === suppression.runId &&
    event.payload.taskId === suppression.taskId &&
    event.payload.errorCode === suppression.errorCode
  );
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

function findRunHistoryEntry(
  state: BackendEventState,
  runId: string,
): RunHistoryEntry | undefined {
  return state.runHistory?.find((entry) => entry.runId === runId);
}

function collectArtifactRefs(
  state: BackendEventState,
  existingRun: RunHistoryEntry | null | undefined,
): string[] {
  const currentArtifactRefs = state.artifacts?.map((artifact) => artifact.path);
  return currentArtifactRefs && currentArtifactRefs.length > 0
    ? currentArtifactRefs
    : existingRun?.artifactRefs ?? [];
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

function appendPendingRuntimeNotice(
  state: BackendEventState,
  nodeId: string,
  notice: RuntimeNotice,
): PendingRuntimeNotice[] | undefined {
  if (!state.activeRunId) {
    return state.pendingRuntimeNotices;
  }
  if (
    state.runHistory?.some((entry) => entry.runId === state.activeRunId)
  ) {
    return state.pendingRuntimeNotices;
  }

  return [
    ...(state.pendingRuntimeNotices ?? []),
    {
      runId: state.activeRunId,
      nodeId,
      notice,
    },
  ];
}

function collectRuntimeNoticesForRun(
  state: BackendEventState,
  runId: string,
): NonNullable<RunHistoryEntry["runtimeNotices"]> {
  const historyNotices =
    state.runHistory?.find((entry) => entry.runId === runId)?.runtimeNotices ??
    [];
  const pendingNotices =
    state.pendingRuntimeNotices
      ?.filter((entry) => entry.runId === runId)
      .map(({ nodeId, notice }) => ({ nodeId, notice })) ?? [];

  return [...historyNotices, ...pendingNotices];
}

function filterPendingRuntimeNotices(
  state: BackendEventState,
  runId: string,
): PendingRuntimeNotice[] | undefined {
  return state.pendingRuntimeNotices?.filter((entry) => entry.runId !== runId);
}

function isSamePlanningConfirmationChoice(
  left: PendingPlanningConfirmationChoice,
  right: PendingPlanningConfirmationChoice,
): boolean {
  return (
    left.runId === right.runId &&
    left.threadId === right.threadId &&
    left.graphId === right.graphId
  );
}

function lastMessageContent(state: BackendEventState): string | null {
  return state.messages[state.messages.length - 1]?.content ?? null;
}
