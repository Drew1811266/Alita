import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AudioTrack } from "./AudioTrack";

describe("AudioTrack", () => {
  it("renders a timer and level bars", () => {
    const markup = renderToStaticMarkup(
      <AudioTrack elapsedSeconds={12} maxSeconds={60} levels={[0.2, 0.5, 0.9]} />,
    );

    expect(markup).toContain("00:12 / 01:00");
    expect((markup.match(/class="voiceLevelBar"/g) ?? []).length).toBe(3);
    expect(markup).toContain("height:50%");
  });
});
