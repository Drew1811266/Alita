import { describe, expect, it } from "vitest";

import {
  createAuthorityDecisionSnapshot,
  clearPendingPermissionChoices,
  createPendingPermissionChoiceSnapshot,
  reduceAuthorityDecisionSnapshotEvents,
} from "./usePermissionController";

describe("permission controller helpers", () => {
  it("starts without pending permission choices", () => {
    expect(createPendingPermissionChoiceSnapshot()).toEqual({
      pendingResearchChoice: null,
      pendingGraphOverwriteChoice: null,
    });
  });

  it("clears coordinated pending permission choices together", () => {
    expect(
      clearPendingPermissionChoices({
        pendingResearchChoice: { taskId: "research" },
        pendingGraphOverwriteChoice: { taskId: "overwrite" },
      }),
    ).toEqual({
      pendingResearchChoice: null,
      pendingGraphOverwriteChoice: null,
    });
  });

  it("tracks authority decisions and exposes the latest denied decision", () => {
    const next = reduceAuthorityDecisionSnapshotEvents(
      createAuthorityDecisionSnapshot(),
      [
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
              createdAt: "2026-05-30T00:00:00.000Z",
            },
          },
        },
        {
          type: "authority.decision_recorded",
          payload: {
            decision: {
              runId: "run-1",
              nodeId: "node-b",
              toolId: "internal:write",
              allowed: false,
              code: "permission_denied",
              message: "write_project_outputs was not approved",
              permissions: ["write_project_outputs"],
              createdAt: "2026-05-30T00:00:01.000Z",
            },
          },
        },
      ],
    );

    expect(next.authorityDecisions).toHaveLength(2);
    expect(next.latestDeniedAuthorityDecision?.toolId).toBe("internal:write");
  });
});
