import { useCallback, useEffect, useRef, useState } from "react";

import { getNodeCatalog } from "./nodeCatalogApi";
import type { NodeCatalogSnapshot } from "../../shared/types";

export type NodeCatalogState = {
  catalog: NodeCatalogSnapshot | null;
  loading: boolean;
  error: string | null;
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

export function useNodeCatalog(): UseNodeCatalogResult {
  const mountedRef = useRef(true);
  const [state, setState] = useState<NodeCatalogState>(createNodeCatalogState);

  const refresh = useCallback(async () => {
    if (mountedRef.current) {
      setState(nodeCatalogLoading);
    }

    try {
      const catalog = await getNodeCatalog();
      if (mountedRef.current) {
        setState((current) => nodeCatalogLoaded(current, catalog));
      }
      return catalog;
    } catch (error) {
      if (mountedRef.current) {
        setState((current) => nodeCatalogFailed(current, errorMessage(error)));
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

  return { ...state, refresh };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
