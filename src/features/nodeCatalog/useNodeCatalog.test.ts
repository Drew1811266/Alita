import { describe, expect, it } from "vitest";

import type { NodeCatalogSnapshot } from "../../shared/types";
import {
  createNodeCatalogState,
  createNodeCatalogRequestState,
  nodeCatalogFailed,
  nodeCatalogLoaded,
  nodeCatalogLoading,
  nodeCatalogRequestLoaded,
  nodeCatalogRequestLoading,
  useNodeCatalog,
} from "./useNodeCatalog";

describe("node catalog state helpers", () => {
  it("transitions through loading loaded and failed states", () => {
    const initial = createNodeCatalogState();
    const loading = nodeCatalogLoading(initial);
    const catalog = {
      schemaVersion: 1,
      generatedAt: "2026-06-06T00:00:00+00:00",
      nodes: [],
      diagnostics: [],
      sourceSummary: {
        internalToolCount: 0,
        systemNodeCount: 0,
        mcpNodeCount: 0,
        pluginNodeCount: 0,
      },
    } satisfies NodeCatalogSnapshot;
    const loaded = nodeCatalogLoaded(loading, catalog);
    const failed = nodeCatalogFailed(loaded, "failed");

    expect(loading).toEqual({
      catalog: null,
      loading: true,
      error: null,
    });
    expect(loaded).toEqual({
      catalog,
      loading: false,
      error: null,
    });
    expect(failed).toEqual({
      catalog,
      loading: false,
      error: "failed",
    });
  });

  it("exposes a hook function for catalog loading consumers", () => {
    expect(typeof useNodeCatalog).toBe("function");
  });

  it("ignores stale loaded results from an older refresh request", () => {
    const olderCatalog = catalogSnapshot("older");
    const newerCatalog = catalogSnapshot("newer");

    const initial = createNodeCatalogRequestState();
    const olderLoading = nodeCatalogRequestLoading(initial, 1);
    const newerLoading = nodeCatalogRequestLoading(olderLoading, 2);
    const newerLoaded = nodeCatalogRequestLoaded(newerLoading, 2, newerCatalog);
    const staleLoaded = nodeCatalogRequestLoaded(newerLoaded, 1, olderCatalog);

    expect(staleLoaded.catalog).toBe(newerCatalog);
    expect(staleLoaded.loading).toBe(false);
    expect(staleLoaded.error).toBeNull();
  });
});

function catalogSnapshot(id: string): NodeCatalogSnapshot {
  return {
    schemaVersion: 1,
    generatedAt: "2026-06-06T00:00:00+00:00",
    nodes: [
      {
        nodeId: id,
        kind: "output",
        displayName: id,
        description: id,
        category: "output",
        capabilities: [id],
        inputPorts: [],
        outputPorts: [],
        execution: { type: "output", outputType: "final_response" },
        permissions: {
          permissions: [],
          riskLevel: "low",
          requiresApproval: false,
          filesystem: "none",
          network: "none",
          sandbox: "none",
        },
        examples: [],
        source: "system",
        version: "1.0.0",
        availability: { status: "available" },
      },
    ],
    diagnostics: [],
    sourceSummary: {
      internalToolCount: 0,
      systemNodeCount: 1,
      mcpNodeCount: 0,
      pluginNodeCount: 0,
    },
  };
}
