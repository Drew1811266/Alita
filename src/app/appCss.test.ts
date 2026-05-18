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
});
