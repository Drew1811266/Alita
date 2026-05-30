import { describe, expect, it } from "vitest";

import {
  createGraphRuntimeControllerState,
  createRuntimeObservabilityState,
  graphRunSettled,
  graphRunStarted,
  reduceRuntimeObservabilityEvents,
} from "./useGraphRuntimeController";

describe("graph runtime controller helpers", () => {
  it("tracks running and cancelling defaults", () => {
    expect(createGraphRuntimeControllerState()).toEqual({
      running: false,
      cancelling: false,
      observability: createRuntimeObservabilityState(),
    });
  });

  it("starts and settles runs without retaining cancellation state", () => {
    expect(graphRunStarted("run-1")).toEqual({
      running: true,
      cancelling: false,
      activeRunId: "run-1",
      observability: createRuntimeObservabilityState(),
    });
    expect(graphRunSettled()).toEqual({
      running: false,
      cancelling: false,
      observability: createRuntimeObservabilityState(),
    });
  });

  it("reduces checkpoint, authority, and recovery events into observability state", () => {
    const next = reduceRuntimeObservabilityEvents(
      createRuntimeObservabilityState(),
      [
        {
          type: "runtime.checkpoint_recorded",
          payload: {
            checkpoint: {
              runId: "run-1",
              nodeId: "node-a",
              status: "before_node",
              completedOutputs: {},
              pendingNodeIds: ["node-a", "node-b"],
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
              toolId: "internal:read",
              allowed: true,
              code: "allowed",
              permissions: ["read_project_files"],
              createdAt: "2026-05-30T00:00:01.000Z",
            },
          },
        },
        {
          type: "recovery.action_proposed",
          payload: {
            action: {
              runId: "run-1",
              nodeId: "node-a",
              action: "proposed",
              reason: "retry suggested",
              operations: [
                {
                  op: "retry_node",
                  node_id: "node-a",
                  reason: "recoverable",
                },
              ],
              requiresUserApproval: false,
              createdAt: "2026-05-30T00:00:02.000Z",
            },
          },
        },
      ],
    );

    expect(next.checkpoints).toHaveLength(1);
    expect(next.authorityDecisions[0].toolId).toBe("internal:read");
    expect(next.recoveryActions[0].action).toBe("proposed");
  });
});
