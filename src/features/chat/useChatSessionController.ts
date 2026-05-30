import { useCallback, useRef, useState } from "react";

import {
  insertTranscriptIntoDraft,
  type DraftSelection,
} from "../voice/draftInsertion";
import type {
  ChatAttachment,
  ChatMessage,
  ProjectAttachmentRef,
} from "../../shared/types";

export const initialMessages: ChatMessage[] = [
  {
    messageId: "system-initial",
    role: "system",
    content: "开发版对话已启动。请描述你的文档处理目标。",
    attachments: [],
    createdAt: "2026-05-09T00:00:00.000Z",
  },
  {
    messageId: "assistant-initial",
    role: "assistant",
    content: "你可以先添加一个文档文件，再说明需要摘要、改写或提取信息。",
    attachments: [],
    createdAt: "2026-05-09T00:00:01.000Z",
  },
];

export type ChatSessionState = {
  draft: string;
  pendingAttachments: ChatAttachment[];
  contextAttachments: ChatAttachment[];
};

export function createChatSessionState(): ChatSessionState {
  return {
    draft: "",
    pendingAttachments: [],
    contextAttachments: [],
  };
}

export function createId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

export function createMessage(
  role: ChatMessage["role"],
  content: string,
  attachments: ChatAttachment[] = [],
): ChatMessage {
  return {
    messageId: createId(role),
    role,
    content,
    attachments,
    createdAt: new Date().toISOString(),
  };
}

export function appendPendingAttachments(
  current: ChatAttachment[],
  selectedAttachments: ChatAttachment[],
): ChatAttachment[] {
  const existingPaths = new Set(current.map((attachment) => attachment.path));
  return [
    ...current,
    ...selectedAttachments.filter(
      (attachment) => !existingPaths.has(attachment.path),
    ),
  ];
}

export function collectProjectAttachments(
  existing: ProjectAttachmentRef[],
  contextAttachments: ChatAttachment[],
  messages: ChatMessage[],
): ProjectAttachmentRef[] {
  const byPath = new Map<string, ProjectAttachmentRef>();

  for (const attachment of existing) {
    byPath.set(attachment.path, attachment);
  }

  for (const attachment of [
    ...contextAttachments,
    ...messages.flatMap((message) => message.attachments),
  ]) {
    if (!byPath.has(attachment.path)) {
      byPath.set(attachment.path, {
        ...attachment,
        originalPath: attachment.path,
        fileExists: true,
      });
    }
  }

  return [...byPath.values()];
}

export function selectAgentAttachments({
  content,
  sentAttachments,
  contextAttachments,
}: {
  content: string;
  sentAttachments: ChatAttachment[];
  contextAttachments: ChatAttachment[];
}): ChatAttachment[] {
  if (sentAttachments.length > 0) {
    return sentAttachments;
  }
  if (contextAttachments.length === 0) {
    return [];
  }
  if (referencesContextAttachment(content, contextAttachments)) {
    return contextAttachments;
  }
  return [];
}

function referencesContextAttachment(
  content: string,
  contextAttachments: ChatAttachment[],
): boolean {
  const normalized = content.trim().toLowerCase();
  if (!normalized) {
    return false;
  }

  const explicitReferences = [
    "attached",
    "attachment",
    "uploaded",
    "this file",
    "the file",
    "this document",
    "the document",
    "\u9644\u4ef6",
    "\u4e0a\u4f20",
    "\u8fd9\u4e2a\u6587\u4ef6",
    "\u8fd9\u4efd\u6587\u4ef6",
    "\u8fd9\u4e2a\u6587\u6863",
    "\u8fd9\u4efd\u6587\u6863",
    "\u521a\u624d\u7684\u6587\u4ef6",
    "\u521a\u624d\u7684\u6587\u6863",
  ];

  if (explicitReferences.some((reference) => normalized.includes(reference))) {
    return true;
  }

  return contextAttachments.some((attachment) => {
    const name = attachment.name.toLowerCase();
    const pathName = attachment.path.split(/[\\/]/).pop()?.toLowerCase() ?? "";
    return Boolean(
      (name && normalized.includes(name)) ||
        (pathName && normalized.includes(pathName)),
    );
  });
}

export function useChatSessionController() {
  const [state, setState] = useState(createChatSessionState);
  const messagesRef = useRef<ChatMessage[]>(initialMessages);

  const setDraft = useCallback((draft: string) => {
    setState((current) => ({ ...current, draft }));
  }, []);

  const applyVoiceTranscript = useCallback(
    (transcript: string, selection: DraftSelection | null) => {
      setState((current) => ({
        ...current,
        draft: insertTranscriptIntoDraft({
          currentDraft: current.draft,
          transcript,
          selection,
        }),
      }));
    },
    [],
  );

  const setPendingAttachments = useCallback(
    (
      action:
        | ChatAttachment[]
        | ((current: ChatAttachment[]) => ChatAttachment[]),
    ) => {
      setState((current) => ({
        ...current,
        pendingAttachments:
          typeof action === "function"
            ? action(current.pendingAttachments)
            : action,
      }));
    },
    [],
  );

  const setContextAttachments = useCallback(
    (contextAttachments: ChatAttachment[]) => {
      setState((current) => ({ ...current, contextAttachments }));
    },
    [],
  );

  const addPendingAttachments = useCallback(
    (selectedAttachments: ChatAttachment[]) => {
      setPendingAttachments((current) =>
        appendPendingAttachments(current, selectedAttachments),
      );
    },
    [setPendingAttachments],
  );

  return {
    state,
    messagesRef,
    setDraft,
    applyVoiceTranscript,
    setPendingAttachments,
    setContextAttachments,
    addPendingAttachments,
  };
}
