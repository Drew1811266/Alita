import { useEffect, useRef, type ChangeEvent } from "react";

import type { ResearchChoiceId, ResearchChoicePayload } from "../../shared/events";
import type { ChatAttachment, ChatMessage } from "../../shared/types";
import { AudioTrack } from "../voice/AudioTrack";
import type { DraftSelection } from "../voice/draftInsertion";

export type VoiceInputStatus =
  | "checking"
  | "unavailable"
  | "idle"
  | "recording"
  | "transcribing"
  | "failed";

export type VoiceInputView = {
  available: boolean;
  status: VoiceInputStatus;
  message: string | null;
  elapsedSeconds: number;
  maxSeconds: number;
  levels: number[];
};

export type PendingResearchChoice = ResearchChoicePayload & {
  submittedPayload?: unknown;
};

type ChatPanelProps = {
  messages: ChatMessage[];
  pendingAttachments: ChatAttachment[];
  pendingResearchChoice?: PendingResearchChoice | null;
  draft: string;
  onDraftChange(value: string): void;
  onSend(): void;
  onAddFile(): void;
  onResearchChoice?(choiceId: ResearchChoiceId): void;
  voiceInput?: VoiceInputView;
  onVoiceToggle?(selection: DraftSelection | null): void;
  onDraftSelectionChange?(selection: DraftSelection | null): void;
};

const idleVoiceInput: VoiceInputView = {
  available: true,
  status: "idle",
  message: null,
  elapsedSeconds: 0,
  maxSeconds: 60,
  levels: [],
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
  pendingResearchChoice = null,
  draft,
  onDraftChange,
  onSend,
  onAddFile,
  onResearchChoice = () => undefined,
  voiceInput = idleVoiceInput,
  onVoiceToggle = () => undefined,
  onDraftSelectionChange = () => undefined,
}: ChatPanelProps) {
  const handleDraftChange = (event: ChangeEvent<HTMLTextAreaElement>) => {
    onDraftChange(event.target.value);
  };
  const handleDraftKeyDown = createComposerKeyDownHandler(onSend);
  const messageListRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const explicitDraftSelectionRef = useRef<DraftSelection | null>(null);

  const readTextareaSelection = (): DraftSelection | null => {
    const textarea = textareaRef.current;

    if (!textarea) {
      return null;
    }

    return {
      start: textarea.selectionStart,
      end: textarea.selectionEnd,
    };
  };

  const reportDraftSelection = () => {
    const selection = readTextareaSelection();

    explicitDraftSelectionRef.current = selection;
    onDraftSelectionChange(selection);
  };

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
            {message.sources && message.sources.length > 0 ? (
              <ul className="sourceList" aria-label="Sources">
                {message.sources.map((source, index) => (
                  <li key={`${source.ref ?? index}-${source.url}`}>
                    <span className="sourceRef">{source.ref ?? `S${index + 1}`}</span>
                    <a href={source.url} rel="noreferrer" target="_blank">
                      {source.title}
                    </a>
                  </li>
                ))}
              </ul>
            ) : null}
          </article>
        ))}
      </div>

      {pendingResearchChoice ? (
        <div className="researchChoiceBar" aria-label="Research choices">
          {pendingResearchChoice.choices.map((choice) => (
            <button
              aria-label={`Choose ${choice.label}`}
              className="secondaryButton researchChoiceButton"
              disabled={!pendingResearchChoice.submittedPayload}
              key={choice.id}
              onClick={() => onResearchChoice(choice.id)}
              type="button"
            >
              {choice.label}
            </button>
          ))}
        </div>
      ) : null}

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
          ref={textareaRef}
          id="chat-draft"
          placeholder="输入你的问题或说明要处理的文档任务"
          value={draft}
          onChange={handleDraftChange}
          onClick={reportDraftSelection}
          onFocus={reportDraftSelection}
          onKeyDown={handleDraftKeyDown}
          onKeyUp={reportDraftSelection}
          onSelect={reportDraftSelection}
          rows={4}
        />

        {voiceInput.status === "recording" ? (
          <AudioTrack
            elapsedSeconds={voiceInput.elapsedSeconds}
            maxSeconds={voiceInput.maxSeconds}
            levels={voiceInput.levels}
          />
        ) : null}
        {voiceInput.status === "failed" && voiceInput.message ? (
          <p className="voiceInputError">{voiceInput.message}</p>
        ) : null}

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
            aria-label="语音输入"
            className="secondaryButton voiceButton"
            disabled={!voiceInput.available || voiceInput.status === "transcribing"}
            onClick={() => onVoiceToggle(explicitDraftSelectionRef.current)}
            title={voiceInput.message ?? "语音输入"}
            type="button"
          >
            {voiceInput.status === "recording"
              ? "停止录音"
              : voiceInput.status === "transcribing"
                ? "转写中"
                : "语音"}
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
