import { useCallback, useEffect, useRef, useState } from "react";

import { getNodeCatalog } from "./nodeCatalogApi";
import type { NodeCatalogSnapshot } from "../../shared/types";

export type NodeCatalogState = {
  catalog: NodeCatalogSnapshot | null;
  loading: boolean;
  error: string | null;
};

export type NodeCatalogRequestState = NodeCatalogState & {
  activeRequestId: number;
};

export type UseNodeCatalogResult = NodeCatalogState & {
  refresh: () => Promise<NodeCatalogSnapshot | null>;
};

export function createNodeCatalogState(): NodeCatalogState {
  return {
    catalog: null,
    loading: false,
    error: null,
  };
}

export function createNodeCatalogRequestState(): NodeCatalogRequestState {
  return {
    ...createNodeCatalogState(),
    activeRequestId: 0,
  };
}

export function nodeCatalogLoading(state: NodeCatalogState): NodeCatalogState {
  return { ...state, loading: true, error: null };
}

export function nodeCatalogLoaded(
  state: NodeCatalogState,
  catalog: NodeCatalogSnapshot,
): NodeCatalogState {
  return { ...state, catalog, loading: false, error: null };
}

export function nodeCatalogFailed(
  state: NodeCatalogState,
  error: string,
): NodeCatalogState {
  return { ...state, loading: false, error };
}

export function nodeCatalogRequestLoading(
  state: NodeCatalogRequestState,
  requestId: number,
): NodeCatalogRequestState {
  return {
    ...state,
    activeRequestId: requestId,
    loading: true,
    error: null,
  };
}

export function nodeCatalogRequestLoaded(
  state: NodeCatalogRequestState,
  requestId: number,
  catalog: NodeCatalogSnapshot,
): NodeCatalogRequestState {
  if (state.activeRequestId !== requestId) {
    return state;
  }
  return {
    ...state,
    catalog,
    loading: false,
    error: null,
  };
}

export function nodeCatalogRequestFailed(
  state: NodeCatalogRequestState,
  requestId: number,
  error: string,
): NodeCatalogRequestState {
  if (state.activeRequestId !== requestId) {
    return state;
  }
  return {
    ...state,
    loading: false,
    error,
  };
}

export function useNodeCatalog(): UseNodeCatalogResult {
  const mountedRef = useRef(true);
  const requestSequenceRef = useRef(0);
  const [state, setState] = useState<NodeCatalogRequestState>(
    createNodeCatalogRequestState,
  );

  const refresh = useCallback(async () => {
    requestSequenceRef.current += 1;
    const requestId = requestSequenceRef.current;

    if (mountedRef.current) {
      setState((current) => nodeCatalogRequestLoading(current, requestId));
    }

    try {
      const catalog = await getNodeCatalog();
      if (mountedRef.current) {
        setState((current) =>
          nodeCatalogRequestLoaded(current, requestId, catalog),
        );
      }
      return catalog;
    } catch (error) {
      if (mountedRef.current) {
        setState((current) =>
          nodeCatalogRequestFailed(current, requestId, errorMessage(error)),
        );
      }
      return null;
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    void refresh();
    return () => {
      mountedRef.current = false;
    };
  }, [refresh]);

  const { activeRequestId: _activeRequestId, ...publicState } = state;
  return { ...publicState, refresh };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
