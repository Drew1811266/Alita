import { describe, expect, it } from "vitest";

import {
  createGraphRuntimeControllerState,
  graphRunSettled,
  graphRunStarted,
} from "./useGraphRuntimeController";

describe("graph runtime controller helpers", () => {
  it("tracks running and cancelling defaults", () => {
    expect(createGraphRuntimeControllerState()).toEqual({
      running: false,
      cancelling: false,
    });
  });

  it("starts and settles runs without retaining cancellation state", () => {
    expect(graphRunStarted("run-1")).toEqual({
      running: true,
      cancelling: false,
      activeRunId: "run-1",
    });
    expect(graphRunSettled()).toEqual({
      running: false,
      cancelling: false,
    });
  });
});
