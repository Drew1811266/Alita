import { invoke } from "@tauri-apps/api/core";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  cancelNodeGraphRun,
  createSseEventParser,
  submitUserMessage,
  runNodeGraphStream,
  toSidecarMessageForTest,
} from "./useTaskEvents";
import type { BackendEvent } from "../../shared/events";
import type { NodeGraph } from "../../shared/types";

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(),
}));

const invokeMock = vi.mocked(invoke);

afterEach(() => {
  delete (globalThis as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
  vi.restoreAllMocks();
});

describe("createSseEventParser", () => {
  it("parses backend events split across SSE chunks", () => {
    const events: BackendEvent[] = [];
    const parser = createSseEventParser((event) => {
      events.push(event);
    });

    parser(
      'data: {"type":"message.started","payload":{"message":{"messageId":"assistant-1","role":"assistant","content":"","attachments":[],"createdAt":"2026-05-10T00:00:00.000Z"}}}\n\n' +
        'data: {"type":"message.delta","payload":{"messageId":"assistant-1","delta":"你',
    );
    parser('好"}}\n\n');
    parser('data: {"type":"message.completed","payload":{"messageId":"assistant-1"}}\n\n');

    expect(events.map((event) => event.type)).toEqual([
      "message.started",
      "message.delta",
      "message.completed",
    ]);
    expect(events[1]).toEqual({
      type: "message.delta",
      payload: {
        messageId: "assistant-1",
        delta: "你好",
      },
    });
  });
});

describe("runNodeGraphStream", () => {
  it("includes model session id in sidecar message payload", () => {
    expect(
      toSidecarMessageForTest({
        taskId: "task-1",
        content: "hello",
        attachments: [],
        modelSessionId: "model-session-1",
      }),
    ).toEqual({
      task_id: "task-1",
      content: "hello",
      attachments: [],
      model_session_id: "model-session-1",
    });
  });

  it("posts model session ids with sidecar message requests", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), {
        headers: { "Content-Type": "application/json" },
      }),
    );

    await submitUserMessage({
      taskId: "task-1",
      content: "Run this",
      attachments: [],
      modelSessionId: "session-1",
    });

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      task_id: "task-1",
      model_session_id: "session-1",
    });
  });

  it("posts null model session ids with sidecar message requests when omitted", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), {
        headers: { "Content-Type": "application/json" },
      }),
    );

    await submitUserMessage({
      taskId: "task-1",
      content: "Run this",
      attachments: [],
    });

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      task_id: "task-1",
      model_session_id: null,
    });
  });

  it("posts Tauri message requests with model session ids directly to the sidecar", async () => {
    Object.defineProperty(globalThis, "__TAURI_INTERNALS__", {
      value: {},
      configurable: true,
    });
    invokeMock.mockResolvedValue("sidecar-token");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), {
        headers: { "Content-Type": "application/json" },
      }),
    );

    await submitUserMessage({
      taskId: "task-1",
      content: "Run this",
      attachments: [],
      modelSessionId: "session-1",
    });

    expect(invokeMock).toHaveBeenCalledWith("get_sidecar_auth_token");
    expect(invokeMock).not.toHaveBeenCalledWith(
      "submit_user_message",
      expect.anything(),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/agent/message",
      expect.objectContaining({
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Alita-Sidecar-Token": "sidecar-token",
        },
      }),
    );
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      task_id: "task-1",
      model_session_id: "session-1",
    });
  });

  it("posts Tauri message requests with whitespace model session ids directly to the sidecar", async () => {
    Object.defineProperty(globalThis, "__TAURI_INTERNALS__", {
      value: {},
      configurable: true,
    });
    invokeMock.mockResolvedValue("sidecar-token");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), {
        headers: { "Content-Type": "application/json" },
      }),
    );

    await submitUserMessage({
      taskId: "task-1",
      content: "Run this",
      attachments: [],
      modelSessionId: "   ",
    });

    expect(invokeMock).toHaveBeenCalledWith("get_sidecar_auth_token");
    expect(invokeMock).not.toHaveBeenCalledWith(
      "submit_user_message",
      expect.anything(),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/agent/message",
      expect.objectContaining({
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Alita-Sidecar-Token": "sidecar-token",
        },
      }),
    );
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      task_id: "task-1",
      model_session_id: "   ",
    });
  });

  it.each([undefined, null] as const)(
    "uses the Tauri command for absent model session ids (%s)",
    async (modelSessionId) => {
      Object.defineProperty(globalThis, "__TAURI_INTERNALS__", {
        value: {},
        configurable: true,
      });
      invokeMock.mockResolvedValue([]);
      const fetchMock = vi.spyOn(globalThis, "fetch");
      const payload = {
        taskId: "task-1",
        content: "Run this",
        attachments: [],
        modelSessionId,
      };

      await submitUserMessage(payload);

      expect(fetchMock).not.toHaveBeenCalled();
      expect(invokeMock).toHaveBeenCalledWith("submit_user_message", {
        payload,
      });
    },
  );

  it("posts the graph and attachments to the sidecar stream endpoint", async () => {
    const events: BackendEvent[] = [];
    const graph: NodeGraph = {
      graphId: "graph-1",
      nodes: [],
      edges: [],
    };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(
          'data: {"type":"task.completed","payload":{"taskId":"task-1"}}\n\n',
        ),
      );

    await runNodeGraphStream(
      {
        runId: "run-1",
        taskId: "task-1",
        projectPath: "D:\\Project\\demo.alita",
        graph,
        mode: { type: "full" },
        attachments: [
          {
            attachmentId: "a1",
            name: "input.md",
            path: "D:\\Project\\input.md",
            sizeBytes: 12,
            mimeType: "text/markdown",
          },
        ],
      },
      (event) => events.push(event),
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/agent/graph/run/stream",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          task_id: "task-1",
          run_id: "run-1",
          project_path: "D:\\Project\\demo.alita",
          graph,
          mode: { type: "full" },
          disabled_tool_ids: [],
          approved_permissions: [],
          model_session_id: null,
          attachments: [
            {
              attachment_id: "a1",
              name: "input.md",
              path: "D:\\Project\\input.md",
              size_bytes: 12,
              mime_type: "text/markdown",
            },
          ],
        }),
      }),
    );
    expect(events).toEqual([
      {
        type: "task.completed",
        payload: { taskId: "task-1" },
      },
    ]);
  });

  it("posts retry mode when running failed nodes", async () => {
    const graph: NodeGraph = { graphId: "graph-1", nodes: [], edges: [] };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(
          'data: {"type":"run.started","payload":{"runId":"run-2","taskId":"task-1","startedAt":"2026-05-10T00:00:00.000Z"}}\n\n',
        ),
      );

    await runNodeGraphStream(
      {
        runId: "run-2",
        taskId: "task-1",
        projectPath: "D:\\Project\\demo.alita",
        graph,
        attachments: [],
        mode: { type: "failed_only", sourceRunId: "run-1" },
      },
      () => undefined,
    );

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      run_id: "run-2",
      mode: { type: "failed_only", source_run_id: "run-1" },
    });
  });

  it("posts disabled tool ids with graph run requests", async () => {
    const graph: NodeGraph = { graphId: "graph-1", nodes: [], edges: [] };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(
          'data: {"type":"run.started","payload":{"runId":"run-1","taskId":"task-1","startedAt":"2026-05-10T00:00:00.000Z"}}\n\n',
        ),
      );

    await runNodeGraphStream(
      {
        runId: "run-1",
        taskId: "task-1",
        projectPath: "D:\\Project\\demo.alita",
        graph,
        attachments: [],
        disabledToolIds: ["document.disabled"],
        mode: { type: "full" },
      },
      () => undefined,
    );

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      disabled_tool_ids: ["document.disabled"],
    });
  });

  it("posts approved permissions with graph run requests", async () => {
    const graph: NodeGraph = { graphId: "graph-1", nodes: [], edges: [] };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(
          'data: {"type":"run.started","payload":{"runId":"run-1","taskId":"task-1","startedAt":"2026-05-10T00:00:00.000Z"}}\n\n',
        ),
      );

    await runNodeGraphStream(
      {
        runId: "run-1",
        taskId: "task-1",
        projectPath: "D:\\Project\\demo.alita",
        graph,
        attachments: [],
        approvedPermissions: ["network"],
        mode: { type: "full" },
      },
      () => undefined,
    );

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      approved_permissions: ["network"],
    });
  });

  it("posts model session ids with graph run requests", async () => {
    const graph: NodeGraph = { graphId: "graph-1", nodes: [], edges: [] };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(
          'data: {"type":"run.started","payload":{"runId":"run-1","taskId":"task-1","startedAt":"2026-05-10T00:00:00.000Z"}}\n\n',
        ),
      );

    await runNodeGraphStream(
      {
        runId: "run-1",
        taskId: "task-1",
        projectPath: "D:\\Project\\demo.alita",
        graph,
        attachments: [],
        modelSessionId: "session-1",
        mode: { type: "full" },
      },
      () => undefined,
    );

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      model_session_id: "session-1",
    });
  });

  it("posts cancel requests to the sidecar", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ cancelled: true }), {
        headers: { "Content-Type": "application/json" },
      }),
    );

    await cancelNodeGraphRun("run-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/agent/graph/run/cancel",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ run_id: "run-1" }),
      }),
    );
  });

  it("adds the sidecar auth token when running inside Tauri", async () => {
    Object.defineProperty(globalThis, "__TAURI_INTERNALS__", {
      value: {},
      configurable: true,
    });
    invokeMock.mockResolvedValue("sidecar-token");
    const graph: NodeGraph = { graphId: "graph-1", nodes: [], edges: [] };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(
          'data: {"type":"task.completed","payload":{"taskId":"task-1"}}\n\n',
        ),
      );

    await runNodeGraphStream(
      {
        runId: "run-1",
        taskId: "task-1",
        projectPath: "D:\\Project\\demo.alita",
        graph,
        attachments: [],
        mode: { type: "full" },
      },
      () => undefined,
    );

    expect(invokeMock).toHaveBeenCalledWith("get_sidecar_auth_token");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/agent/graph/run/stream",
      expect.objectContaining({
        headers: {
          "Content-Type": "application/json",
          "X-Alita-Sidecar-Token": "sidecar-token",
        },
      }),
    );
  });
});
