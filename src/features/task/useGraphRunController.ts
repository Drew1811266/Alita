import { useCallback, useMemo, useState } from "react";
import {
  reduceBackendEvents,
  type PendingGraphOverwriteChoice,
  type PendingResearchChoice,
  type ResearchChoiceSubmitPayload,
} from "../../app/backendEvents";
import type { BackendEvent } from "../../shared/events";
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
  activeRunId: string | null;
  selectedCanvasNode: AgentNode | null;
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
    activeRunId: null,
    selectedCanvasNode: null,
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
      activeRunId: state.activeRunId,
      runHistory: state.runHistory,
      artifacts: state.artifacts,
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
    activeRunId: reduced.activeRunId ?? null,
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
