import { describe, expect, it } from "vitest";

import {
  createProjectControllerState,
  rememberRecentProject,
} from "./useProjectController";

describe("project controller helpers", () => {
  it("starts without an active project", () => {
    expect(createProjectControllerState()).toMatchObject({
      activeProject: null,
      projectWarnings: [],
      projectError: null,
      saving: false,
      recentProjects: [],
    });
  });

  it("moves opened projects to the front and deduplicates", () => {
    expect(
      rememberRecentProject(["D:\\A.alita", "D:\\B.alita"], "D:\\B.alita"),
    ).toEqual(["D:\\B.alita", "D:\\A.alita"]);
  });
});
