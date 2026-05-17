import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  ChatPanel,
  createComposerKeyDownHandler,
  type VoiceInputView,
  scrollMessageListToBottom,
} from "./ChatPanel";
import type { ChatAttachment, ChatMessage } from "../../shared/types";

const sourceAttachment: ChatAttachment = {
  attachmentId: "attachment-source-doc",
  name: "需求说明.docx",
  path: "C:\\Users\\Drew\\Documents\\需求说明.docx",
  sizeBytes: 18432,
  mimeType:
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
};

const pendingAttachment: ChatAttachment = {
  attachmentId: "attachment-pending-doc",
  name: "待处理文档.docx",
  path: "C:\\Users\\Drew\\Documents\\待处理文档.docx",
  sizeBytes: 24576,
  mimeType:
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
};

const messages: ChatMessage[] = [
  {
    messageId: "system-1",
    role: "system",
    content: "系统已准备好处理文档。",
    attachments: [],
    createdAt: "2026-05-09T08:00:00.000Z",
  },
  {
    messageId: "user-1",
    role: "user",
    content: "请分析这份文档。",
    attachments: [sourceAttachment],
    createdAt: "2026-05-09T08:01:00.000Z",
  },
  {
    messageId: "assistant-1",
    role: "assistant",
    content: "我会先读取文档内容。",
    attachments: [],
    createdAt: "2026-05-09T08:02:00.000Z",
  },
];

const idleVoiceInput: VoiceInputView = {
  available: true,
  status: "idle",
  message: null,
  elapsedSeconds: 0,
  maxSeconds: 60,
  levels: [],
};

function renderChatPanel(voiceInput: VoiceInputView = idleVoiceInput) {
  return renderToStaticMarkup(
    <ChatPanel
      messages={messages}
      pendingAttachments={[pendingAttachment]}
      draft="请总结重点"
      onDraftChange={() => undefined}
      onSend={() => undefined}
      onAddFile={() => undefined}
      voiceInput={voiceInput}
      onVoiceToggle={() => undefined}
      onDraftSelectionChange={() => undefined}
    />,
  );
}

describe("ChatPanel", () => {
  it("renders message content and message attachment filenames", () => {
    const markup = renderChatPanel();

    expect(markup).toContain("系统已准备好处理文档。");
    expect(markup).toContain("请分析这份文档。");
    expect(markup).toContain("我会先读取文档内容。");
    expect(markup).toContain("需求说明.docx");
  });

  it("renders pending attachments and the Chinese composer placeholder", () => {
    const markup = renderChatPanel();

    expect(markup).toContain("待处理文档.docx");
    expect(markup).toContain("输入你的问题或说明要处理的文档任务");
  });

  it("renders add-file, voice, and send buttons as visible Chinese actions", () => {
    const markup = renderChatPanel();

    expect(markup).toContain("添加文件");
    expect(markup).toContain("发送");
    expect(markup).toContain("语音");
    expect((markup.match(/type="button"/g) ?? []).length).toBe(3);
    expect(markup).toContain('aria-label="添加文件"');
    expect(markup.indexOf('aria-label="添加文件"')).toBeLessThan(
      markup.indexOf('aria-label="语音输入"'),
    );
    expect(markup.indexOf('aria-label="语音输入"')).toBeLessThan(
      markup.indexOf('aria-label="发送消息"'),
    );
    expect(markup).toContain('aria-label="发送消息"');
  });

  it("disables voice input when the voice model is unavailable", () => {
    const markup = renderChatPanel({
      available: false,
      status: "unavailable",
      message: "未配置语音模型",
      elapsedSeconds: 0,
      maxSeconds: 60,
      levels: [],
    });

    expect(markup).toContain(
      '<button aria-label="语音输入" class="secondaryButton voiceButton" disabled="" title="未配置语音模型" type="button">',
    );
    expect(markup).toContain("未配置语音模型");
  });

  it("renders the recording track while voice input is recording", () => {
    const markup = renderChatPanel({
      available: true,
      status: "recording",
      message: "录音中",
      elapsedSeconds: 8,
      maxSeconds: 60,
      levels: [0.2, 0.9],
    });

    expect(markup).toContain("00:08 / 01:00");
    expect(markup).toContain("voiceLevelBar");
  });

  it("sends the message on Enter without preventing Shift+Enter newlines", () => {
    let sendCount = 0;
    let preventDefaultCount = 0;
    const handleKeyDown = createComposerKeyDownHandler(() => {
      sendCount += 1;
    });

    handleKeyDown({
      key: "Enter",
      shiftKey: false,
      isComposing: false,
      preventDefault: () => {
        preventDefaultCount += 1;
      },
    });

    handleKeyDown({
      key: "Enter",
      shiftKey: true,
      isComposing: false,
      preventDefault: () => {
        preventDefaultCount += 1;
      },
    });

    expect(sendCount).toBe(1);
    expect(preventDefaultCount).toBe(1);
  });

  it("does not send while an input method is composing text", () => {
    let sendCount = 0;
    const handleKeyDown = createComposerKeyDownHandler(() => {
      sendCount += 1;
    });

    handleKeyDown({
      key: "Enter",
      shiftKey: false,
      isComposing: true,
      preventDefault: () => undefined,
    });

    expect(sendCount).toBe(0);
  });

  it("scrolls the message list to the newest message", () => {
    const messageList = {
      scrollHeight: 1200,
      scrollTop: 240,
    };

    scrollMessageListToBottom(messageList);

    expect(messageList.scrollTop).toBe(1200);
  });
});
