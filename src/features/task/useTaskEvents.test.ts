import { invoke } from "@tauri-apps/api/core";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  cancelNodeGraphRun,
  createSseEventParser,
  runNodeGraphStream,
  submitUserMessage,
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
  it("posts inquiry choice when submitting a user message", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), {
        headers: { "Content-Type": "application/json" },
      }),
    );

    await submitUserMessage({
      taskId: "task-1",
      content: "Research and compare current Python packaging tools",
      attachments: [],
      inquiryChoice: "research_flow",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/agent/message",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          task_id: "task-1",
          content: "Research and compare current Python packaging tools",
          attachments: [],
          inquiry_choice: "research_flow",
        }),
      }),
    );
  });

  it("posts graph feedback context when submitting after a graph exists", async () => {
    const graph: NodeGraph = {
      graphId: "graph-1",
      nodes: [],
      edges: [],
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), {
        headers: { "Content-Type": "application/json" },
      }),
    );

    await submitUserMessage({
      taskId: "task-1",
      content: "Change the summary step",
      attachments: [],
      currentGraph: graph,
      hasRunHistory: true,
      artifactRefs: ["artifact-1"],
      pendingChoice: { id: "confirm_overwrite", kind: "full_replan" },
    });

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      task_id: "task-1",
      current_graph: graph,
      has_run_history: true,
      artifact_refs: ["artifact-1"],
      pending_choice: { id: "confirm_overwrite", kind: "full_replan" },
    });
  });

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
