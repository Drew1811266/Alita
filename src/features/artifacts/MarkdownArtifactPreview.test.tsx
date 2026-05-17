import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MarkdownArtifactPreview } from "./MarkdownArtifactPreview";

describe("MarkdownArtifactPreview", () => {
  it("renders markdown headings as structured HTML", () => {
    const markup = renderToStaticMarkup(
      <MarkdownArtifactPreview content={"# Report\n\nAlpha"} />,
    );

    expect(markup).toContain("artifactPreviewMarkdown");
    expect(markup).toContain("<h1>Report</h1>");
    expect(markup).toContain("<p>Alpha</p>");
  });
});
