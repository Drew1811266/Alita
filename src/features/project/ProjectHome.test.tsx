import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ProjectHome } from "./ProjectHome";

describe("ProjectHome", () => {
  it("renders project actions and preferences entry", () => {
    const markup = renderToStaticMarkup(
      <ProjectHome
        error={null}
        onCreateProject={() => undefined}
        onOpenProject={() => undefined}
        onOpenRecentProject={() => undefined}
        onOpenPreferences={() => undefined}
        recentProjects={["D:\\Projects\\文档整理测试.alita"]}
      />,
    );

    expect(markup).toContain("Alita");
    expect(markup).toContain("新建工程");
    expect(markup).toContain("打开工程");
    expect(markup).toContain("最近工程");
    expect(markup).toContain("首选项");
    expect(markup).toContain("文档整理测试.alita");
  });

  it("renders recent projects as clickable project entries", () => {
    const markup = renderToStaticMarkup(
      <ProjectHome
        error={null}
        onCreateProject={() => undefined}
        onOpenProject={() => undefined}
        onOpenRecentProject={() => undefined}
        onOpenPreferences={() => undefined}
        recentProjects={["D:\\Projects\\Alita\\example.alita"]}
      />,
    );

    expect(markup).toContain("recentProjectButton");
    expect(markup).toContain('type="button"');
    expect(markup).toContain("D:\\Projects\\Alita\\example.alita");
  });
});
