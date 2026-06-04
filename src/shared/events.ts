import type {
  AgentNode,
  AuthorityDecisionRecord,
  ChatMessage,
  MessageSourceMetadata,
  NodeGraph,
  NodeRunRecord,
  RecoveryActionRecord,
  RuntimeSpanRecord,
  RuntimeCheckpointRecord,
  RuntimeNotice,
  ScriptReviewState,
  WebSourceReference,
} from "./types";

export type ResearchChoiceId = "quick_answer" | "research_flow";

export type ResearchChoicePayload = {
  taskId: string;
  prompt: string;
  choices: Array<{
    id: ResearchChoiceId;
    label: string;
    description?: string;
  }>;
};

export type PlanningConfirmationChoiceId = "approve" | "revise" | "cancel";

export type PlanningConfirmationPendingChoice = {
  kind: "planning.confirmation";
  runId: string;
  threadId: string;
  graphId: string;
};

export type PlanningConfirmationSubmitChoice =
  PlanningConfirmationPendingChoice & {
    decision: PlanningConfirmationChoiceId;
    revisionInstructions: string[];
  };

export type PlanningConfirmationChoice = {
  id: PlanningConfirmationChoiceId;
  label: string;
  description?: string;
};

export type PlanningConfirmationRequiredPayload = {
  kind: "planning.confirmation";
  taskId: string;
  runId: string;
  threadId: string;
  graphId: string;
  summary: string;
  pendingChoice: PlanningConfirmationPendingChoice;
  choices: PlanningConfirmationChoice[];
};

export type PlanningClarificationPayload = {
  kind: "planning.clarification";
  taskId: string;
  runId: string;
  threadId: string;
  question: string;
  missingInputs: string[];
  prompt: string;
};

export type PlanningCheckpointRecord = {
  runId: string;
  threadId: string;
  checkpointId: string;
  stage: string;
  node?: string | null;
  revisionCount: number;
  hasPlanDraft: boolean;
  hasCompiledGraph: boolean;
  hasAgentCompiledGraph: boolean;
  executionReady: boolean;
  createdAt: string;
};

export type PlanningTerminalPayload = {
  taskId: string;
  runId: string;
  threadId: string;
  graphId: string;
};

export type AgentPlanGraphCompileStartedPayload = {
  taskId: string;
  runId: string;
  threadId: string;
  graphId: string;
};

export type AgentPlanGraphCompiledPayload =
  AgentPlanGraphCompileStartedPayload & {
    compileId: string;
  };

export type AgentPlanGraphCompileReviewCompletedPayload =
  AgentPlanGraphCompiledPayload;

export type AgentPlanGraphExecutionReadyPayload =
  AgentPlanGraphCompiledPayload & {
    nodeCount: number;
    edgeCount: number;
    toolNodeCount: number;
    modelNodeCount: number;
    permissionsRequired: string[];
    expectedArtifacts: string[];
  };

export type AgentPlanGraphCompileFailedPayload =
  AgentPlanGraphCompileStartedPayload & {
    compileId?: string;
    reason: string;
    issues: Array<{
      code: string;
      message: string;
      nodeId?: string;
      severity: "error" | "warning";
    }>;
    unsupportedCapabilities: string[];
    missingBindings: string[];
  };

export type AgentExecutionBasePayload = {
  taskId: string;
  runId: string;
  threadId: string;
  compileId: string;
  graphId: string;
};

export type AgentExecutionStartedPayload = AgentExecutionBasePayload;

export type AgentExecutionSummaryFields = {
  artifactRefs: string[];
  completedNodeIds: string[];
  checkpointIds: string[];
  recoveryActions: unknown[];
};

export type AgentExecutionCompletedPayload = AgentExecutionBasePayload &
  AgentExecutionSummaryFields & {
    status: "completed";
    finalMessage?: string;
  };

export type AgentExecutionFailedSummaryPayload = AgentExecutionBasePayload &
  AgentExecutionSummaryFields & {
    status: "failed";
    failedNodeId?: string;
    reason: string;
    finalMessage?: string;
  };

export type AgentExecutionFailedExceptionPayload = Omit<
  AgentExecutionBasePayload,
  "compileId"
> & {
  compileId?: string;
  status: "failed";
  reason: "execution_bridge_failed";
  errorCode: string;
  issues: unknown[];
};

export type AgentExecutionFailedPayload =
  | AgentExecutionFailedSummaryPayload
  | AgentExecutionFailedExceptionPayload;

export type AgentExecutionInterruptedPayload = AgentExecutionBasePayload &
  AgentExecutionSummaryFields & {
    status: "interrupted";
    reason: string;
    failedNodeId?: string;
    finalMessage?: string;
  };

export type AgentExecutionVerifyCompletedPayload = AgentExecutionBasePayload & {
  status: "approved" | "failed" | "needs_repair";
  isValid: boolean;
  issues: unknown[];
  finalArtifacts: string[];
  repairRequired: boolean;
};

export type AgentExecutionRepairProposedPayload = AgentExecutionBasePayload &
  AgentExecutionSummaryFields & {
    status: "failed" | "interrupted";
    actions: unknown[];
    issues: unknown[];
    reason: string;
    failedNodeId?: string;
    finalMessage?: string;
  };

export type AgentExecutionFinalPayload = AgentExecutionBasePayload &
  AgentExecutionSummaryFields & {
    status: "completed";
    message: string;
    finalMessage?: string;
  };

export type PlanningResumedPayload =
  | {
      kind: "planning.clarification";
      taskId: string;
      runId: string;
      threadId: string;
    }
  | {
      kind: "planning.confirmation";
      taskId: string;
      runId: string;
      threadId: string;
      decision: PlanningConfirmationChoiceId;
      revisionInstructions: string[];
    };

export type PlanningRevisionRequestedPayload = {
  taskId: string;
  reason: string;
  review?: Record<string, unknown>;
  revisionCount: number;
  revisionBudget: number;
  instructions: string[];
};

export type PlanningRevisionStartedPayload = {
  taskId: string;
  revisionCount: number;
  revisionBudget: number;
  instructions: string[];
};

export type PlanningRevisionCompletedPayload = {
  taskId: string;
  revisionCount: number;
  revisionBudget: number;
  planDraftId: string;
};

export type PlanningRevisionExhaustedPayload = {
  taskId: string;
  reason: string;
  review?: Record<string, unknown>;
  revisionCount: number;
  revisionBudget: number;
  instructions?: string[];
};

export type BackendEvent =
  | {
      type: "run.started";
      payload: {
        runId: string;
        taskId: string;
        startedAt: string;
      };
    }
  | {
      type: "run.cancelled";
      payload: {
        runId: string;
        taskId: string;
        completedAt: string;
      };
    }
  | {
      type: "message.started";
      payload: {
        message: ChatMessage;
      };
    }
  | {
      type: "message.delta";
      payload: {
        messageId: string;
        delta: string;
      };
    }
  | {
      type: "message.completed";
      payload: {
        messageId: string;
      };
    }
  | {
      type: "message.created";
      payload: {
        message: ChatMessage;
        sources?: WebSourceReference[];
        rejectedSources?: WebSourceReference[];
        sourceMetadata?: MessageSourceMetadata;
      };
    }
  | {
      type: "input.required";
      payload: {
        prompt: string;
        missing: string[];
      };
    }
  | {
      type: "planning.progress";
      payload: {
        taskId: string;
        stageId: string;
        label: string;
        summary: string;
        status: "completed" | "running" | "waiting" | string;
        sequence: number;
        total: number;
      };
    }
  | {
      type: "planning.stage_changed";
      payload: {
        taskId: string;
        stage: string;
        label: string;
      };
    }
  | {
      type: "planning.checkpoint_recorded";
      payload: {
        checkpoint: PlanningCheckpointRecord;
      };
    }
  | {
      type: "reasoning.decision_created";
      payload: {
        decision: Record<string, unknown>;
      };
    }
  | {
      type: "reasoning.completed";
      payload: {
        taskId: string;
        nextAction: string;
      };
    }
  | {
      type: "planning.started";
      payload: {
        taskId: string;
      };
    }
  | {
      type: "planning.thinking_status";
      payload: {
        thinkingStatus: Record<string, unknown>;
      };
    }
  | {
      type: "planning.draft_created";
      payload: {
        planDraft: Record<string, unknown>;
      };
    }
  | {
      type: "planning.review_completed";
      payload: {
        review: Record<string, unknown>;
      };
    }
  | {
      type: "planning.graph_compiled";
      payload: {
        graph: NodeGraph;
      };
    }
  | {
      type: "planning.graph_review_completed";
      payload: {
        review: Record<string, unknown>;
      };
    }
  | {
      type: "planning.revision_requested";
      payload: PlanningRevisionRequestedPayload;
    }
  | {
      type: "planning.revision_started";
      payload: PlanningRevisionStartedPayload;
    }
  | {
      type: "planning.revision_completed";
      payload: PlanningRevisionCompletedPayload;
    }
  | {
      type: "planning.revision_exhausted";
      payload: PlanningRevisionExhaustedPayload;
    }
  | {
      type: "planning.clarification_required";
      payload: PlanningClarificationPayload;
    }
  | {
      type: "planning.confirmation_required";
      payload: PlanningConfirmationRequiredPayload;
    }
  | {
      type: "planning.confirmed";
      payload: PlanningTerminalPayload;
    }
  | {
      type: "agent_plan_graph.compile_started";
      payload: AgentPlanGraphCompileStartedPayload;
    }
  | {
      type: "agent_plan_graph.compiled";
      payload: AgentPlanGraphCompiledPayload;
    }
  | {
      type: "agent_plan_graph.compile_review_completed";
      payload: AgentPlanGraphCompileReviewCompletedPayload;
    }
  | {
      type: "agent_plan_graph.execution_ready";
      payload: AgentPlanGraphExecutionReadyPayload;
    }
  | {
      type: "agent_plan_graph.compile_failed";
      payload: AgentPlanGraphCompileFailedPayload;
    }
  | {
      type: "agent_execution.started";
      payload: AgentExecutionStartedPayload;
    }
  | {
      type: "agent_execution.completed";
      payload: AgentExecutionCompletedPayload;
    }
  | {
      type: "agent_execution.failed";
      payload: AgentExecutionFailedPayload;
    }
  | {
      type: "agent_execution.interrupted";
      payload: AgentExecutionInterruptedPayload;
    }
  | {
      type: "agent_execution.verify_completed";
      payload: AgentExecutionVerifyCompletedPayload;
    }
  | {
      type: "agent_execution.repair_proposed";
      payload: AgentExecutionRepairProposedPayload;
    }
  | {
      type: "agent_execution.final";
      payload: AgentExecutionFinalPayload;
    }
  | {
      type: "planning.cancelled";
      payload: PlanningTerminalPayload;
    }
  | {
      type: "planning.interrupted";
      payload: PlanningClarificationPayload | PlanningConfirmationRequiredPayload;
    }
  | {
      type: "planning.resumed";
      payload: PlanningResumedPayload;
    }
  | {
      type: "planning.failed";
      payload: {
        reason: string;
        message?: string;
        review?: Record<string, unknown>;
      };
    }
  | {
      type: "node_graph.created";
      payload: {
        graph: NodeGraph;
      };
    }
  | {
      type: "node.created";
      payload: {
        node: AgentNode;
      };
    }
  | {
      type: "node.updated";
      payload: {
        node: AgentNode;
      };
    }
  | {
      type: "node.running";
      payload: {
        nodeId: string;
      };
    }
  | {
      type: "node.completed";
      payload: {
        nodeId: string;
        artifactRefs: string[];
      };
    }
  | {
      type: "node.failed";
      payload: {
        nodeId: string;
        taskId?: string;
        runId?: string;
        error: string;
        errorCode?: string;
      };
    }
  | {
      type: "node.skipped";
      payload: {
        nodeId: string;
        reason: string;
      };
    }
  | {
      type: "node.run_recorded";
      payload: {
        record: NodeRunRecord;
      };
    }
  | {
      type: "permission.required";
      payload: {
        nodeId: string;
        taskId?: string;
        runId?: string;
        permissions: string[];
      };
    }
  | {
      type: "research.completed";
      payload: {
        taskId: string;
        runId?: string;
        reportArtifactId?: string;
        reportArtifactPath?: string;
        summary?: string;
        acceptedSources?: WebSourceReference[];
        rejectedSources?: WebSourceReference[];
      };
    }
  | {
      type: "research.choice_required";
      payload: ResearchChoicePayload;
    }
  | {
      type: "node.needs_permission";
      payload: {
        nodeId: string;
        permissions: string[];
        scriptReview?: ScriptReviewState;
      };
    }
  | {
      type: "node.runtime_notice";
      payload: {
        nodeId: string;
        notice: RuntimeNotice;
      };
    }
  | {
      type: "runtime.checkpoint_recorded";
      payload: {
        checkpoint: RuntimeCheckpointRecord;
      };
    }
  | {
      type: "runtime.span_recorded";
      payload: {
        span: RuntimeSpanRecord;
      };
    }
  | {
      type: "runtime.resume_started";
      payload: {
        runId: string;
        taskId: string;
        checkpoint: RuntimeCheckpointRecord;
        pendingNodeIds: string[];
      };
    }
  | {
      type: "runtime.legacy_graph_blocked";
      payload: {
        runId: string;
        threadId: string;
        taskId: string;
        reason: string;
        blockedEventTypes: string[];
      };
    }
  | {
      type: "runtime.deep_agent_product_path_blocked";
      payload: {
        runId: string;
        threadId: string;
        taskId: string;
        reason: string;
      };
    }
  | {
      type: "authority.decision_recorded";
      payload: {
        decision: AuthorityDecisionRecord;
      };
    }
  | {
      type: "recovery.action_proposed";
      payload: {
        action: RecoveryActionRecord;
      };
    }
  | {
      type: "recovery.action_applied";
      payload: {
        action: RecoveryActionRecord;
      };
    }
  | {
      type: "recovery.continued";
      payload: {
        runId: string;
        taskId: string;
        nodeId: string;
        reason: string;
        recoveryCount: number;
        suggestion?: unknown;
        createdAt: string;
      };
    }
  | {
      type: "graph.replanned";
      payload: {
        graph: NodeGraph;
        previousGraphId?: string;
        summary?: string;
      };
    }
  | {
      type: "graph.overwrite_confirmation_required";
      payload: {
        taskId: string;
        previousGraphId: string;
        summary: string;
        pendingChoice: Record<string, unknown>;
        choices: Array<{
          id: "confirm_overwrite" | "cancel";
          label: string;
          description?: string;
        }>;
      };
    }
  | {
      type: "artifact.created";
      payload: {
        artifactId: string;
        path: string;
        sourceNodeId?: string;
        createdAt?: string;
      };
    }
  | {
      type: "graph.patch_suggested";
      payload: {
        reason: string;
        operations: Array<{
          op:
            | "retry_node"
            | "rerun_node"
            | "rerun_from_node"
            | "request_tool_enablement";
          node_id: string;
          reason: string;
        }>;
        requires_user_approval: boolean;
      };
    }
  | {
      type: "task.completed";
      payload: {
        taskId: string;
        runId?: string;
      };
    }
  | {
      type: "task.failed";
      payload: {
        taskId: string;
        error: string;
        runId?: string;
        errorCode?: string;
      };
    };
