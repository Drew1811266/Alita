import { useEffect, useRef, type ChangeEvent } from "react";

import type { ChatAttachment, ChatMessage } from "../../shared/types";

type ChatPanelProps = {
  messages: ChatMessage[];
  pendingAttachments: ChatAttachment[];
  draft: string;
  onDraftChange(value: string): void;
  onSend(): void;
  onAddFile(): void;
};

const roleLabels: Record<ChatMessage["role"], string> = {
  user: "用户",
  assistant: "助手",
  system: "系统",
};

type ComposerKeyEvent = {
  key: string;
  shiftKey: boolean;
  isComposing?: boolean;
  nativeEvent?: {
    isComposing?: boolean;
  };
  preventDefault(): void;
};

type ScrollableMessageList = {
  scrollHeight: number;
  scrollTop: number;
};

export function createComposerKeyDownHandler(onSend: () => void) {
  return (event: ComposerKeyEvent) => {
    const isComposing = event.isComposing || event.nativeEvent?.isComposing;
    if (event.key !== "Enter" || event.shiftKey || isComposing) {
      return;
    }

    event.preventDefault();
    onSend();
  };
}

export function scrollMessageListToBottom(
  messageList: ScrollableMessageList | null,
) {
  if (!messageList) {
    return;
  }

  messageList.scrollTop = messageList.scrollHeight;
}

export function ChatPanel({
  messages,
  pendingAttachments,
  draft,
  onDraftChange,
  onSend,
  onAddFile,
}: ChatPanelProps) {
  const handleDraftChange = (event: ChangeEvent<HTMLTextAreaElement>) => {
    onDraftChange(event.target.value);
  };
  const handleDraftKeyDown = createComposerKeyDownHandler(onSend);
  const messageListRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollMessageListToBottom(messageListRef.current);
  }, [messages]);

  return (
    <section className="chatPanel" aria-labelledby="chat-panel-title">
      <header className="chatHeader">
        <div>
          <h1 id="chat-panel-title">对话</h1>
          <p>把文档任务交给 Agent，确认后生成右侧流程。</p>
        </div>
        <span className="statusBadge">开发版</span>
      </header>

      <div className="messageList" aria-label="对话消息" ref={messageListRef}>
        {messages.map((message) => (
          <article
            className={`messageItem messageItem-${message.role}`}
            key={message.messageId}
          >
            <div className="messageMeta">
              <span>{roleLabels[message.role]}</span>
            </div>
            <p>{message.content}</p>
            {message.attachments.length > 0 ? (
              <ul className="attachmentList" aria-label="消息附件">
                {message.attachments.map((attachment) => (
                  <li key={attachment.attachmentId}>{attachment.name}</li>
                ))}
              </ul>
            ) : null}
          </article>
        ))}
      </div>

      <div className="composer" aria-label="消息编辑器">
        {pendingAttachments.length > 0 ? (
          <div className="pendingAttachments" aria-label="待发送附件">
            {pendingAttachments.map((attachment) => (
              <span className="attachmentChip" key={attachment.attachmentId}>
                {attachment.name}
              </span>
            ))}
          </div>
        ) : null}

        <label className="composerLabel" htmlFor="chat-draft">
          消息内容
        </label>
        <textarea
          id="chat-draft"
          placeholder="输入你的问题或说明要处理的文档任务"
          value={draft}
          onChange={handleDraftChange}
          onKeyDown={handleDraftKeyDown}
          rows={4}
        />

        <div className="composerActions">
          <button
            aria-label="添加文件"
            className="secondaryButton"
            onClick={onAddFile}
            type="button"
          >
            添加文件
          </button>
          <button
            aria-label="发送消息"
            className="primaryButton"
            onClick={onSend}
            type="button"
          >
            发送
          </button>
        </div>
      </div>
    </section>
  );
}
