import { describe, expect, it } from "vitest";

import type { NodeCatalogSnapshot } from "../../shared/types";
import {
  createNodeCatalogState,
  nodeCatalogFailed,
  nodeCatalogLoaded,
  nodeCatalogLoading,
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
});
