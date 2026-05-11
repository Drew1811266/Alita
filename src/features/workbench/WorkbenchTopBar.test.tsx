import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { WorkbenchTopBar } from "./WorkbenchTopBar";

describe("WorkbenchTopBar", () => {
  it("renders project name, dirty state, and actions", () => {
    const markup = renderToStaticMarkup(
      <WorkbenchTopBar
        dirty
        onOpenPreferences={() => undefined}
        onSave={() => undefined}
        onSaveAs={() => undefined}
        projectName="文档整理测试"
        saving={false}
      />,
    );

    expect(markup).toContain("文档整理测试");
    expect(markup).toContain("未保存");
    expect(markup).toContain("保存");
    expect(markup).toContain("另存为");
    expect(markup).toContain("首选项");
  });
});
