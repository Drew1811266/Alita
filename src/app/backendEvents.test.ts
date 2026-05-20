import { describe, expect, it } from "vitest";

import { reduceBackendEvents } from "./backendEvents";
import type { BackendEvent } from "../shared/events";
import type { ChatMessage, NodeGraph } from "../shared/types";

const existingMessage: ChatMessage = {
  messageId: "user-1",
  role: "user",
  content: "你好",
  attachments: [],
  createdAt: "2026-05-09T12:00:00.000Z",
};

const assistantMessage: ChatMessage = {
  messageId: "assistant-1",
  role: "assistant",
  content: "你好，我是本地模型。",
  attachments: [],
  createdAt: "2026-05-09T12:00:01.000Z",
};

const graph: NodeGraph = {
  graphId: "task-1-graph",
  nodes: [],
  edges: [],
};

const graphWithNode: NodeGraph = {
  graphId: "task-1-graph",
  nodes: [
    {
      nodeId: "document-parse",
      nodeType: "fixed_tool",
      displayName: "解析文档",
      status: "waiting",
      inputPorts: [],
      outputPorts: [],
      dependencies: [],
      toolRef: "document.extract_text",
      summary: "读取正文",
      createdBy: "agent",
      artifactRefs: [],
      retryCount: 0,
      position: { x: 0, y: 0 },
    },
  ],
  edges: [],
};

function createAssistantMessage(content: string): ChatMessage {
  return {
    messageId: `assistant-generated-${content.length}`,
    role: "assistant",
    content,
    attachments: [],
    createdAt: "2026-05-09T12:00:02.000Z",
  };
}

describe("reduceBackendEvents", () => {
  it("appends local model messages from message.created events", () => {
    const events: BackendEvent[] = [
      {
        type: "message.created",
        payload: {
          message: assistantMessage,
        },
      },
    ];

    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph: null,
        dirty: false,
      },
      events,
      createAssistantMessage,
    );

    expect(result.messages).toEqual([existingMessage, assistantMessage]);
    expect(result.graph).toBeNull();
    expect(result.dirty).toBe(true);
  });

  it("keeps existing input and graph responses working", () => {
    const events: BackendEvent[] = [
      {
        type: "input.required",
        payload: {
          prompt: "请把需要处理的文件添加到聊天框里。",
          missing: ["document_file"],
        },
      },
      {
        type: "node_graph.created",
        payload: {
          graph,
        },
      },
    ];

    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph: null,
        dirty: false,
      },
      events,
      createAssistantMessage,
    );

    expect(result.messages.map((message) => message.content)).toEqual([
      "你好",
      "请把需要处理的文件添加到聊天框里。",
      "已生成右侧工具流程。",
    ]);
    expect(result.graph).toBe(graph);
    expect(result.dirty).toBe(true);
  });

  it("applies streaming message lifecycle events", () => {
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph: null,
        dirty: false,
      },
      [
        {
          type: "message.started",
          payload: {
            message: {
              ...assistantMessage,
              content: "",
            },
          },
        },
        {
          type: "message.delta",
          payload: {
            messageId: "assistant-1",
            delta: "你好",
          },
        },
        {
          type: "message.delta",
          payload: {
            messageId: "assistant-1",
            delta: "，本地模型",
          },
        },
        {
          type: "message.completed",
          payload: {
            messageId: "assistant-1",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.messages).toHaveLength(2);
    expect(result.messages[1].content).toBe("你好，本地模型");
    expect(result.dirty).toBe(true);
  });

  it("updates node status and artifacts from graph run events", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph: graphWithNode,
        dirty: false,
      },
      [
        { type: "node.running", payload: { nodeId: "document-parse" } },
        {
          type: "node.completed",
          payload: {
            nodeId: "document-parse",
            artifactRefs: ["D:\\Project\\artifacts\\report.md"],
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.graph?.nodes[0].status).toBe("completed");
    expect(result.graph?.nodes[0].artifactRefs).toEqual([
      "D:\\Project\\artifacts\\report.md",
    ]);
    expect(result.dirty).toBe(true);
  });

  it("adds a chat notice when an artifact is created", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph: graphWithNode,
        dirty: false,
      },
      [
        {
          type: "artifact.created",
          payload: {
            artifactId: "report",
            path: "D:\\Project\\artifacts\\report.md",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.messages[0].content).toContain("D:\\Project\\artifacts\\report.md");
    expect(result.dirty).toBe(true);
  });

  it("records the active run when run.started is received", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph: null,
        dirty: false,
        activeRunId: null,
      },
      [
        {
          type: "run.started",
          payload: {
            runId: "run-1",
            taskId: "task-1",
            startedAt: "2026-05-10T00:00:00.000Z",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.activeRunId).toBe("run-1");
    expect(result.dirty).toBe(true);
  });

  it("stores the last node run record on the matching node", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph: graphWithNode,
        dirty: false,
        activeRunId: "run-1",
      },
      [
        {
          type: "node.run_recorded",
          payload: {
            record: {
              nodeRunId: "nr-1",
              runId: "run-1",
              nodeId: "document-parse",
              status: "failed",
              startedAt: "2026-05-10T00:00:00.000Z",
              completedAt: "2026-05-10T00:00:01.000Z",
              artifactRefs: [],
              error: "读取失败",
            },
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.graph?.nodes[0].lastRun?.error).toBe("读取失败");
    expect(result.graph?.nodes[0].status).toBe("failed");
  });

  it("stores a minimal failed last run from node.failed events", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph: graphWithNode,
        dirty: false,
        activeRunId: "run-1",
      },
      [
        {
          type: "node.failed",
          payload: {
            nodeId: "document-parse",
            taskId: "task-1",
            runId: "run-1",
            error: "tool disabled",
            errorCode: "tool_disabled",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.graph?.nodes[0].status).toBe("failed");
    expect(result.graph?.nodes[0].lastRun?.runId).toBe("run-1");
    expect(result.graph?.nodes[0].lastRun?.error).toBe("tool disabled");
    expect(result.graph?.nodes[0].lastRun?.errorCode).toBe("tool_disabled");
  });

  it("marks a node as needing permission when permission.required is received", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph: graphWithNode,
        dirty: false,
        activeRunId: "run-1",
      },
      [
        {
          type: "permission.required",
          payload: {
            nodeId: "document-parse",
            taskId: "task-1",
            runId: "run-1",
            permissions: ["network"],
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.graph?.nodes[0].status).toBe("needs_permission");
    expect(result.graph?.nodes[0].scriptReview).toEqual({
      status: "reviewing",
      summary: "节点需要授权后才能继续执行。",
      permissions: ["network"],
    });
  });

  it("adds completed runs to run history", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph: null,
        dirty: false,
        activeRunId: "run-1",
        runHistory: [],
      },
      [
        {
          type: "task.completed",
          payload: { taskId: "task-1", runId: "run-1" },
        },
      ],
      createAssistantMessage,
    );

    expect(result.runHistory?.[0].runId).toBe("run-1");
    expect(result.runHistory?.[0].status).toBe("completed");
  });
});
