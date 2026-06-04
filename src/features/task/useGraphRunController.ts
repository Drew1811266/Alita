import { useCallback, useMemo, useState } from "react";
import {
  reduceBackendEvents,
  type ActiveAgentExecutionFlow,
  type AgentCompileStatus,
  type AgentPlanGraphCompileFailedPayload,
  type AgentPlanGraphExecutionReadyPayload,
  type PendingGraphOverwriteChoice,
  type PendingPlanningChoice,
  type PendingResearchChoice,
  type ResearchChoiceSubmitPayload,
} from "../../app/backendEvents";
import type { BackendEvent } from "../../shared/events";
import type { PlanningCheckpointRecord } from "../../shared/events";
import type {
  AgentNode,
  ArtifactRef,
  ChatMessage,
  NodeGraph,
  RuntimeObservabilityState,
  RunHistoryEntry,
} from "../../shared/types";
import {
  createRuntimeObservabilityState,
  reduceRuntimeObservabilityEvents,
} from "./useGraphRuntimeController";

export type GraphRunControllerState = {
  messages: ChatMessage[];
  graph: NodeGraph | null;
  runHistory: RunHistoryEntry[];
  artifacts: ArtifactRef[];
  runtimeObservability: RuntimeObservabilityState;
  pendingResearchChoice: PendingResearchChoice | null;
  pendingGraphOverwriteChoice: PendingGraphOverwriteChoice | null;
  pendingPlanningChoice: PendingPlanningChoice | null;
  planningCheckpoints: PlanningCheckpointRecord[];
  activeRunId: string | null;
  selectedCanvasNode: AgentNode | null;
  agentCompileStatus: AgentCompileStatus;
  agentExecutionReadySummary: AgentPlanGraphExecutionReadyPayload | null;
  agentCompileFailure: AgentPlanGraphCompileFailedPayload | null;
  activeAgentExecutionFlow: ActiveAgentExecutionFlow | null;
  dirty: boolean;
};

export function createGraphRunControllerState(): GraphRunControllerState {
  return {
    messages: [],
    graph: null,
    runHistory: [],
    artifacts: [],
    runtimeObservability: createRuntimeObservabilityState(),
    pendingResearchChoice: null,
    pendingGraphOverwriteChoice: null,
    pendingPlanningChoice: null,
    planningCheckpoints: [],
    activeRunId: null,
    selectedCanvasNode: null,
    agentCompileStatus: "idle",
    agentExecutionReadySummary: null,
    agentCompileFailure: null,
    activeAgentExecutionFlow: null,
    dirty: false,
  };
}

export function reduceGraphRunControllerEvents(
  state: GraphRunControllerState,
  events: BackendEvent[],
  createAssistantMessage: (content: string) => ChatMessage = createDefaultAssistantMessage,
  submittedPayload?: ResearchChoiceSubmitPayload,
): GraphRunControllerState {
  const reduced = reduceBackendEvents(
    {
      messages: state.messages,
      graph: state.graph,
      dirty: state.dirty,
      pendingResearchChoice: state.pendingResearchChoice,
      pendingGraphOverwriteChoice: state.pendingGraphOverwriteChoice,
      pendingPlanningChoice: state.pendingPlanningChoice,
      planningCheckpoints: state.planningCheckpoints,
      activeRunId: state.activeRunId,
      runHistory: state.runHistory,
      artifacts: state.artifacts,
      agentCompileStatus: state.agentCompileStatus,
      agentExecutionReadySummary: state.agentExecutionReadySummary,
      agentCompileFailure: state.agentCompileFailure,
      activeAgentExecutionFlow: state.activeAgentExecutionFlow,
    },
    events,
    createAssistantMessage,
    submittedPayload,
  );
  const currentObservability =
    state.runtimeObservability ?? createRuntimeObservabilityState();
  const runtimeObservability = reduceRuntimeObservabilityEvents(
    currentObservability,
    events,
  );
  const runtimeObservabilityChanged =
    runtimeObservability !== currentObservability;

  return {
    ...state,
    messages: reduced.messages,
    graph: reduced.graph,
    runHistory: reduced.runHistory ?? state.runHistory,
    artifacts: reduced.artifacts ?? state.artifacts,
    runtimeObservability,
    pendingResearchChoice: reduced.pendingResearchChoice ?? null,
    pendingGraphOverwriteChoice: reduced.pendingGraphOverwriteChoice ?? null,
    pendingPlanningChoice: reduced.pendingPlanningChoice ?? null,
    planningCheckpoints: reduced.planningCheckpoints ?? state.planningCheckpoints,
    activeRunId: reduced.activeRunId ?? null,
    agentCompileStatus: reduced.agentCompileStatus ?? "idle",
    agentExecutionReadySummary: reduced.agentExecutionReadySummary ?? null,
    agentCompileFailure: reduced.agentCompileFailure ?? null,
    activeAgentExecutionFlow: reduced.activeAgentExecutionFlow ?? null,
    dirty: state.dirty || reduced.dirty || runtimeObservabilityChanged,
  };
}

export function useGraphRunController(
  initial?: Partial<GraphRunControllerState>,
) {
  const [state, setState] = useState<GraphRunControllerState>({
    ...createGraphRunControllerState(),
    ...initial,
  });

  const applyBackendEvents = useCallback(
    (
      events: BackendEvent[],
      createAssistantMessage?: (content: string) => ChatMessage,
      submittedPayload?: ResearchChoiceSubmitPayload,
    ) => {
      setState((current) =>
        reduceGraphRunControllerEvents(
          current,
          events,
          createAssistantMessage,
          submittedPayload,
        ),
      );
    },
    [],
  );

  return useMemo(
    () => ({
      state,
      setState,
      applyBackendEvents,
    }),
    [applyBackendEvents, state],
  );
}

function createDefaultAssistantMessage(content: string): ChatMessage {
  return {
    messageId: "assistant-message",
    role: "assistant",
    content,
    attachments: [],
    createdAt: new Date(0).toISOString(),
  };
}
