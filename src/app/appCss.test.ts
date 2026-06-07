import { describe, expect, it } from "vitest";

// @ts-expect-error Vitest runs in Node, but the app tsconfig intentionally only includes browser types.
import { readFileSync } from "node:fs";

const appCss = readFileSync("src/app/app.css", "utf8");

describe("app workbench layout CSS", () => {
  it("uses equal-width desktop columns for chat, canvas, and preview", () => {
    const appShellRule = appCss.match(/\.appShell\s*\{[\s\S]*?\}/)?.[0];

    expect(appShellRule).toBeDefined();
    expect(appShellRule).toContain(
      "grid-template-columns: repeat(3, minmax(0, 1fr));",
    );
  });

  it("styles planning, permission, risk, and estimate canvas states", () => {
    expect(appCss).toContain(".agentNode-planningQuiet");
    expect(appCss).toContain(".agentNode-needsPermission");
    expect(appCss).toContain(".agentNode-riskHigh");
    expect(appCss).toContain(".agentNodeEstimateChips");
    expect(appCss).toContain("grid-template-rows: auto auto 1fr auto;");
  });

  it("bounds popover code previews", () => {
    const codePreviewRule = appCss.match(
      /\.nodePopoverCodePreview\s*\{[\s\S]*?\}/,
    )?.[0];

    expect(codePreviewRule).toBeDefined();
    expect(codePreviewRule).toContain("max-height:");
    expect(codePreviewRule).toContain("overflow: auto;");
    expect(codePreviewRule).toContain("font-family:");
  });

  it("keeps the node catalog list as the remaining-height scroll region", () => {
    const panelRule = appCss.match(/\.nodeCatalogPanel\s*\{[\s\S]*?\}/)?.[0];
    const listRule = appCss.match(/\.nodeCatalogList\s*\{[\s\S]*?\}/)?.[0];

    expect(panelRule).toBeDefined();
    expect(panelRule).toContain("display: flex;");
    expect(panelRule).toContain("flex-direction: column;");
    expect(panelRule).not.toContain("grid-template-rows:");

    expect(listRule).toBeDefined();
    expect(listRule).toContain("flex: 1 1 auto;");
    expect(listRule).toContain("min-height: 0;");
    expect(listRule).toContain("overflow: auto;");
  });
});
