import { useCallback, useRef, useState } from "react";

export type GraphRuntimeControllerState = {
  running: boolean;
  cancelling: boolean;
};

export function createGraphRuntimeControllerState(): GraphRuntimeControllerState {
  return {
    running: false,
    cancelling: false,
  };
}

export function graphRunStarted(
  runId: string,
): GraphRuntimeControllerState & { activeRunId: string } {
  return {
    running: true,
    cancelling: false,
    activeRunId: runId,
  };
}

export function graphRunSettled(): GraphRuntimeControllerState {
  return {
    running: false,
    cancelling: false,
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

  const setActiveRunIdRef = useCallback((runId: string | null) => {
    activeRunIdRef.current = runId;
  }, []);

  return {
    state,
    activeRunIdRef,
    setRunning,
    setCancelling,
    setActiveRunIdRef,
  };
}
