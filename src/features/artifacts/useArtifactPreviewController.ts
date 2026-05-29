import { useCallback, useMemo, useState } from "react";
import type { AgentNode, ArtifactRef } from "../../shared/types";
import type { ArtifactTextPreview } from "./artifactApi";
import {
  resolvePreviewArtifactForNode,
  type PreviewArtifactSelection,
} from "./artifactPreview";

export type ArtifactPreviewState = {
  artifactPreview: ArtifactTextPreview | null;
  loading: boolean;
  error: string | null;
};

export function createArtifactPreviewState(): ArtifactPreviewState {
  return {
    artifactPreview: null,
    loading: false,
    error: null,
  };
}

export function resolveArtifactPreviewRequest(
  node: AgentNode | null,
  artifacts: ArtifactRef[],
): { artifact: PreviewArtifactSelection } | null {
  const artifact = resolvePreviewArtifactForNode(node, artifacts);
  return artifact ? { artifact } : null;
}

export function useArtifactPreviewController() {
  const [state, setState] = useState(createArtifactPreviewState);

  const clearPreview = useCallback(() => {
    setState(createArtifactPreviewState());
  }, []);

  const startPreviewLoad = useCallback(() => {
    setState({ artifactPreview: null, loading: true, error: null });
  }, []);

  const setArtifactPreview = useCallback(
    (artifactPreview: ArtifactTextPreview | null) => {
      setState((current) => ({ ...current, artifactPreview }));
    },
    [],
  );

  const setPreviewError = useCallback((error: string | null) => {
    setState((current) => ({ ...current, error }));
  }, []);

  const setPreviewLoading = useCallback((loading: boolean) => {
    setState((current) => ({ ...current, loading }));
  }, []);

  return useMemo(
    () => ({
      state,
      clearPreview,
      startPreviewLoad,
      setArtifactPreview,
      setPreviewError,
      setPreviewLoading,
    }),
    [
      clearPreview,
      setArtifactPreview,
      setPreviewError,
      setPreviewLoading,
      startPreviewLoad,
      state,
    ],
  );
}
