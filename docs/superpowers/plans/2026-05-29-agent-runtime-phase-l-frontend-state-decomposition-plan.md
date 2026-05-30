# Agent Runtime Phase L Frontend State Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decompose `App.tsx` state into focused feature controllers while preserving the current UI, backend event reducer behavior, and Tauri API contracts.

**Architecture:** Extract controller hooks around existing feature boundaries: graph run lifecycle, artifact preview, preferences, and voice input. Keep `reduceBackendEvents()` as the canonical event reducer and keep `App.tsx` as the composition shell that wires controllers into existing components. This phase does not redesign UI, change backend schemas, or introduce a global state library.

**Tech Stack:** React, TypeScript, Vite/Vitest, existing feature APIs, existing `reduceBackendEvents()`.

---

## Current Baseline

- `src/app/App.tsx` owns project state, messages, draft, voice session, pending attachments, graph, run history, artifacts, artifact preview, preferences, pending research choice, pending graph overwrite choice, selected node, and side-effect handlers.
- `src/app/backendEvents.ts` contains the canonical event reducer.
- Feature APIs already exist under `src/features/*`.
- Existing frontend tests cover backend events and selected App behavior.

## Non-Goals

- Do not redesign the UI.
- Do not replace React state with Redux/Zustand/Jotai.
- Do not change backend event types or payloads.
- Do not change Tauri command signatures.
- Do not add memory UI.
- Do not add new runtime features.

## Files

### Create

- `src/features/task/useGraphRunController.ts`
- `src/features/task/useGraphRunController.test.ts`
- `src/features/artifacts/useArtifactPreviewController.ts`
- `src/features/artifacts/useArtifactPreviewController.test.ts`
- `src/features/preferences/usePreferencesController.ts`
- `src/features/preferences/usePreferencesController.test.ts`
- `src/features/voice/useVoiceInputController.ts`
- `src/features/voice/useVoiceInputController.test.ts`

### Modify

- `src/app/App.tsx`
- `src/app/App.test.tsx`
- `src/app/backendEvents.test.ts`

---

## Controller Boundaries

### `useGraphRunController`

Owns:

- current graph run state
- selected canvas node
- pending research choice
- pending graph overwrite choice
- run/cancel/retry handlers
- applying `reduceBackendEvents()` results

Does not own:

- project persistence
- artifact preview rendering
- preferences dialog state
- voice input

### `useArtifactPreviewController`

Owns:

- `artifactPreview`
- `openArtifact`, `revealArtifact`, `readArtifactText`, `artifactFileUrl` flow
- selected node artifact resolution

### `usePreferencesController`

Owns:

- preferences loading/saving
- model provider commands
- tool enablement
- preferences dialog side effects

### `useVoiceInputController`

Owns:

- voice session state
- recording/transcription lifecycle
- draft insertion callback

---

## Task 0: Baseline Verification

**Files:**
- Read: `src/app/App.tsx`
- Read: `src/app/App.test.tsx`
- Read: `src/app/backendEvents.test.ts`

- [ ] **Step 1: Run current frontend baseline**

Run:

```powershell
npm run frontend:test -- src\app\App.test.tsx src\app\backendEvents.test.ts
npm run frontend:lint
```

Expected:

```text
Test Files  2 passed
```

and typecheck exits `0`.

---

## Task 1: Graph Run Controller

**Files:**
- Create: `src/features/task/useGraphRunController.ts`
- Create: `src/features/task/useGraphRunController.test.ts`
- Modify: `src/app/App.tsx`

- [ ] **Step 1: Add failing hook test**

Create `src/features/task/useGraphRunController.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { createGraphRunControllerState, reduceGraphRunControllerEvents } from "./useGraphRunController";
import type { BackendEvent } from "../../shared/events";

describe("useGraphRunController state reducer", () => {
  it("applies backend graph events without changing event reducer semantics", () => {
    const initial = createGraphRunControllerState();
    const events: BackendEvent[] = [
      {
        type: "node_graph.created",
        payload: {
          graph: {
            graphId: "g1",
            nodes: [],
            edges: [],
            metadata: { plannerChain: { strategy: "legacy_task_planner" } },
          },
        },
      },
    ];

    const next = reduceGraphRunControllerEvents(initial, events);

    expect(next.graph?.graphId).toBe("g1");
    expect(next.pendingResearchChoice).toBeNull();
  });
});
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
npm run frontend:test -- src\features\task\useGraphRunController.test.ts
```

Expected:

```text
Failed to resolve import "./useGraphRunController"
```

- [ ] **Step 3: Implement controller reducer shell**

Create `src/features/task/useGraphRunController.ts`:

```typescript
import { useCallback, useMemo, useState } from "react";
import {
  reduceBackendEvents,
  type PendingGraphOverwriteChoice,
  type PendingResearchChoice,
} from "../../app/backendEvents";
import type { BackendEvent } from "../../shared/events";
import type { AgentNode, ArtifactRef, ChatMessage, NodeGraph, RunHistoryEntry } from "../../shared/types";

export type GraphRunControllerState = {
  messages: ChatMessage[];
  graph: NodeGraph | null;
  runHistory: RunHistoryEntry[];
  artifacts: ArtifactRef[];
  pendingResearchChoice: PendingResearchChoice | null;
  pendingGraphOverwriteChoice: PendingGraphOverwriteChoice | null;
  selectedCanvasNode: AgentNode | null;
};

export function createGraphRunControllerState(): GraphRunControllerState {
  return {
    messages: [],
    graph: null,
    runHistory: [],
    artifacts: [],
    pendingResearchChoice: null,
    pendingGraphOverwriteChoice: null,
    selectedCanvasNode: null,
  };
}

export function reduceGraphRunControllerEvents(
  state: GraphRunControllerState,
  events: BackendEvent[],
): GraphRunControllerState {
  const reduced = reduceBackendEvents(
    {
      messages: state.messages,
      graph: state.graph,
      runHistory: state.runHistory,
      artifacts: state.artifacts,
      pendingResearchChoice: state.pendingResearchChoice,
      pendingGraphOverwriteChoice: state.pendingGraphOverwriteChoice,
    },
    events,
  );
  return {
    ...state,
    ...reduced,
  };
}

export function useGraphRunController(initial?: Partial<GraphRunControllerState>) {
  const [state, setState] = useState<GraphRunControllerState>({
    ...createGraphRunControllerState(),
    ...initial,
  });

  const applyBackendEvents = useCallback((events: BackendEvent[]) => {
    setState((current) => reduceGraphRunControllerEvents(current, events));
  }, []);

  return useMemo(
    () => ({
      state,
      setState,
      applyBackendEvents,
    }),
    [applyBackendEvents, state],
  );
}
```

This task only introduces the controller shell and reducer helpers. Move event-application code from `App.tsx` into the hook only after tests pass.

- [ ] **Step 4: Run hook test**

Run:

```powershell
npm run frontend:test -- src\features\task\useGraphRunController.test.ts
```

Expected:

```text
Test Files  1 passed
```

- [ ] **Step 5: Wire App incrementally**

In `App.tsx`, replace direct calls to `reduceBackendEvents()` for task graph runs with `useGraphRunController().applyBackendEvents()`. Keep state variable names exported from the hook so component props remain stable.

- [ ] **Step 6: Run frontend tests**

Run:

```powershell
npm run frontend:test -- src\features\task\useGraphRunController.test.ts src\app\App.test.tsx src\app\backendEvents.test.ts
npm run frontend:lint
```

Expected:

```text
Test Files  3 passed
```

- [ ] **Step 7: Commit**

Run:

```powershell
git add src/features/task/useGraphRunController.ts src/features/task/useGraphRunController.test.ts src/app/App.tsx
git commit -m "refactor: extract graph run controller"
```

---

## Task 2: Artifact Preview Controller

**Files:**
- Create: `src/features/artifacts/useArtifactPreviewController.ts`
- Create: `src/features/artifacts/useArtifactPreviewController.test.ts`
- Modify: `src/app/App.tsx`

- [ ] **Step 1: Add failing artifact controller test**

Create `src/features/artifacts/useArtifactPreviewController.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { createArtifactPreviewState, resolveArtifactPreviewRequest } from "./useArtifactPreviewController";
import type { ArtifactRef, AgentNode } from "../../shared/types";

describe("artifact preview controller helpers", () => {
  it("resolves an artifact preview request from a selected node", () => {
    const artifact: ArtifactRef = {
      artifactId: "a1",
      path: "D:\\Project\\artifacts\\report.md",
      kind: "markdown",
      sourceNodeId: "node-1",
      createdAt: "2026-05-29T00:00:00Z",
    };
    const node = { nodeId: "node-1" } as AgentNode;

    const request = resolveArtifactPreviewRequest(node, [artifact]);

    expect(createArtifactPreviewState().artifactPreview).toBeNull();
    expect(request?.artifact.artifactId).toBe("a1");
  });
});
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
npm run frontend:test -- src\features\artifacts\useArtifactPreviewController.test.ts
```

Expected:

```text
Failed to resolve import "./useArtifactPreviewController"
```

- [ ] **Step 3: Implement controller helper**

Create `src/features/artifacts/useArtifactPreviewController.ts` with:

```typescript
import { useCallback, useMemo, useState } from "react";
import { resolvePreviewArtifactForNode } from "./artifactPreview";
import type { AgentNode, ArtifactRef } from "../../shared/types";

export type ArtifactPreviewState = {
  artifactPreview: ArtifactRef | null;
};

export function createArtifactPreviewState(): ArtifactPreviewState {
  return { artifactPreview: null };
}

export function resolveArtifactPreviewRequest(
  node: AgentNode | null,
  artifacts: ArtifactRef[],
) {
  const artifact = resolvePreviewArtifactForNode(node, artifacts);
  return artifact ? { artifact } : null;
}

export function useArtifactPreviewController() {
  const [state, setState] = useState(createArtifactPreviewState);
  const clearPreview = useCallback(() => setState(createArtifactPreviewState()), []);
  const setArtifactPreview = useCallback((artifactPreview: ArtifactRef | null) => {
    setState({ artifactPreview });
  }, []);
  return useMemo(
    () => ({ state, clearPreview, setArtifactPreview }),
    [clearPreview, setArtifactPreview, state],
  );
}
```

- [ ] **Step 4: Wire App artifact preview state**

Move `artifactPreview` state and selected-node artifact preview helper usage from `App.tsx` into the hook without changing component props.

- [ ] **Step 5: Run frontend tests**

Run:

```powershell
npm run frontend:test -- src\features\artifacts\useArtifactPreviewController.test.ts src\app\App.test.tsx
npm run frontend:lint
```

Expected:

```text
Test Files  2 passed
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add src/features/artifacts/useArtifactPreviewController.ts src/features/artifacts/useArtifactPreviewController.test.ts src/app/App.tsx
git commit -m "refactor: extract artifact preview controller"
```

---

## Task 3: Preferences Controller

**Files:**
- Create: `src/features/preferences/usePreferencesController.ts`
- Create: `src/features/preferences/usePreferencesController.test.ts`
- Modify: `src/app/App.tsx`

- [ ] **Step 1: Add preferences controller test**

Create `src/features/preferences/usePreferencesController.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { createPreferencesControllerState, preferencesLoaded } from "./usePreferencesController";
import type { PreferencesView } from "./preferencesApi";

describe("preferences controller helpers", () => {
  it("stores loaded preferences and clears loading state", () => {
    const preferences = { schemaVersion: 3 } as PreferencesView;

    const state = preferencesLoaded(createPreferencesControllerState(), preferences);

    expect(state.preferences).toBe(preferences);
    expect(state.loading).toBe(false);
    expect(state.error).toBeNull();
  });
});
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
npm run frontend:test -- src\features\preferences\usePreferencesController.test.ts
```

Expected:

```text
Failed to resolve import "./usePreferencesController"
```

- [ ] **Step 3: Implement controller state helpers**

Create `src/features/preferences/usePreferencesController.ts` with reducer-style helpers first:

```typescript
import { useCallback, useMemo, useState } from "react";
import { getPreferences, type PreferencesView } from "./preferencesApi";

export type PreferencesControllerState = {
  preferences: PreferencesView | null;
  loading: boolean;
  error: string | null;
};

export function createPreferencesControllerState(): PreferencesControllerState {
  return { preferences: null, loading: false, error: null };
}

export function preferencesLoaded(
  state: PreferencesControllerState,
  preferences: PreferencesView,
): PreferencesControllerState {
  return { ...state, preferences, loading: false, error: null };
}

export function usePreferencesController() {
  const [state, setState] = useState(createPreferencesControllerState);
  const reloadPreferences = useCallback(async () => {
    setState((current) => ({ ...current, loading: true, error: null }));
    try {
      const preferences = await getPreferences();
      setState((current) => preferencesLoaded(current, preferences));
    } catch (error) {
      setState((current) => ({
        ...current,
        loading: false,
        error: error instanceof Error ? error.message : String(error),
      }));
    }
  }, []);
  return useMemo(() => ({ state, setState, reloadPreferences }), [reloadPreferences, state]);
}
```

- [ ] **Step 4: Move App preferences state**

Move preferences state variables and reload helper from `App.tsx` into `usePreferencesController`. Keep command functions in `preferencesApi.ts`.

- [ ] **Step 5: Run frontend tests**

Run:

```powershell
npm run frontend:test -- src\features\preferences\usePreferencesController.test.ts src\app\App.test.tsx
npm run frontend:lint
```

Expected:

```text
Test Files  2 passed
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add src/features/preferences/usePreferencesController.ts src/features/preferences/usePreferencesController.test.ts src/app/App.tsx
git commit -m "refactor: extract preferences controller"
```

---

## Task 4: Voice Input Controller

**Files:**
- Create: `src/features/voice/useVoiceInputController.ts`
- Create: `src/features/voice/useVoiceInputController.test.ts`
- Modify: `src/app/App.tsx`

- [ ] **Step 1: Add voice controller test**

Create `src/features/voice/useVoiceInputController.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { createVoiceInputControllerState, voiceControllerFailed } from "./useVoiceInputController";

describe("voice input controller helpers", () => {
  it("records voice errors in controller state", () => {
    const state = voiceControllerFailed(createVoiceInputControllerState(), "microphone denied");

    expect(state.voiceInput.status).toBe("error");
    expect(state.voiceInput.error).toBe("microphone denied");
  });
});
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
npm run frontend:test -- src\features\voice\useVoiceInputController.test.ts
```

Expected:

```text
Failed to resolve import "./useVoiceInputController"
```

- [ ] **Step 3: Implement voice controller shell**

Create `src/features/voice/useVoiceInputController.ts`:

```typescript
import { useCallback, useMemo, useState } from "react";
import { createInitialVoiceInput, voiceFailed } from "./voiceSession";

export type VoiceInputControllerState = {
  voiceInput: ReturnType<typeof createInitialVoiceInput>;
};

export function createVoiceInputControllerState(): VoiceInputControllerState {
  return { voiceInput: createInitialVoiceInput() };
}

export function voiceControllerFailed(
  state: VoiceInputControllerState,
  error: string,
): VoiceInputControllerState {
  return { ...state, voiceInput: voiceFailed(state.voiceInput, error) };
}

export function useVoiceInputController() {
  const [state, setState] = useState(createVoiceInputControllerState);
  const failVoiceInput = useCallback((error: string) => {
    setState((current) => voiceControllerFailed(current, error));
  }, []);
  return useMemo(() => ({ state, setState, failVoiceInput }), [failVoiceInput, state]);
}
```

- [ ] **Step 4: Move App voice state**

Move `voiceInput`, audio refs, recording lifecycle, and transcription lifecycle into the hook. Keep behavior identical:

- `canStartVoiceRecording`
- `canStopVoiceRecording`
- `encodeWav`
- `transcribeVoiceAudio`
- `insertTranscriptIntoDraft`

Use callback injection for draft insertion so the hook does not own chat draft state.

- [ ] **Step 5: Run frontend tests**

Run:

```powershell
npm run frontend:test -- src\features\voice\useVoiceInputController.test.ts src\app\App.test.tsx
npm run frontend:lint
```

Expected:

```text
Test Files  2 passed
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add src/features/voice/useVoiceInputController.ts src/features/voice/useVoiceInputController.test.ts src/app/App.tsx
git commit -m "refactor: extract voice input controller"
```

---

## Task 5: App Composition Cleanup

**Files:**
- Modify: `src/app/App.tsx`
- Modify: `src/app/App.test.tsx`
- Modify: `src/app/backendEvents.test.ts`

- [ ] **Step 1: Add App smoke assertion**

Add or update `src/app/App.test.tsx` so it still verifies the app renders the main workbench shell after controller extraction:

```typescript
it("renders the workbench shell after controller extraction", () => {
  render(<App />);

  expect(screen.getByRole("main")).toBeInTheDocument();
});
```

If the existing app test uses a different root query, keep the existing query and add only one assertion that fails if `App` crashes during controller composition.

- [ ] **Step 2: Run App tests**

Run:

```powershell
npm run frontend:test -- src\app\App.test.tsx src\app\backendEvents.test.ts
```

Expected:

```text
Test Files  2 passed
```

- [ ] **Step 3: Remove dead state and imports**

In `App.tsx`, remove state variables and imports that are now owned by controllers. Keep JSX prop names and child components stable.

- [ ] **Step 4: Run full frontend checks**

Run:

```powershell
npm run frontend:lint
npm run frontend:test
```

Expected:

```text
Test Files ... passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/app/App.tsx src/app/App.test.tsx src/app/backendEvents.test.ts
git commit -m "refactor: make app compose feature controllers"
```

---

## Task 6: Final Regression And Review

**Files:**
- Read: `src/app/App.tsx`
- Read: `src/features/task/useGraphRunController.ts`
- Read: `src/features/artifacts/useArtifactPreviewController.ts`
- Read: `src/features/preferences/usePreferencesController.ts`
- Read: `src/features/voice/useVoiceInputController.ts`

- [ ] **Step 1: Run frontend verification**

Run:

```powershell
npm run frontend:lint
npm run frontend:test
```

Expected:

```text
Test Files ... passed
```

- [ ] **Step 2: Run backend event compatibility**

Run:

```powershell
npm run frontend:test -- src\app\backendEvents.test.ts src\features\task\useTaskEvents.test.ts
```

Expected:

```text
Test Files  2 passed
```

- [ ] **Step 3: Run full MVP verification**

Run:

```powershell
.\scripts\verify-mvp.ps1
```

Expected:

```text
MVP verification passed.
```

- [ ] **Step 4: Final code review**

Dispatch final review:

```text
Review Phase L Frontend State Decomposition implementation. Prioritize App.tsx behavior preservation, backend event reducer compatibility, controller boundaries, hook test quality, no global store introduction, no UI redesign, no backend schema changes, and whether the refactor makes future runtime events easier to integrate without hiding state flow.
```

Expected: reviewer returns no critical or important findings. Fix any critical or important finding before finishing Phase L.

---

## Acceptance Criteria

Phase L is complete when all statements are true:

- `App.tsx` delegates graph run, artifact preview, preferences, and voice state to feature controllers.
- `reduceBackendEvents()` remains canonical for backend event semantics.
- New controller hooks have focused tests.
- Existing UI behavior and event shapes remain stable.
- No global state library is introduced.
- No backend schema or Tauri command signature changes are introduced.
- `npm run frontend:lint`, `npm run frontend:test`, and `.\scripts\verify-mvp.ps1` pass.

## Handoff Notes

After Phase L, the Agent Runtime roadmap from Phase A through Phase L has a maintainable backend runtime spine and a frontend shell that can absorb later runtime events without turning `App.tsx` into the only state owner again.
