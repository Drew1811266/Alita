import { describe, expect, it } from "vitest";

import {
  reduceBackendEvents,
  toGraphOverwriteSubmitChoice,
  toPlanningClarificationSubmitChoice,
  toPlanningConfirmationSubmitChoice,
} from "./backendEvents";
import type {
  PendingGraphOverwriteChoice,
  PendingPlanningClarificationChoice,
  PendingPlanningConfirmationChoice,
  PendingPlanningChoice,
} from "./backendEvents";
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

const replannedGraph: NodeGraph = {
  graphId: "task-1-graph-replanned",
  nodes: [],
  edges: [],
};

const pendingPlanningChoice: PendingPlanningConfirmationChoice = {
  kind: "planning.confirmation",
  taskId: "task-1",
  runId: "run-planning-1",
  threadId: "thread-planning-1",
  graphId: "task-1-graph",
  summary: "Create a report. Steps: read, analyze, write.",
  pendingChoice: {
    kind: "planning.confirmation",
    runId: "run-planning-1",
    threadId: "thread-planning-1",
    graphId: "task-1-graph",
  },
  choices: [
    { id: "approve", label: "确认执行" },
    { id: "revise", label: "要求修订" },
    { id: "cancel", label: "取消" },
  ],
};

const pendingPlanningClarificationChoice: PendingPlanningClarificationChoice = {
  kind: "planning.clarification",
  taskId: "task-clarify",
  runId: "run-clarify",
  threadId: "thread-clarify",
  question: "Who is the report for?",
  missingInputs: ["audience"],
  prompt: "Who is the report for?",
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

  it("preserves web source metadata on message.created messages", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph: null,
        dirty: false,
      },
      [
        {
          type: "message.created",
          payload: {
            message: assistantMessage,
            sources: [
              {
                ref: "S1",
                title: "Python documentation",
                url: "https://docs.python.org/3/",
                snippet: "Official Python docs.",
                accepted: true,
              },
            ],
            rejectedSources: [
              {
                ref: "R1",
                title: "Low quality mirror",
                url: "https://mirror.example/python",
                accepted: false,
                rejectionReason: "low_quality",
              },
            ],
            sourceMetadata: {
              accepted: [
                {
                  ref: "S1",
                  title: "Python documentation",
                  url: "https://docs.python.org/3/",
                  accepted: true,
                },
              ],
              rejected: [
                {
                  ref: "R1",
                  title: "Low quality mirror",
                  url: "https://mirror.example/python",
                  accepted: false,
                  rejectionReason: "low_quality",
                },
              ],
            },
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.messages[0].sources).toEqual([
      expect.objectContaining({
        ref: "S1",
        title: "Python documentation",
        url: "https://docs.python.org/3/",
      }),
    ]);
    expect(result.messages[0].rejectedSources).toHaveLength(1);
    expect(result.messages[0].sourceMetadata?.rejected?.[0].title).toBe(
      "Low quality mirror",
    );
  });

  it("keeps chat and simple web inquiry responses as messages without creating a graph", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph: null,
        dirty: false,
      },
      [
        {
          type: "message.created",
          payload: {
            message: createAssistantMessage("Direct assistant response."),
          },
        },
        {
          type: "message.created",
          payload: {
            message: createAssistantMessage("Sourced web answer [1]."),
            sources: [
              {
                ref: "[1]",
                title: "Python docs",
                url: "https://docs.python.org/3/",
                accepted: true,
              },
            ],
            sourceMetadata: {
              answerStatus: "answered",
              accepted: [
                {
                  ref: "[1]",
                  title: "Python docs",
                  url: "https://docs.python.org/3/",
                  accepted: true,
                },
              ],
              rejected: [],
            },
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.graph).toBeNull();
    expect(result.messages.map((message) => message.content)).toEqual([
      "Direct assistant response.",
      "Sourced web answer [1].",
    ]);
    expect(result.messages[1].sourceMetadata?.answerStatus).toBe("answered");
    expect(result.pendingResearchChoice).toBeNull();
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

  it("adds visible messages for planning progress before the graph appears", () => {
    const events: BackendEvent[] = [
      {
        type: "planning.progress",
        payload: {
          taskId: "task-1",
          stageId: "context-gathering",
          label: "Context gathering",
          summary: "No attachments were provided.",
          status: "completed",
          sequence: 2,
          total: 8,
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

    expect(result.messages).toHaveLength(3);
    expect(result.messages[0].content).toBe(existingMessage.content);
    expect(result.messages[1].content).toBe(
      "Planning progress 2/8: Context gathering\nNo attachments were provided.",
    );
    expect(result.messages[2].content.length).toBeGreaterThan(0);
    expect(result.graph).toBe(graph);
    expect(result.dirty).toBe(true);
  });

  it("ignores planning events without dropping node graph events", () => {
    const events: BackendEvent[] = [
      {
        type: "planning.draft_created",
        payload: {
          planDraft: {
            plan_draft_id: "plan-1",
            task_understanding: "Write a report",
            steps: [],
          },
        },
      },
      {
        type: "node_graph.created",
        payload: {
          graph: {
            graphId: "graph-1",
            nodes: [],
            edges: [],
            metadata: {
              generatedBy: "deep_agent_runtime",
              sourcePlanDraftId: "plan-1",
            },
          },
        },
      },
    ];

    const state = reduceBackendEvents(
      {
        messages: [],
        graph: null,
        dirty: false,
        pendingResearchChoice: null,
        pendingGraphOverwriteChoice: null,
        activeRunId: null,
        runHistory: [],
        pendingRuntimeNotices: [],
        artifacts: [],
      },
      events,
      createAssistantMessage,
    );

    expect(state.graph?.graphId).toBe("graph-1");
  });

  it("adds visible messages for deep planning clarification and failure", () => {
    const events: BackendEvent[] = [
      {
        type: "planning.clarification_required",
        payload: {
          kind: "planning.clarification",
          taskId: "task-clarify",
          runId: "run-clarify",
          threadId: "thread-clarify",
          question: "Please provide the target audience.",
          missingInputs: ["audience"],
          prompt: "Please provide the target audience.",
        },
      },
      {
        type: "planning.failed",
        payload: {
          reason: "reasoning_unavailable",
          message: "The local reasoning model is not configured.",
        },
      },
    ];

    const state = reduceBackendEvents(
      {
        messages: [],
        graph: null,
        dirty: false,
      },
      events,
      createAssistantMessage,
    );

    expect(state.messages.map((message) => message.content)).toEqual([
      "Please provide the target audience.",
      "规划失败：The local reasoning model is not configured.",
    ]);
  });

  it("marks planning stage changes dirty without adding a chat message", () => {
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph: null,
        dirty: false,
      },
      [
        {
          type: "planning.stage_changed",
          payload: {
            taskId: "task-1",
            stage: "build_context",
            label: "构建上下文",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.messages).toEqual([existingMessage]);
    expect(result.dirty).toBe(true);
  });

  it("records planning checkpoints without adding a chat message", () => {
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph: null,
        dirty: false,
        planningCheckpoints: [],
      },
      [
        {
          type: "planning.checkpoint_recorded",
          payload: {
            checkpoint: {
              runId: "run-planning-1",
              threadId: "thread-planning-1",
              checkpointId: "checkpoint-1",
              stage: "review_plan",
              node: "review_plan",
              revisionCount: 1,
              hasPlanDraft: true,
              hasCompiledGraph: false,
              hasAgentCompiledGraph: false,
              executionReady: false,
              createdAt: "2026-06-02T00:00:00.000Z",
            },
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.messages).toEqual([existingMessage]);
    expect(result.planningCheckpoints).toEqual([
      {
        runId: "run-planning-1",
        threadId: "thread-planning-1",
        checkpointId: "checkpoint-1",
        stage: "review_plan",
        node: "review_plan",
        revisionCount: 1,
        hasPlanDraft: true,
        hasCompiledGraph: false,
        hasAgentCompiledGraph: false,
        executionReady: false,
        createdAt: "2026-06-02T00:00:00.000Z",
      },
    ]);
    expect(result.dirty).toBe(true);
  });

  it("stores planning confirmation choices and clears other pending choices", () => {
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph,
        dirty: false,
        pendingResearchChoice: {
          taskId: "task-1",
          prompt: "Choose research path.",
          choices: [{ id: "quick_answer", label: "Quick answer" }],
        },
        pendingGraphOverwriteChoice: {
          taskId: "task-1",
          previousGraphId: graph.graphId,
          summary: "Overwrite graph?",
          pendingChoice: { id: "pending-graph", kind: "full_replan" },
          choices: [{ id: "cancel", label: "Cancel" }],
        },
      },
      [
        {
          type: "planning.confirmation_required",
          payload: pendingPlanningChoice,
        },
      ],
      createAssistantMessage,
    );

    expect(result.pendingPlanningChoice).toEqual(pendingPlanningChoice);
    expect(result.pendingResearchChoice).toBeNull();
    expect(result.pendingGraphOverwriteChoice).toBeNull();
    expect(result.messages[1].content).toContain(
      "Create a report. Steps: read, analyze, write.",
    );
    expect(result.messages[1].content).toContain("确认执行");
    expect(result.messages[1].content).toContain("要求修订");
    expect(result.messages[1].content).toContain("取消");
    expect(result.dirty).toBe(true);
  });

  it("stores planning confirmation choices from interrupted events", () => {
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph,
        dirty: false,
        pendingPlanningChoice: {
          ...pendingPlanningChoice,
          threadId: "stale-thread",
        },
      },
      [
        {
          type: "planning.interrupted",
          payload: pendingPlanningChoice,
        },
      ],
      createAssistantMessage,
    );

    expect(result.pendingPlanningChoice).toEqual(pendingPlanningChoice);
    expect(result.messages[1].content).toContain(
      "Create a report. Steps: read, analyze, write.",
    );
    expect(result.messages[1].content).toContain("确认执行");
    expect(result.dirty).toBe(true);
  });

  it("does not duplicate planning confirmation prompts when interrupted follows required", () => {
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph,
        dirty: false,
      },
      [
        {
          type: "planning.confirmation_required",
          payload: pendingPlanningChoice,
        },
        {
          type: "planning.interrupted",
          payload: pendingPlanningChoice,
        },
      ],
      createAssistantMessage,
    );

    expect(result.pendingPlanningChoice).toEqual(pendingPlanningChoice);
    expect(result.messages).toHaveLength(2);
    expect(result.messages[1].content).toContain("确认执行");
    expect(result.dirty).toBe(true);
  });

  it("stores clarification choices from interrupted clarification events", () => {
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph: null,
        dirty: false,
        pendingPlanningChoice,
      },
      [
        {
          type: "planning.interrupted",
          payload: {
            kind: "planning.clarification",
            taskId: "task-clarify",
            runId: "run-clarify",
            threadId: "thread-clarify",
            question: "Who is the report for?",
            missingInputs: ["audience"],
            prompt: "Who is the report for?",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.pendingPlanningChoice).toEqual(pendingPlanningClarificationChoice);
    expect(result.messages[1].content).toBe("Who is the report for?");
    expect(result.dirty).toBe(true);
  });

  it("does not duplicate clarification prompts when interrupted follows required", () => {
    const clarificationPayload = {
      kind: "planning.clarification" as const,
      taskId: "task-clarify",
      runId: "run-clarify",
      threadId: "thread-clarify",
      question: "Who is the report for?",
      missingInputs: ["audience"],
      prompt: "Who is the report for?",
    };
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph: null,
        dirty: false,
      },
      [
        {
          type: "planning.clarification_required",
          payload: clarificationPayload,
        },
        {
          type: "planning.interrupted",
          payload: clarificationPayload,
        },
      ],
      createAssistantMessage,
    );

    expect(result.messages.map((message) => message.content)).toEqual([
      "你好",
      "Who is the report for?",
    ]);
    expect(result.pendingPlanningChoice).toEqual(clarificationPayload);
    expect(result.dirty).toBe(true);
  });

  it("stores clarification choices from required events", () => {
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph,
        dirty: false,
        pendingResearchChoice: {
          taskId: "task-1",
          prompt: "Choose research path.",
          choices: [{ id: "quick_answer", label: "Quick answer" }],
        },
        pendingGraphOverwriteChoice: {
          taskId: "task-1",
          previousGraphId: graph.graphId,
          summary: "Overwrite graph?",
          pendingChoice: { id: "pending-graph", kind: "full_replan" },
          choices: [{ id: "cancel", label: "Cancel" }],
        },
        pendingPlanningChoice,
      },
      [
        {
          type: "planning.clarification_required",
          payload: pendingPlanningClarificationChoice,
        },
      ],
      createAssistantMessage,
    );

    expect(result.pendingPlanningChoice).toEqual(pendingPlanningClarificationChoice);
    expect(result.pendingResearchChoice).toBeNull();
    expect(result.pendingGraphOverwriteChoice).toBeNull();
    expect(result.messages[1].content).toBe("Who is the report for?");
    expect(result.dirty).toBe(true);
  });

  it("clears planning confirmation choices when planning is confirmed", () => {
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph,
        dirty: false,
        pendingPlanningChoice,
      },
      [
        {
          type: "planning.confirmed",
          payload: {
            taskId: "task-1",
            runId: "run-planning-1",
            threadId: "thread-planning-1",
            graphId: "task-1-graph",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.pendingPlanningChoice).toBeNull();
    expect(result.messages[1].content).toBe(
      "规划已确认，正在编译执行准备。",
    );
    expect(result.dirty).toBe(true);
  });

  it("resets stale agent plan graph compile state when a new graph is created", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph: null,
        dirty: false,
        agentCompileStatus: "failed",
        agentExecutionReadySummary: {
          taskId: "task-1",
          runId: "run-planning-1",
          threadId: "thread-planning-1",
          graphId: "stale-graph",
          compileId: "compile-stale",
          nodeCount: 4,
          edgeCount: 3,
          toolNodeCount: 2,
          modelNodeCount: 2,
          permissionsRequired: ["network"],
          expectedArtifacts: ["report.md"],
        },
        agentCompileFailure: {
          taskId: "task-1",
          runId: "run-planning-1",
          threadId: "thread-planning-1",
          graphId: "stale-graph",
          compileId: "compile-stale",
          reason: "stale compile failure",
          issues: [
            {
              code: "missing_binding",
              message: "Missing model binding.",
              severity: "error",
            },
          ],
          unsupportedCapabilities: ["browser"],
          missingBindings: ["model:reasoning"],
        },
      },
      [
        {
          type: "node_graph.created",
          payload: {
            graph,
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.graph).toBe(graph);
    expect(result.agentCompileStatus).toBe("idle");
    expect(result.agentExecutionReadySummary).toBeNull();
    expect(result.agentCompileFailure).toBeNull();
  });

  it("tracks the agent plan graph compile lifecycle without starting execution", () => {
    const executionReadyPayload = {
      taskId: "task-1",
      runId: "run-planning-1",
      threadId: "thread-planning-1",
      graphId: "task-1-graph",
      compileId: "compile-1",
      nodeCount: 5,
      edgeCount: 4,
      toolNodeCount: 3,
      modelNodeCount: 2,
      permissionsRequired: ["read_project_files", "network"],
      expectedArtifacts: ["artifacts/report.md"],
    };

    const result = reduceBackendEvents(
      {
        messages: [],
        graph,
        dirty: false,
        activeRunId: null,
        runHistory: [],
        pendingPlanningChoice,
      },
      [
        {
          type: "agent_plan_graph.compile_started",
          payload: {
            taskId: "task-1",
            runId: "run-planning-1",
            threadId: "thread-planning-1",
            graphId: "task-1-graph",
          },
        },
        {
          type: "agent_plan_graph.compiled",
          payload: {
            taskId: "task-1",
            runId: "run-planning-1",
            threadId: "thread-planning-1",
            graphId: "task-1-graph",
            compileId: "compile-1",
          },
        },
        {
          type: "agent_plan_graph.compile_review_completed",
          payload: {
            taskId: "task-1",
            runId: "run-planning-1",
            threadId: "thread-planning-1",
            graphId: "task-1-graph",
            compileId: "compile-1",
          },
        },
        {
          type: "agent_plan_graph.execution_ready",
          payload: executionReadyPayload,
        },
      ],
      createAssistantMessage,
    );

    expect(result.agentCompileStatus).toBe("execution_ready");
    expect(result.agentExecutionReadySummary).toEqual(executionReadyPayload);
    expect(result.agentCompileFailure).toBeNull();
    expect(result.activeRunId).toBeNull();
    expect(result.runHistory).toEqual([]);
    expect(result.pendingPlanningChoice).toEqual(pendingPlanningChoice);
    expect(result.messages).toEqual([]);
    expect(result.dirty).toBe(true);
  });

  it("adds a visible message when agent execution starts and preserves execution-ready compile state", () => {
    const executionReadySummary = {
      taskId: "task-1",
      runId: "run-planning-1",
      threadId: "thread-planning-1",
      graphId: "task-1-graph",
      compileId: "compile-1",
      nodeCount: 5,
      edgeCount: 4,
      toolNodeCount: 3,
      modelNodeCount: 2,
      permissionsRequired: ["read_project_files"],
      expectedArtifacts: ["artifacts/report.md"],
    };

    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph,
        dirty: false,
        agentCompileStatus: "execution_ready",
        agentExecutionReadySummary: executionReadySummary,
      },
      [
        {
          type: "agent_execution.started",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.messages.map((message) => message.content)).toEqual([
      existingMessage.content,
      "Agent 开始执行已确认的计划。",
    ]);
    expect(result.agentCompileStatus).toBe("execution_ready");
    expect(result.agentExecutionReadySummary).toEqual(executionReadySummary);
    expect(result.dirty).toBe(true);
  });

  it("adds a final execution message with artifact paths and preserves compile state", () => {
    const executionReadySummary = {
      taskId: "task-1",
      runId: "run-planning-1",
      threadId: "thread-planning-1",
      graphId: "task-1-graph",
      compileId: "compile-1",
      nodeCount: 5,
      edgeCount: 4,
      toolNodeCount: 3,
      modelNodeCount: 2,
      permissionsRequired: [],
      expectedArtifacts: ["artifacts/report.md"],
    };

    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph,
        dirty: false,
        agentCompileStatus: "execution_ready",
        agentExecutionReadySummary: executionReadySummary,
      },
      [
        {
          type: "agent_execution.final",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
            status: "completed",
            message: "Execution finished.",
            artifactRefs: ["artifacts/report.md"],
            completedNodeIds: ["write-report"],
            checkpointIds: ["checkpoint-1"],
            recoveryActions: [],
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.messages[1].content).toContain(
      "Agent 执行完成并通过验证。",
    );
    expect(result.messages[1].content).toContain("artifacts/report.md");
    expect(result.agentCompileStatus).toBe("execution_ready");
    expect(result.agentExecutionReadySummary).toEqual(executionReadySummary);
    expect(result.dirty).toBe(true);
  });

  it("adds a direct summary failed execution message outside an agent flow", () => {
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph,
        dirty: false,
        agentCompileStatus: "execution_ready",
      },
      [
        {
          type: "agent_execution.failed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
            status: "failed",
            artifactRefs: [],
            completedNodeIds: [],
            checkpointIds: [],
            recoveryActions: [],
            failedNodeId: "write-report",
            reason: "tool_failed",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.messages[1].content).toBe("Agent 执行失败：tool_failed");
    expect(result.agentCompileStatus).toBe("execution_ready");
    expect(result.dirty).toBe(true);
  });

  it("adds an exception failed execution message using errorCode before reason", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph,
        dirty: false,
        agentCompileStatus: "execution_ready",
      },
      [
        {
          type: "agent_execution.failed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            graphId: "task-1-graph",
            status: "failed",
            reason: "execution_bridge_failed",
            errorCode: "bridge_timeout",
            issues: [],
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.messages[0].content).toBe(
      "Agent 执行失败：bridge_timeout",
    );
    expect(result.agentCompileStatus).toBe("execution_ready");
    expect(result.dirty).toBe(true);
  });

  it("adds a repair-proposed message and preserves compile status", () => {
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph,
        dirty: false,
        agentCompileStatus: "execution_ready",
      },
      [
        {
          type: "agent_execution.repair_proposed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
            status: "failed",
            artifactRefs: [],
            completedNodeIds: [],
            checkpointIds: ["checkpoint-1"],
            recoveryActions: [],
            actions: [{ kind: "retry_node", nodeId: "write-report" }],
            issues: [],
            reason: "tool_failed",
            failedNodeId: "write-report",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.messages[1].content).toBe(
      "Agent 已提出执行修复方案。（1 个动作）",
    );
    expect(result.agentCompileStatus).toBe("execution_ready");
    expect(result.dirty).toBe(true);
  });

  it("keeps completed execution state-only and adds interrupted execution messages", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph,
        dirty: false,
        agentCompileStatus: "execution_ready",
      },
      [
        {
          type: "agent_execution.completed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
            status: "completed",
            artifactRefs: [],
            completedNodeIds: ["write-report"],
            checkpointIds: ["checkpoint-1"],
            recoveryActions: [],
          },
        },
        {
          type: "agent_execution.interrupted",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
            status: "interrupted",
            artifactRefs: [],
            completedNodeIds: ["write-report"],
            checkpointIds: ["checkpoint-1"],
            recoveryActions: [],
            reason: "human_input_required",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.messages.map((message) => message.content)).toEqual([
      "Agent 执行已中断：human_input_required",
    ]);
    expect(result.agentCompileStatus).toBe("execution_ready");
    expect(result.dirty).toBe(true);
  });

  it("marks verification completion dirty without duplicating approved chat messages", () => {
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph,
        dirty: false,
        agentCompileStatus: "execution_ready",
      },
      [
        {
          type: "agent_execution.verify_completed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
            status: "approved",
            isValid: true,
            issues: [],
            finalArtifacts: ["artifacts/report.md"],
            repairRequired: false,
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.messages).toEqual([existingMessage]);
    expect(result.agentCompileStatus).toBe("execution_ready");
    expect(result.dirty).toBe(true);
  });

  it("keeps verification completion dirty-only for failed and repair statuses", () => {
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph,
        dirty: false,
        agentCompileStatus: "execution_ready",
      },
      [
        {
          type: "agent_execution.verify_completed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
            status: "needs_repair",
            isValid: false,
            issues: [{ message: "Missing final artifact." }],
            finalArtifacts: [],
            repairRequired: true,
          },
        },
        {
          type: "agent_execution.verify_completed",
          payload: {
            taskId: "task-2",
            runId: "run-execution-2",
            threadId: "thread-planning-2",
            compileId: "compile-2",
            graphId: "task-2-graph",
            status: "failed",
            isValid: false,
            issues: [{ message: "Verifier failed." }],
            finalArtifacts: [],
            repairRequired: false,
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.messages).toEqual([existingMessage]);
    expect(result.agentCompileStatus).toBe("execution_ready");
    expect(result.dirty).toBe(true);
  });

  it("suppresses duplicate messages in a full successful agent execution stream", () => {
    const executionReadySummary = {
      taskId: "task-1",
      runId: "run-planning-1",
      threadId: "thread-planning-1",
      graphId: "task-1-graph",
      compileId: "compile-1",
      nodeCount: 5,
      edgeCount: 4,
      toolNodeCount: 3,
      modelNodeCount: 2,
      permissionsRequired: [],
      expectedArtifacts: ["artifacts/report.md"],
    };

    const result = reduceBackendEvents(
      {
        messages: [],
        graph,
        dirty: false,
        activeRunId: "run-execution-1",
        runHistory: [],
        agentCompileStatus: "execution_ready",
        agentExecutionReadySummary: executionReadySummary,
      },
      [
        {
          type: "agent_execution.started",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
          },
        },
        {
          type: "task.completed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
          },
        },
        {
          type: "agent_execution.completed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
            status: "completed",
            artifactRefs: ["artifacts/report.md"],
            completedNodeIds: ["write-report"],
            checkpointIds: ["checkpoint-1"],
            recoveryActions: [],
          },
        },
        {
          type: "agent_execution.verify_completed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
            status: "approved",
            isValid: true,
            issues: [],
            finalArtifacts: ["artifacts/report.md"],
            repairRequired: false,
          },
        },
        {
          type: "agent_execution.final",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
            status: "completed",
            message: "Execution finished.",
            artifactRefs: ["artifacts/report.md"],
            completedNodeIds: ["write-report"],
            checkpointIds: ["checkpoint-1"],
            recoveryActions: [],
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.messages.map((message) => message.content)).toEqual([
      "Agent 开始执行已确认的计划。",
      "Agent 执行完成并通过验证。\n产物：artifacts/report.md",
    ]);
    expect(result.runHistory?.[0]).toMatchObject({
      runId: "run-execution-1",
      status: "completed",
    });
    expect(result.agentCompileStatus).toBe("execution_ready");
    expect(result.agentExecutionReadySummary).toEqual(executionReadySummary);
    expect(result.dirty).toBe(true);
  });

  it("suppresses duplicate messages across sequential successful agent execution reducer calls", () => {
    const executionReadySummary = {
      taskId: "task-1",
      runId: "run-planning-1",
      threadId: "thread-planning-1",
      graphId: "task-1-graph",
      compileId: "compile-1",
      nodeCount: 5,
      edgeCount: 4,
      toolNodeCount: 3,
      modelNodeCount: 2,
      permissionsRequired: [],
      expectedArtifacts: ["artifacts/report.md"],
    };
    let state = reduceBackendEvents(
      {
        messages: [],
        graph,
        dirty: false,
        activeRunId: "run-execution-1",
        runHistory: [],
        agentCompileStatus: "execution_ready",
        agentExecutionReadySummary: executionReadySummary,
      },
      [
        {
          type: "agent_execution.started",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
          },
        },
      ],
      createAssistantMessage,
    );

    state = reduceBackendEvents(
      state,
      [
        {
          type: "task.completed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
          },
        },
      ],
      createAssistantMessage,
    );

    state = reduceBackendEvents(
      state,
      [
        {
          type: "agent_execution.completed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
            status: "completed",
            artifactRefs: ["artifacts/report.md"],
            completedNodeIds: ["write-report"],
            checkpointIds: ["checkpoint-1"],
            recoveryActions: [],
          },
        },
      ],
      createAssistantMessage,
    );

    state = reduceBackendEvents(
      state,
      [
        {
          type: "agent_execution.verify_completed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
            status: "approved",
            isValid: true,
            issues: [],
            finalArtifacts: ["artifacts/report.md"],
            repairRequired: false,
          },
        },
      ],
      createAssistantMessage,
    );

    state = reduceBackendEvents(
      state,
      [
        {
          type: "agent_execution.final",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
            status: "completed",
            message: "Execution finished.",
            artifactRefs: ["artifacts/report.md"],
            completedNodeIds: ["write-report"],
            checkpointIds: ["checkpoint-1"],
            recoveryActions: [],
          },
        },
      ],
      createAssistantMessage,
    );

    expect(state.messages.map((message) => message.content)).toEqual([
      "Agent 开始执行已确认的计划。",
      "Agent 执行完成并通过验证。\n产物：artifacts/report.md",
    ]);
    expect(state.runHistory?.[0]).toMatchObject({
      runId: "run-execution-1",
      status: "completed",
    });
    expect(state.agentCompileStatus).toBe("execution_ready");
    expect(state.agentExecutionReadySummary).toEqual(executionReadySummary);
    expect(state.activeAgentExecutionFlow).toBeNull();
  });

  it("suppresses duplicate messages in a full repair agent execution stream", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph,
        dirty: false,
        activeRunId: "run-execution-1",
        runHistory: [],
        agentCompileStatus: "execution_ready",
      },
      [
        {
          type: "agent_execution.started",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
          },
        },
        {
          type: "task.failed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            error: "Tool failed.",
            errorCode: "tool_failed",
          },
        },
        {
          type: "agent_execution.failed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
            status: "failed",
            artifactRefs: [],
            completedNodeIds: ["extract-data"],
            checkpointIds: ["checkpoint-1"],
            recoveryActions: [{ kind: "retry_node", nodeId: "write-report" }],
            failedNodeId: "write-report",
            reason: "tool_failed",
          },
        },
        {
          type: "agent_execution.verify_completed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
            status: "needs_repair",
            isValid: false,
            issues: [{ message: "Missing final artifact." }],
            finalArtifacts: [],
            repairRequired: true,
          },
        },
        {
          type: "agent_execution.repair_proposed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
            status: "failed",
            artifactRefs: [],
            completedNodeIds: ["extract-data"],
            checkpointIds: ["checkpoint-1"],
            recoveryActions: [],
            actions: [{ kind: "retry_node", nodeId: "write-report" }],
            issues: [{ message: "Missing final artifact." }],
            reason: "tool_failed",
            failedNodeId: "write-report",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.messages.map((message) => message.content)).toEqual([
      "Agent 开始执行已确认的计划。",
      "Agent 已提出执行修复方案。（1 个动作）",
    ]);
    expect(result.runHistory?.[0]).toMatchObject({
      runId: "run-execution-1",
      status: "failed",
    });
    expect(result.agentCompileStatus).toBe("execution_ready");
    expect(result.dirty).toBe(true);
  });

  it("suppresses duplicate messages across sequential repair agent execution reducer calls", () => {
    let state = reduceBackendEvents(
      {
        messages: [],
        graph,
        dirty: false,
        activeRunId: "run-execution-1",
        runHistory: [],
        agentCompileStatus: "execution_ready",
      },
      [
        {
          type: "agent_execution.started",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
          },
        },
      ],
      createAssistantMessage,
    );

    state = reduceBackendEvents(
      state,
      [
        {
          type: "task.failed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            error: "Tool failed.",
            errorCode: "tool_failed",
          },
        },
      ],
      createAssistantMessage,
    );

    state = reduceBackendEvents(
      state,
      [
        {
          type: "agent_execution.failed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
            status: "failed",
            artifactRefs: [],
            completedNodeIds: ["extract-data"],
            checkpointIds: ["checkpoint-1"],
            recoveryActions: [{ kind: "retry_node", nodeId: "write-report" }],
            failedNodeId: "write-report",
            reason: "tool_failed",
          },
        },
      ],
      createAssistantMessage,
    );

    state = reduceBackendEvents(
      state,
      [
        {
          type: "agent_execution.verify_completed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
            status: "needs_repair",
            isValid: false,
            issues: [{ message: "Missing final artifact." }],
            finalArtifacts: [],
            repairRequired: true,
          },
        },
      ],
      createAssistantMessage,
    );

    state = reduceBackendEvents(
      state,
      [
        {
          type: "agent_execution.repair_proposed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
            status: "failed",
            artifactRefs: [],
            completedNodeIds: ["extract-data"],
            checkpointIds: ["checkpoint-1"],
            recoveryActions: [],
            actions: [{ kind: "retry_node", nodeId: "write-report" }],
            issues: [{ message: "Missing final artifact." }],
            reason: "tool_failed",
            failedNodeId: "write-report",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(state.messages.map((message) => message.content)).toEqual([
      "Agent 开始执行已确认的计划。",
      "Agent 已提出执行修复方案。（1 个动作）",
    ]);
    expect(state.runHistory?.[0]).toMatchObject({
      runId: "run-execution-1",
      status: "failed",
    });
    expect(state.agentCompileStatus).toBe("execution_ready");
    expect(state.activeAgentExecutionFlow).toBeNull();
  });

  it("surfaces unrecoverable summary failures across sequential agent execution reducer calls", () => {
    let state = reduceBackendEvents(
      {
        messages: [],
        graph,
        dirty: false,
        activeRunId: "run-execution-1",
        runHistory: [],
        agentCompileStatus: "execution_ready",
      },
      [
        {
          type: "agent_execution.started",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
          },
        },
      ],
      createAssistantMessage,
    );

    state = reduceBackendEvents(
      state,
      [
        {
          type: "task.failed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            error: "Tool failed.",
            errorCode: "tool_failed",
          },
        },
      ],
      createAssistantMessage,
    );

    state = reduceBackendEvents(
      state,
      [
        {
          type: "agent_execution.failed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
            status: "failed",
            artifactRefs: [],
            completedNodeIds: ["extract-data"],
            checkpointIds: ["checkpoint-1"],
            recoveryActions: [],
            failedNodeId: "write-report",
            reason: "tool_failed",
          },
        },
      ],
      createAssistantMessage,
    );

    state = reduceBackendEvents(
      state,
      [
        {
          type: "agent_execution.verify_completed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
            status: "failed",
            isValid: false,
            issues: [{ message: "No repair available." }],
            finalArtifacts: [],
            repairRequired: false,
          },
        },
      ],
      createAssistantMessage,
    );

    expect(state.messages.map((message) => message.content)).toEqual([
      "Agent 开始执行已确认的计划。",
      "Agent 执行失败：tool_failed",
    ]);
    expect(state.runHistory?.[0]).toMatchObject({
      runId: "run-execution-1",
      status: "failed",
    });
    expect(state.agentCompileStatus).toBe("execution_ready");
    expect(state.activeAgentExecutionFlow).toBeNull();
  });

  it("surfaces exception failures in an agent execution stream without a low-level task failure", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph,
        dirty: false,
        agentCompileStatus: "execution_ready",
      },
      [
        {
          type: "agent_execution.started",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            compileId: "compile-1",
            graphId: "task-1-graph",
          },
        },
        {
          type: "agent_execution.failed",
          payload: {
            taskId: "task-1",
            runId: "run-execution-1",
            threadId: "thread-planning-1",
            graphId: "task-1-graph",
            status: "failed",
            reason: "execution_bridge_failed",
            errorCode: "bridge_timeout",
            issues: [{ message: "Runner timed out." }],
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.messages.map((message) => message.content)).toEqual([
      "Agent 开始执行已确认的计划。",
      "Agent 执行失败：bridge_timeout\nRunner timed out.",
    ]);
    expect(result.agentCompileStatus).toBe("execution_ready");
    expect(result.dirty).toBe(true);
  });

  it("keeps ordinary task terminal messages outside agent execution flows", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph,
        dirty: false,
        activeRunId: "ordinary-run-1",
        runHistory: [],
      },
      [
        {
          type: "task.completed",
          payload: {
            taskId: "ordinary-task-1",
            runId: "ordinary-run-1",
          },
        },
        {
          type: "task.failed",
          payload: {
            taskId: "ordinary-task-2",
            runId: "ordinary-run-2",
            error: "Ordinary task failed.",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.messages.map((message) => message.content)).toEqual([
      "流程执行完成。",
      "流程执行失败：Ordinary task failed.",
    ]);
    expect(result.runHistory).toEqual([
      expect.objectContaining({
        runId: "ordinary-run-1",
        status: "completed",
      }),
      expect.objectContaining({
        runId: "ordinary-run-2",
        status: "failed",
      }),
    ]);
  });

  it("stores agent plan graph compile failures and surfaces the reason", () => {
    const failurePayload = {
      taskId: "task-1",
      runId: "run-planning-1",
      threadId: "thread-planning-1",
      graphId: "task-1-graph",
      reason: "Graph uses unsupported capabilities.",
      issues: [
        {
          code: "unsupported_capability",
          message: "Browser automation is not available.",
          nodeId: "browse-web",
          severity: "error" as const,
        },
        {
          code: "missing_binding",
          message: "No model binding configured.",
          severity: "warning" as const,
        },
      ],
      unsupportedCapabilities: ["browser_automation"],
      missingBindings: ["model:reasoning"],
    };

    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph,
        dirty: false,
        pendingPlanningChoice,
        agentCompileStatus: "compiling",
        agentExecutionReadySummary: {
          taskId: "task-1",
          runId: "run-planning-1",
          threadId: "thread-planning-1",
          graphId: "task-1-graph",
          compileId: "compile-stale",
          nodeCount: 2,
          edgeCount: 1,
          toolNodeCount: 1,
          modelNodeCount: 1,
          permissionsRequired: [],
          expectedArtifacts: [],
        },
      },
      [
        {
          type: "agent_plan_graph.compile_failed",
          payload: failurePayload,
        },
      ],
      createAssistantMessage,
    );

    expect(result.agentCompileStatus).toBe("failed");
    expect(result.agentCompileFailure).toEqual(failurePayload);
    expect(result.agentExecutionReadySummary).toBeNull();
    expect(result.pendingPlanningChoice).toBeNull();
    expect(result.messages[1].content).toContain(
      "Graph uses unsupported capabilities.",
    );
    expect(result.dirty).toBe(true);
  });

  it("surfaces blocked legacy graph fallback as a compile failure without duplicating task failure messages", () => {
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph,
        dirty: false,
        activeRunId: null,
        runHistory: [],
        pendingResearchChoice: {
          taskId: "task-1",
          prompt: "Choose research path.",
          choices: [{ id: "quick_answer", label: "Quick answer" }],
        },
        pendingGraphOverwriteChoice: {
          taskId: "task-1",
          previousGraphId: graph.graphId,
          summary: "Overwrite graph?",
          pendingChoice: { id: "pending-graph", kind: "full_replan" },
          choices: [{ id: "cancel", label: "Cancel" }],
        },
        pendingPlanningChoice,
        agentCompileStatus: "execution_ready",
        agentExecutionReadySummary: {
          taskId: "task-1",
          runId: "run-stale",
          threadId: "thread-stale",
          graphId: "task-1-graph",
          compileId: "compile-stale",
          nodeCount: 2,
          edgeCount: 1,
          toolNodeCount: 1,
          modelNodeCount: 1,
          permissionsRequired: [],
          expectedArtifacts: [],
        },
      },
      [
        {
          type: "runtime.legacy_graph_blocked",
          payload: {
            runId: "run-block",
            threadId: "thread-block",
            taskId: "task-block",
            reason: "legacy graph event emitted from response-only fallback",
            blockedEventTypes: ["node_graph.created"],
          },
        },
        {
          type: "task.failed",
          payload: {
            taskId: "task-block",
            runId: "run-block",
            errorCode: "legacy_graph_blocked",
            error:
              "Legacy graph creation is blocked from the Agent Runtime product path.",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.activeRunId).toBeNull();
    expect(result.runHistory?.[0]).toMatchObject({
      runId: "run-block",
      status: "failed",
    });
    expect(result.agentCompileStatus).toBe("failed");
    expect(result.agentExecutionReadySummary).toBeNull();
    expect(result.agentCompileFailure).toBeNull();
    expect(result.pendingResearchChoice).toBeNull();
    expect(result.pendingGraphOverwriteChoice).toBeNull();
    expect(result.pendingPlanningChoice).toBeNull();
    expect(result.messages.map((message) => message.content)).toEqual([
      existingMessage.content,
      "Legacy graph fallback was blocked. The Agent must produce the task graph through deep planning.",
    ]);
    expect(result.dirty).toBe(true);
  });

  it("does not suppress unrelated later blocked-code task failures", () => {
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph,
        dirty: false,
        activeRunId: null,
        runHistory: [],
      },
      [
        {
          type: "runtime.legacy_graph_blocked",
          payload: {
            runId: "run-block",
            threadId: "thread-block",
            taskId: "task-block",
            reason: "legacy graph event emitted from response-only fallback",
            blockedEventTypes: ["node_graph.created"],
          },
        },
        {
          type: "task.failed",
          payload: {
            taskId: "task-other",
            runId: "run-other",
            errorCode: "legacy_graph_blocked",
            error: "Unrelated blocked task failed.",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.runHistory).toEqual([
      expect.objectContaining({
        runId: "run-other",
        status: "failed",
        summary: "Unrelated blocked task failed.",
      }),
    ]);
    expect(result.messages.map((message) => message.content)).toEqual([
      existingMessage.content,
      "Legacy graph fallback was blocked. The Agent must produce the task graph through deep planning.",
      "流程执行失败：Unrelated blocked task failed.",
    ]);
  });

  it("surfaces incomplete Deep Agent product path as a compile failure without duplicating task failure messages", () => {
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph,
        dirty: false,
        activeRunId: null,
        runHistory: [],
        pendingResearchChoice: {
          taskId: "task-1",
          prompt: "Choose research path.",
          choices: [{ id: "research_flow", label: "Research flow" }],
        },
        pendingGraphOverwriteChoice: {
          taskId: "task-1",
          previousGraphId: graph.graphId,
          summary: "Overwrite graph?",
          pendingChoice: { id: "pending-graph", kind: "full_replan" },
          choices: [{ id: "cancel", label: "Cancel" }],
        },
        pendingPlanningChoice,
        agentCompileStatus: "compiling",
      },
      [
        {
          type: "runtime.deep_agent_product_path_blocked",
          payload: {
            runId: "run-incomplete",
            threadId: "thread-incomplete",
            taskId: "task-incomplete",
            reason: "deep_agent_runtime_missing_terminal_event:deep_planning",
          },
        },
        {
          type: "task.failed",
          payload: {
            taskId: "task-incomplete",
            runId: "run-incomplete",
            errorCode: "deep_agent_product_path_incomplete",
            error:
              "Deep Agent runtime did not emit a terminal product-path event; legacy graph fallback is blocked.",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.activeRunId).toBeNull();
    expect(result.runHistory?.[0]).toMatchObject({
      runId: "run-incomplete",
      status: "failed",
    });
    expect(result.agentCompileStatus).toBe("failed");
    expect(result.agentExecutionReadySummary).toBeNull();
    expect(result.agentCompileFailure).toBeNull();
    expect(result.pendingResearchChoice).toBeNull();
    expect(result.pendingGraphOverwriteChoice).toBeNull();
    expect(result.pendingPlanningChoice).toBeNull();
    expect(result.messages.map((message) => message.content)).toEqual([
      existingMessage.content,
      "Deep Agent planning did not reach a valid terminal state, and legacy graph fallback is blocked.",
    ]);
    expect(result.dirty).toBe(true);
  });

  it("clears planning confirmation choices when planning is cancelled", () => {
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph,
        dirty: false,
        pendingPlanningChoice,
      },
      [
        {
          type: "planning.cancelled",
          payload: {
            taskId: "task-1",
            runId: "run-planning-1",
            threadId: "thread-planning-1",
            graphId: "task-1-graph",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.pendingPlanningChoice).toBeNull();
    expect(result.messages[1].content).toBe("规划已取消。");
    expect(result.dirty).toBe(true);
  });

  it("adds a chat prompt for research choice events", () => {
    const submittedPayload = {
      taskId: "task-1",
      content: "Compare current Python packaging tools",
      attachments: [],
    };
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph: null,
        dirty: false,
      },
      [
        {
          type: "research.choice_required",
          payload: {
            taskId: "task-1",
            prompt:
              "This question can be answered quickly or turned into a research flow. Choose how to proceed.",
            choices: [
              {
                id: "quick_answer",
                label: "Quick answer",
                description:
                  "Search the web now and return a concise sourced answer.",
              },
              {
                id: "research_flow",
                label: "Research flow",
                description:
                  "Create a research graph for planning, source review, and report synthesis.",
              },
            ],
          },
        },
      ],
      createAssistantMessage,
      submittedPayload,
    );

    expect(result.messages).toHaveLength(2);
    expect(result.messages[1].content).toContain(
      "This question can be answered quickly",
    );
    expect(result.messages[1].content).toContain("Quick answer");
    expect(result.messages[1].content).toContain("Research flow");
    expect(result.pendingResearchChoice).toEqual({
      taskId: "task-1",
      prompt:
        "This question can be answered quickly or turned into a research flow. Choose how to proceed.",
      choices: [
        {
          id: "quick_answer",
          label: "Quick answer",
          description: "Search the web now and return a concise sourced answer.",
        },
        {
          id: "research_flow",
          label: "Research flow",
          description:
            "Create a research graph for planning, source review, and report synthesis.",
        },
      ],
      submittedPayload,
    });
    expect(result.dirty).toBe(true);
  });

  it("binds a stale research choice to the request that produced it", () => {
    const olderPayload = {
      taskId: "task-1",
      content: "Research source A",
      attachments: [
        {
          attachmentId: "a1",
          name: "a.md",
          path: "D:\\Project\\a.md",
          sizeBytes: 10,
          mimeType: "text/markdown",
        },
      ],
    };
    const newerPayload = {
      taskId: "task-1",
      content: "Research source B",
      attachments: [],
    };

    const result = reduceBackendEvents(
      {
        messages: [
          {
            messageId: "user-b",
            role: "user",
            content: newerPayload.content,
            attachments: [],
            createdAt: "2026-05-09T00:00:02.000Z",
          },
        ],
        graph: null,
        dirty: false,
      },
      [
        {
          type: "research.choice_required",
          payload: {
            taskId: "task-1",
            prompt: "Choose how to answer.",
            choices: [{ id: "research_flow", label: "Research flow" }],
          },
        },
      ],
      createAssistantMessage,
      olderPayload,
    );

    expect(result.pendingResearchChoice?.submittedPayload).toEqual(olderPayload);
    expect(result.pendingResearchChoice?.submittedPayload).not.toEqual(
      newerPayload,
    );
  });

  it("clears pending research choice when a response arrives", () => {
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph: null,
        dirty: false,
        pendingResearchChoice: {
          taskId: "task-1",
          prompt: "Choose how to proceed.",
          choices: [
            { id: "quick_answer", label: "Quick answer" },
            { id: "research_flow", label: "Research flow" },
          ],
        },
      },
      [
        {
          type: "node_graph.created",
          payload: {
            graph,
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.pendingResearchChoice).toBeNull();
    expect(result.graph).toBe(graph);
  });

  it("updates the visible graph when graph.replanned is received", () => {
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph,
        dirty: false,
      },
      [
        {
          type: "graph.replanned",
          payload: {
            graph: replannedGraph,
            previousGraphId: graph.graphId,
            summary: "Updated graph node from user feedback.",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.graph).toBe(replannedGraph);
    expect(result.messages.map((message) => message.content)).toEqual([
      existingMessage.content,
      "Updated graph node from user feedback.",
    ]);
    expect(result.pendingGraphOverwriteChoice).toBeNull();
    expect(result.dirty).toBe(true);
  });

  it("stores graph overwrite confirmation so a later submit can carry pendingChoice", () => {
    const result = reduceBackendEvents(
      {
        messages: [existingMessage],
        graph,
        dirty: false,
      },
      [
        {
          type: "graph.overwrite_confirmation_required",
          payload: {
            taskId: "task-1",
            previousGraphId: graph.graphId,
            summary: "This change will replace the current graph.",
            pendingChoice: {
              id: "pending-graph-overwrite",
              kind: "local_modification",
              message: "Change Extract Data",
              previousGraphId: graph.graphId,
              nodeId: "extract-data",
            },
            choices: [
              {
                id: "confirm_overwrite",
                label: "Overwrite graph",
                description: "Replace the current graph.",
              },
              { id: "cancel", label: "Cancel" },
            ],
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.pendingGraphOverwriteChoice).toEqual({
      taskId: "task-1",
      previousGraphId: graph.graphId,
      summary: "This change will replace the current graph.",
      pendingChoice: {
        id: "pending-graph-overwrite",
        kind: "local_modification",
        message: "Change Extract Data",
        previousGraphId: graph.graphId,
        nodeId: "extract-data",
      },
      choices: [
        {
          id: "confirm_overwrite",
          label: "Overwrite graph",
          description: "Replace the current graph.",
        },
        { id: "cancel", label: "Cancel" },
      ],
    });
    expect(result.messages[1].content).toContain(
      "This change will replace the current graph.",
    );
    expect(result.pendingResearchChoice).toBeNull();
    expect(result.dirty).toBe(true);
  });

  it("maps overwrite confirmation text into a sidecar pending choice", () => {
    const pendingChoice: PendingGraphOverwriteChoice = {
      taskId: "task-1",
      previousGraphId: graph.graphId,
      summary: "This full replan will replace prior run artifacts.",
      pendingChoice: {
        id: "pending-graph-overwrite",
        kind: "full_replan",
        message: "Restart, the direction is wrong.",
        previousGraphId: graph.graphId,
      },
      choices: [
        { id: "confirm_overwrite", label: "Overwrite graph" },
        { id: "cancel", label: "Cancel" },
      ],
    };

    expect(toGraphOverwriteSubmitChoice(pendingChoice, "yes")).toMatchObject({
      id: "confirm_overwrite",
      kind: "full_replan",
      previousGraphId: graph.graphId,
    });
    expect(toGraphOverwriteSubmitChoice(pendingChoice, "cancel")).toMatchObject({
      id: "cancel",
      kind: "full_replan",
      previousGraphId: graph.graphId,
    });
  });

  it("adds an explicit decision to planning confirmation submit choices", () => {
    expect(
      toPlanningConfirmationSubmitChoice(pendingPlanningChoice, "approve"),
    ).toEqual({
      kind: "planning.confirmation",
      runId: "run-planning-1",
      threadId: "thread-planning-1",
      graphId: "task-1-graph",
      decision: "approve",
      revisionInstructions: [],
    });

    expect(
      toPlanningConfirmationSubmitChoice(pendingPlanningChoice, "revise", [
        "Add explicit verification.",
      ]),
    ).toEqual({
      kind: "planning.confirmation",
      runId: "run-planning-1",
      threadId: "thread-planning-1",
      graphId: "task-1-graph",
      decision: "revise",
      revisionInstructions: ["Add explicit verification."],
    });
  });

  it("maps clarification answers into planning resume choices", () => {
    expect(
      toPlanningClarificationSubmitChoice(
        pendingPlanningClarificationChoice,
        "The report is for executives.",
      ),
    ).toEqual({
      kind: "planning.clarification",
      runId: "run-clarify",
      threadId: "thread-clarify",
      answer: "The report is for executives.",
    });
  });

  it("replaces only the graph snapshot supplied by graph feedback events", () => {
    const originalGraph: NodeGraph = {
      graphId: "feedback-graph",
      nodes: [
        {
          nodeId: "extract-data",
          nodeType: "model",
          displayName: "Extract Data",
          status: "completed",
          inputPorts: [],
          outputPorts: [],
          dependencies: [],
          summary: "Extract CSV rows.",
          createdBy: "agent",
          artifactRefs: ["artifact-extract"],
          retryCount: 0,
          position: { x: 0, y: 0 },
        },
        {
          nodeId: "independent-output",
          nodeType: "output",
          displayName: "Independent Output",
          status: "completed",
          inputPorts: [],
          outputPorts: [],
          dependencies: [],
          summary: "Keep independent output.",
          createdBy: "agent",
          artifactRefs: ["artifact-independent"],
          retryCount: 0,
          position: { x: 180, y: 0 },
        },
      ],
      edges: [],
    };
    const updatedGraph: NodeGraph = {
      ...originalGraph,
      nodes: [
        {
          ...originalGraph.nodes[0],
          status: "waiting",
          artifactRefs: [],
          summary: "Extract JSON rows.",
        },
        originalGraph.nodes[1],
      ],
    };

    const result = reduceBackendEvents(
      {
        messages: [],
        graph: originalGraph,
        dirty: false,
      },
      [
        {
          type: "graph.replanned",
          payload: {
            graph: updatedGraph,
            previousGraphId: originalGraph.graphId,
            summary: "Updated Extract Data only.",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.graph?.nodes[0]).toMatchObject({
      nodeId: "extract-data",
      status: "waiting",
      artifactRefs: [],
      summary: "Extract JSON rows.",
    });
    expect(result.graph?.nodes[1]).toBe(originalGraph.nodes[1]);
    expect(result.messages[0].content).toBe("Updated Extract Data only.");
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

  it("marks nodes that need permission and adds an actionable chat message", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph: graphWithNode,
        dirty: false,
      },
      [
        {
          type: "node.needs_permission",
          payload: {
            nodeId: "document-parse",
            permissions: ["read_project_files", "network_access"],
            scriptReview: {
              status: "reviewing",
              summary: "Script needs project file and network access.",
              permissions: ["read_project_files", "network_access"],
              riskLevel: "high",
              requiresApproval: true,
            },
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.graph?.nodes[0].status).toBe("needs_permission");
    expect(result.graph?.nodes[0].scriptReview).toMatchObject({
      status: "reviewing",
      riskLevel: "high",
      requiresApproval: true,
    });
    expect(result.messages[0].content).toContain("document-parse");
    expect(result.messages[0].content).toContain("read_project_files");
    expect(result.messages[0].content).toContain("network_access");
    expect(result.dirty).toBe(true);
  });

  it("marks nodes that require graph-run permissions", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph: graphWithNode,
        dirty: false,
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
    expect(result.graph?.nodes[0].scriptReview).toMatchObject({
      status: "reviewing",
      permissions: ["network"],
    });
    expect(result.messages[0].content).toContain("document-parse");
    expect(result.messages[0].content).toContain("network");
    expect(result.dirty).toBe(true);
  });

  it("adds a chat notice when a graph patch is suggested", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph: graphWithNode,
        dirty: false,
      },
      [
        {
          type: "graph.patch_suggested",
          payload: {
            reason: "node content-organize returned empty value",
            operations: [
              {
                op: "retry_node",
                node_id: "content-organize",
                reason: "node content-organize returned empty value",
              },
            ],
            requires_user_approval: false,
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.messages[0].content).toContain("建议修复");
    expect(result.messages[0].content).toContain("retry_node");
    expect(result.messages[0].content).toContain("content-organize");
    expect(result.graph).toBe(graphWithNode);
    expect(result.dirty).toBe(true);
  });

  it("stores runtime notices on matching nodes", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph: graphWithNode,
        dirty: false,
      },
      [
        {
          type: "node.runtime_notice",
          payload: {
            nodeId: "document-parse",
            notice: {
              kind: "duration_exceeded",
              message: "Node exceeded estimated duration.",
              actualDurationMs: 1200,
            },
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.graph?.nodes[0].runtimeNotice).toEqual({
      kind: "duration_exceeded",
      message: "Node exceeded estimated duration.",
      actualDurationMs: 1200,
    });
    expect(result.dirty).toBe(true);
  });

  it("records runtime notices in matching run history entries", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph: graphWithNode,
        dirty: false,
        activeRunId: "run-1",
        runHistory: [
          {
            runId: "run-1",
            startedAt: "2026-05-10T00:00:00.000Z",
            status: "completed",
            summary: "Run completed.",
            nodeRunIds: [],
            artifactRefs: [],
          },
        ],
      },
      [
        {
          type: "node.runtime_notice",
          payload: {
            nodeId: "document-parse",
            notice: {
              kind: "duration_exceeded",
              message: "Node exceeded estimated duration.",
              actualDurationMs: 1200,
            },
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.runHistory?.[0].runtimeNotices).toEqual([
      {
        nodeId: "document-parse",
        notice: {
          kind: "duration_exceeded",
          message: "Node exceeded estimated duration.",
          actualDurationMs: 1200,
        },
      },
    ]);
  });

  it("preserves runtime notices from run start through task completion", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph: graphWithNode,
        dirty: false,
        activeRunId: null,
        runHistory: [],
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
        {
          type: "node.runtime_notice",
          payload: {
            nodeId: "document-parse",
            notice: {
              kind: "duration_exceeded",
              message: "Node exceeded estimated duration.",
              actualDurationMs: 1200,
            },
          },
        },
        {
          type: "task.completed",
          payload: {
            taskId: "task-1",
            runId: "run-1",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.activeRunId).toBeNull();
    expect(result.graph?.nodes[0].runtimeNotice).toMatchObject({
      kind: "duration_exceeded",
      actualDurationMs: 1200,
    });
    expect(result.runHistory?.[0]).toMatchObject({
      runId: "run-1",
      status: "completed",
      runtimeNotices: [
        {
          nodeId: "document-parse",
          notice: {
            kind: "duration_exceeded",
            message: "Node exceeded estimated duration.",
            actualDurationMs: 1200,
          },
        },
      ],
    });
  });

  it("preserves the real run start time when a task completes", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph: graphWithNode,
        dirty: false,
        activeRunId: null,
        runHistory: [],
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
        {
          type: "task.completed",
          payload: {
            taskId: "task-1",
            runId: "run-1",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.runHistory?.[0]).toMatchObject({
      runId: "run-1",
      startedAt: "2026-05-10T00:00:00.000Z",
      status: "completed",
    });
    expect(result.runHistory?.[0].completedAt).not.toBe(
      result.runHistory?.[0].startedAt,
    );
  });

  it("preserves the real run start time when a run is cancelled", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph: graphWithNode,
        dirty: false,
        activeRunId: null,
        runHistory: [],
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
        {
          type: "run.cancelled",
          payload: {
            runId: "run-1",
            taskId: "task-1",
            completedAt: "2026-05-10T00:00:05.000Z",
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.runHistory?.[0]).toMatchObject({
      runId: "run-1",
      startedAt: "2026-05-10T00:00:00.000Z",
      completedAt: "2026-05-10T00:00:05.000Z",
      status: "cancelled",
    });
  });

  it("adds research completion artifact and chat summary", () => {
    const acceptedSources = [
      {
        ref: "[1]",
        title: "Python docs",
        url: "https://docs.python.org/3/",
        snippet: "Official docs.",
        sourceType: "official_docs",
        accepted: true,
        rejectionReason: null,
      },
    ];
    const rejectedSources = [
      {
        ref: "[2]",
        title: "Top10 Python",
        url: "https://top10.example/python",
        accepted: false,
        rejectionReason: "content_farm",
      },
    ];
    const result = reduceBackendEvents(
      {
        messages: [],
        graph: graphWithNode,
        dirty: false,
        artifacts: [],
      },
      [
        {
          type: "research.completed",
          payload: {
            taskId: "task-1",
            runId: "run-1",
            reportArtifactId: "research-report-abc123",
            reportArtifactPath: "D:\\Project\\artifacts\\research\\research-report-abc123.md",
            summary: "Research completed for Python packaging.",
            acceptedSources,
            rejectedSources,
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.messages[0].content).toContain(
      "Research completed for Python packaging.",
    );
    expect(result.messages[0].content).toContain(
      "D:\\Project\\artifacts\\research\\research-report-abc123.md",
    );
    expect(result.artifacts).toEqual([
      expect.objectContaining({
        artifactId: "research-report-abc123",
        path: "D:\\Project\\artifacts\\research\\research-report-abc123.md",
      }),
    ]);
    expect(result.messages[0].sources).toEqual(acceptedSources);
    expect(result.messages[0].rejectedSources).toEqual(rejectedSources);
    expect(result.messages[0].sourceMetadata).toEqual({
      answerStatus: "answered",
      accepted: acceptedSources,
      rejected: rejectedSources,
    });
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

  it("keeps error codes when failed nodes are later recorded", () => {
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
            error: "Search failed.",
            errorCode: "web_search_failed",
          },
        },
        {
          type: "node.run_recorded",
          payload: {
            record: {
              nodeRunId: "run-1-document-parse",
              runId: "run-1",
              nodeId: "document-parse",
              status: "failed",
              startedAt: "2026-05-10T00:00:00.000Z",
              completedAt: "2026-05-10T00:00:01.000Z",
              artifactRefs: [],
              error: "Search failed.",
            },
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.graph?.nodes[0].status).toBe("failed");
    expect(result.graph?.nodes[0].lastRun?.errorCode).toBe(
      "web_search_failed",
    );
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

  it("adds a fallback explanation when a replanned graph has no summary", () => {
    const result = reduceBackendEvents(
      {
        messages: [],
        graph,
        dirty: false,
      },
      [
        {
          type: "graph.replanned",
          payload: {
            graph: replannedGraph,
            previousGraphId: graph.graphId,
          },
        },
      ],
      createAssistantMessage,
    );

    expect(result.graph).toBe(replannedGraph);
    expect(result.messages[0].content).toContain(graph.graphId);
    expect(result.messages[0].content).toContain(replannedGraph.graphId);
  });
});
