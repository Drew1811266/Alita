import { useCallback, useRef, useState } from "react";
import type { BackendEvent } from "../../shared/events";
import type { RuntimeObservabilityState } from "../../shared/types";

export type GraphRuntimeControllerState = {
  running: boolean;
  cancelling: boolean;
  observability: RuntimeObservabilityState;
};

export function createGraphRuntimeControllerState(): GraphRuntimeControllerState {
  return {
    running: false,
    cancelling: false,
    observability: createRuntimeObservabilityState(),
  };
}

export function graphRunStarted(
  runId: string,
): GraphRuntimeControllerState & { activeRunId: string } {
  return {
    running: true,
    cancelling: false,
    activeRunId: runId,
    observability: createRuntimeObservabilityState(),
  };
}

export function graphRunSettled(): GraphRuntimeControllerState {
  return {
    running: false,
    cancelling: false,
    observability: createRuntimeObservabilityState(),
  };
}

export function createRuntimeObservabilityState(): RuntimeObservabilityState {
  return {
    checkpoints: [],
    spans: [],
    authorityDecisions: [],
    recoveryActions: [],
  };
}

export function reduceRuntimeObservabilityEvents(
  state: RuntimeObservabilityState,
  events: BackendEvent[],
): RuntimeObservabilityState {
  let checkpoints = state.checkpoints;
  let spans = state.spans;
  let authorityDecisions = state.authorityDecisions;
  let recoveryActions = state.recoveryActions;

  for (const event of events) {
    if (event.type === "runtime.checkpoint_recorded") {
      checkpoints = [...checkpoints, event.payload.checkpoint];
      continue;
    }

    if (event.type === "runtime.span_recorded") {
      spans = [...spans, event.payload.span];
      continue;
    }

    if (event.type === "authority.decision_recorded") {
      authorityDecisions = [...authorityDecisions, event.payload.decision];
      continue;
    }

    if (
      event.type === "recovery.action_proposed" ||
      event.type === "recovery.action_applied"
    ) {
      recoveryActions = [...recoveryActions, event.payload.action];
      continue;
    }

    if (event.type === "recovery.continued") {
      recoveryActions = [
        ...recoveryActions,
        {
          runId: event.payload.runId,
          nodeId: event.payload.nodeId,
          action: "applied",
          reason: event.payload.reason,
          operations: [],
          requiresUserApproval: false,
          createdAt: event.payload.createdAt,
          recoveryCount: event.payload.recoveryCount,
        },
      ];
    }
  }

  if (
    checkpoints === state.checkpoints &&
    spans === state.spans &&
    authorityDecisions === state.authorityDecisions &&
    recoveryActions === state.recoveryActions
  ) {
    return state;
  }

  return {
    checkpoints,
    spans,
    authorityDecisions,
    recoveryActions,
  };
}

export function useGraphRuntimeController() {
  const [state, setState] = useState(createGraphRuntimeControllerState);
  const activeRunIdRef = useRef<string | null>(null);

  const setRunning = useCallback((running: boolean) => {
    setState((current) => ({ ...current, running }));
  }, []);

  const setCancelling = useCallback((cancelling: boolean) => {
    setState((current) => ({ ...current, cancelling }));
  }, []);

  const applyObservabilityEvents = useCallback((events: BackendEvent[]) => {
    setState((current) => ({
      ...current,
      observability: reduceRuntimeObservabilityEvents(
        current.observability,
        events,
      ),
    }));
  }, []);

  const setActiveRunIdRef = useCallback((runId: string | null) => {
    activeRunIdRef.current = runId;
  }, []);

  return {
    state,
    activeRunIdRef,
    setRunning,
    setCancelling,
    applyObservabilityEvents,
    setActiveRunIdRef,
  };
}
