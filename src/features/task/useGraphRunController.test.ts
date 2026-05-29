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
});
