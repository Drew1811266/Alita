import { describe, expect, it } from "vitest";
import type { BackendEvent } from "../../shared/events";
import {
  createGraphRunControllerState,
  reduceGraphRunControllerEvents,
} from "./useGraphRunController";

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

  it("preserves existing dirty state when no backend event changes it", () => {
    const next = reduceGraphRunControllerEvents(
      { ...createGraphRunControllerState(), dirty: true },
      [],
    );

    expect(next.dirty).toBe(true);
  });

  it("stores runtime observability events beside existing graph run state", () => {
    const initial = createGraphRunControllerState();
    const events: BackendEvent[] = [
      {
        type: "node_graph.created",
        payload: {
          graph: {
            graphId: "g1",
            nodes: [],
            edges: [],
          },
        },
      },
      {
        type: "runtime.checkpoint_recorded",
        payload: {
          checkpoint: {
            runId: "run-1",
            nodeId: "node-a",
            status: "after_node",
            completedOutputs: {},
            pendingNodeIds: ["node-b"],
            createdAt: "2026-05-30T00:00:00.000Z",
            recoveryCount: 0,
          },
        },
      },
      {
        type: "authority.decision_recorded",
        payload: {
          decision: {
            runId: "run-1",
            nodeId: "node-a",
            toolId: "internal:write-report",
            allowed: false,
            code: "permission_denied",
            message: "permission was not approved",
            permissions: ["write_project_outputs"],
            createdAt: "2026-05-30T00:00:01.000Z",
          },
        },
      },
      {
        type: "recovery.action_applied",
        payload: {
          action: {
            runId: "run-1",
            nodeId: "node-a",
            action: "applied",
            reason: "retry low-risk node once",
            operations: [
              {
                op: "retry_node",
                node_id: "node-a",
                reason: "recoverable tool failure",
              },
            ],
            requiresUserApproval: false,
            createdAt: "2026-05-30T00:00:02.000Z",
            recoveryCount: 1,
          },
        },
      },
    ];

    const next = reduceGraphRunControllerEvents(initial, events);

    expect(next.graph?.graphId).toBe("g1");
    expect(next.runtimeObservability.checkpoints).toHaveLength(1);
    expect(next.runtimeObservability.checkpoints[0].pendingNodeIds).toEqual([
      "node-b",
    ]);
    expect(next.runtimeObservability.authorityDecisions[0].allowed).toBe(false);
    expect(next.runtimeObservability.recoveryActions[0].action).toBe("applied");
    expect(next.dirty).toBe(true);
  });
});
