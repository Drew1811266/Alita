import { describe, expect, it } from "vitest";

import {
  clearPendingPermissionChoices,
  createPendingPermissionChoiceSnapshot,
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
});
