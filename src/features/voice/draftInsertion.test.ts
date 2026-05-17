import { describe, expect, it } from "vitest";

import { insertTranscriptIntoDraft } from "./draftInsertion";

describe("insertTranscriptIntoDraft", () => {
  it("fills an empty draft", () => {
    expect(
      insertTranscriptIntoDraft({
        currentDraft: "",
        transcript: "请总结这份文档",
        selection: null,
      }),
    ).toBe("请总结这份文档");
  });

  it("appends when there is no selection", () => {
    expect(
      insertTranscriptIntoDraft({
        currentDraft: "先分析结构",
        transcript: "再提炼重点",
        selection: null,
      }),
    ).toBe("先分析结构\n再提炼重点");
  });

  it("inserts at the captured cursor", () => {
    expect(
      insertTranscriptIntoDraft({
        currentDraft: "请  处理",
        transcript: "详细",
        selection: { start: 2, end: 2 },
      }),
    ).toBe("请 详细 处理");
  });

  it("replaces the captured selection", () => {
    expect(
      insertTranscriptIntoDraft({
        currentDraft: "请快速处理",
        transcript: "详细分析",
        selection: { start: 1, end: 5 },
      }),
    ).toBe("请详细分析");
  });

  it("clamps stale selection offsets to the current draft", () => {
    expect(
      insertTranscriptIntoDraft({
        currentDraft: "短文本",
        transcript: "追加内容",
        selection: { start: 99, end: 120 },
      }),
    ).toBe("短文本追加内容");
  });
});
