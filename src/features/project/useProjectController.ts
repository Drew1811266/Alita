import { useState } from "react";

import type {
  AlitaProject,
  ProjectOpenWarning,
} from "../../shared/types";

export type ProjectControllerState = {
  activeProject: AlitaProject | null;
  projectWarnings: ProjectOpenWarning[];
  projectError: string | null;
  saving: boolean;
  recentProjects: string[];
};

export function createProjectControllerState(): ProjectControllerState {
  return {
    activeProject: null,
    projectWarnings: [],
    projectError: null,
    saving: false,
    recentProjects: [],
  };
}

export function rememberRecentProject(
  current: string[],
  projectPath: string,
  limit = 8,
): string[] {
  return [
    projectPath,
    ...current.filter((path) => path !== projectPath),
  ].slice(0, limit);
}

export function useProjectController() {
  const [state, setState] = useState(createProjectControllerState);

  return {
    state,
    setActiveProject: (activeProject: AlitaProject | null) =>
      setState((current) => ({ ...current, activeProject })),
    setProjectWarnings: (projectWarnings: ProjectOpenWarning[]) =>
      setState((current) => ({ ...current, projectWarnings })),
    setProjectError: (projectError: string | null) =>
      setState((current) => ({ ...current, projectError })),
    setSaving: (saving: boolean) =>
      setState((current) => ({ ...current, saving })),
    setRecentProjects: (
      action: string[] | ((current: string[]) => string[]),
    ) =>
      setState((current) => ({
        ...current,
        recentProjects:
          typeof action === "function"
            ? action(current.recentProjects)
            : action,
      })),
  };
}
