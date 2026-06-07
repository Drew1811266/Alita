import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  App,
  buildPlanningClarificationSubmitPayload,
  buildPlanningChoiceSubmitPayload,
  buildResearchChoiceSubmitPayload,
  buildTemporaryScriptPermissionSubmitPayload,
  conversationHistoryForSubmit,
  didApplyBackendEvents,
  restorePendingPlanningChoiceAfterFailure,
  shouldRefreshAsrForPreferencesUpdate,
  submitUserMessageWithStreamFallbackForTest,
} from "./App";
import { selectAgentAttachments } from "../features/chat/useChatSessionController";
import type { AgentNode, ChatAttachment, NodeGraph } from "../shared/types";
import type { BackendEvent } from "../shared/events";
import type {
  PendingPlanningClarificationChoice,
  PendingPlanningConfirmationChoice,
  PendingPlanningChoice,
  PendingResearchChoice,
} from "./backendEvents";
import type { PreferencesView } from "../features/preferences/preferencesApi";

// @ts-expect-error Vitest runs in Node, but the app tsconfig intentionally only includes browser types.
import { readFileSync } from "node:fs";

const appSource = readFileSync("src/app/App.tsx", "utf8");

function preferencesViewWithSpeechModel(
  speechToTextModelId: string | null,
): PreferencesView {
  return {
    preferences: {
      schemaVersion: 3,
      recentProjects: [],
      modelDirectories: [],
      modelStorageDir: "D:\\Models",
      models: [],
      defaultModelId: null,
      modelAssignments: {
        agentChatModelId: null,
        speechToTextModelId,
      },
      agentModelMode: "local",
      activeApiProviderId: null,
      apiProviderConfigs: [],
      toolProviderConfigs: [
        {
          providerId: "internal",
          source: "internal",
          displayName: "Internal Tools",
          args: [],
          enabled: true,
          createdAt: "system",
          updatedAt: "system",
        },
      ],
      alitaMcpServer: {
        enabled: false,
        allowedToolIds: [],
        requireLocalAuth: true,
      },
      toolEnablement: {},
    },
    tools: [],
  };
}

describe("App", () => {
  it("builds compact conversation history for agent submits", () => {
    expect(
      conversationHistoryForSubmit(
        [
          {
            messageId: "m-1",
            role: "system",
            content: "开发版对话已启动。",
            attachments: [],
            createdAt: "2026-06-07T00:00:00.000Z",
          },
          {
            messageId: "m-2",
            role: "user",
            content: " 预算是一万元。 ",
            attachments: [],
            createdAt: "2026-06-07T00:00:01.000Z",
          },
          {
            messageId: "m-3",
            role: "assistant",
            content: "请补充用途。",
            attachments: [],
            createdAt: "2026-06-07T00:00:02.000Z",
          },
        ],
        2,
      ),
    ).toEqual([
      { role: "user", content: "预算是一万元。" },
      { role: "assistant", content: "请补充用途。" },
    ]);
  });

  it("starts on the project home before a project is active", () => {
    const markup = renderToStaticMarkup(<App />);

    expect(markup).toContain("新建工程");
    expect(markup).toContain("打开工程");
    expect(markup).toContain("最近工程");
    expect(markup).not.toContain("消息内容");
  });

  it("composes extracted feature controllers in the workbench shell", () => {
    expect(appSource).toContain("useProjectController()");
    expect(appSource).toContain("useChatSessionController()");
    expect(appSource).toContain("useGraphRunController({");
    expect(appSource).toContain("useGraphRuntimeController()");
    expect(appSource).toContain("usePermissionController");
    expect(appSource).toContain("useArtifactPreviewController()");
    expect(appSource).toContain("usePreferencesController()");
    expect(appSource).toContain("useVoiceInputController({");
    expect(appSource).not.toContain("const [voiceInput, setVoiceInput]");
    expect(appSource).not.toContain("const [messages, setMessages]");
    expect(appSource).not.toContain("const [draft, setDraft]");
    expect(appSource).not.toContain("const [activeProject, setActiveProject]");
  });

  it("refreshes ASR status when the speech-to-text assignment changes", () => {
    const withoutSpeechModel = preferencesViewWithSpeechModel(null);
    const withSpeechModel = preferencesViewWithSpeechModel("asr-1");

    expect(
      shouldRefreshAsrForPreferencesUpdate(null, withSpeechModel),
    ).toBe(true);
    expect(
      shouldRefreshAsrForPreferencesUpdate(
        withoutSpeechModel,
        withSpeechModel,
      ),
    ).toBe(true);
    expect(
      shouldRefreshAsrForPreferencesUpdate(withSpeechModel, withSpeechModel),
    ).toBe(false);
  });

  it("builds research choice submit payload from the original pending request", () => {
    const originalAttachment: ChatAttachment = {
      attachmentId: "original-1",
      name: "original.md",
      path: "D:\\Project\\original.md",
      sizeBytes: 10,
      mimeType: "text/markdown",
    };
    const pendingChoice: PendingResearchChoice = {
      taskId: "task-1",
      prompt: "Choose how to proceed.",
      choices: [
        { id: "quick_answer", label: "Quick answer" },
        { id: "research_flow", label: "Research flow" },
      ],
      submittedPayload: {
        taskId: "task-1",
        projectPath: "D:\\Project\\demo.alita",
        content: "Research current packaging tools",
        attachments: [originalAttachment],
      },
    };

    expect(
      buildResearchChoiceSubmitPayload({
        pendingChoice,
        choiceId: "research_flow",
      }),
    ).toEqual({
      taskId: "task-1",
      projectPath: "D:\\Project\\demo.alita",
      content: "Research current packaging tools",
      attachments: [originalAttachment],
      inquiryChoice: "research_flow",
    });
  });

  it("builds planning confirmation submit payloads with explicit decisions", () => {
    const pendingChoice: PendingPlanningConfirmationChoice = {
      kind: "planning.confirmation",
      taskId: "task-1",
      runId: "run-planning-1",
      threadId: "thread-planning-1",
      graphId: "graph-planning-1",
      summary: "Review the generated plan.",
      pendingChoice: {
        kind: "planning.confirmation",
        runId: "run-planning-1",
        threadId: "thread-planning-1",
        graphId: "graph-planning-1",
      },
      choices: [
        { id: "approve", label: "确认执行" },
        { id: "revise", label: "要求修订" },
        { id: "cancel", label: "取消" },
      ],
    };
    const graph: NodeGraph = { graphId: "graph-planning-1", nodes: [], edges: [] };

    expect(
      buildPlanningChoiceSubmitPayload({
        taskId: "task-1",
        projectPath: "D:\\Project\\demo.alita",
        pendingChoice,
        choiceId: "approve",
        content: "ignored for approval",
        currentGraph: graph,
        hasRunHistory: true,
        artifactRefs: ["artifact-1"],
      }),
    ).toEqual({
      taskId: "task-1",
      projectPath: "D:\\Project\\demo.alita",
      content: "",
      attachments: [],
      currentGraph: graph,
      hasRunHistory: true,
      artifactRefs: ["artifact-1"],
      pendingChoice: {
        kind: "planning.confirmation",
        runId: "run-planning-1",
        threadId: "thread-planning-1",
        graphId: "graph-planning-1",
        decision: "approve",
        revisionInstructions: [],
      },
    });

    expect(
      buildPlanningChoiceSubmitPayload({
        taskId: "task-1",
        pendingChoice,
        choiceId: "revise",
        content: "Add an explicit verification step.",
      }),
    ).toEqual({
      taskId: "task-1",
      content: "Add an explicit verification step.",
      attachments: [],
      pendingChoice: {
        kind: "planning.confirmation",
        runId: "run-planning-1",
        threadId: "thread-planning-1",
        graphId: "graph-planning-1",
        decision: "revise",
        revisionInstructions: ["Add an explicit verification step."],
      },
    });
  });

  it("builds planning clarification submit payloads for checkpoint resume", () => {
    const pendingChoice: PendingPlanningClarificationChoice = {
      kind: "planning.clarification",
      taskId: "task-clarify",
      runId: "run-clarify",
      threadId: "thread-clarify",
      question: "Who is the report for?",
      missingInputs: ["audience"],
      prompt: "Who is the report for?",
    };
    const graph: NodeGraph = { graphId: "graph-planning-1", nodes: [], edges: [] };

    expect(
      buildPlanningClarificationSubmitPayload({
        taskId: "task-clarify",
        projectPath: "D:\\Project\\demo.alita",
        pendingChoice,
        content: "The report is for executives.",
        currentGraph: graph,
        hasRunHistory: true,
        artifactRefs: ["artifact-1"],
      }),
    ).toEqual({
      taskId: "task-clarify",
      projectPath: "D:\\Project\\demo.alita",
      content: "The report is for executives.",
      attachments: [],
      currentGraph: graph,
      hasRunHistory: true,
      artifactRefs: ["artifact-1"],
      pendingChoice: {
        kind: "planning.clarification",
        runId: "run-clarify",
        threadId: "thread-clarify",
        answer: "The report is for executives.",
      },
    });
  });

  it("does not build a research choice submit payload without the original request", () => {
    expect(
      buildResearchChoiceSubmitPayload({
        pendingChoice: {
          taskId: "task-1",
          prompt: "Choose how to proceed.",
          choices: [{ id: "quick_answer", label: "Quick answer" }],
        },
        choiceId: "quick_answer",
      }),
    ).toBeNull();
  });

  it("does not reuse context attachments for a new web research request", () => {
    const oldAttachment: ChatAttachment = {
      attachmentId: "old-1",
      name: "old.docx",
      path: "D:\\Project\\old.docx",
      sizeBytes: 100,
      mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    };

    expect(
      selectAgentAttachments({
        content: "Research current GitHub trending projects and write a document.",
        sentAttachments: [],
        contextAttachments: [oldAttachment],
      }),
    ).toEqual([]);
  });

  it("reuses context attachments when the message explicitly references them", () => {
    const oldAttachment: ChatAttachment = {
      attachmentId: "old-1",
      name: "old.docx",
      path: "D:\\Project\\old.docx",
      sizeBytes: 100,
      mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    };

    expect(
      selectAgentAttachments({
        content: "Please summarize the attached document.",
        sentAttachments: [],
        contextAttachments: [oldAttachment],
      }),
    ).toEqual([oldAttachment]);
  });

  it("builds temporary script approval and rejection payloads from app state", () => {
    const graph: NodeGraph = { graphId: "graph-1", nodes: [], edges: [] };
    const node: AgentNode = {
      nodeId: "temporary-script",
      nodeType: "temporary_script",
      displayName: "Temporary script",
      status: "needs_permission",
      inputPorts: [],
      outputPorts: [],
      dependencies: [],
      summary: "Inspect project files.",
      createdBy: "agent",
      artifactRefs: [],
      retryCount: 0,
      position: { x: 0, y: 0 },
      scriptReview: {
        status: "reviewing",
        summary: "Needs review before execution.",
        permissions: ["read_project_files"],
        riskLevel: "high",
        requiresApproval: true,
        codePreview: "print('preview')",
        inputContract: { path: "string" },
        outputContract: { result: "string" },
        approvalFingerprint: "backend-review-token",
      },
    };

    expect(
      buildTemporaryScriptPermissionSubmitPayload({
        taskId: "task-1",
        node,
        decision: "approve",
        currentGraph: graph,
      }),
    ).toEqual({
      type: "temporary_script.permission",
      taskId: "task-1",
      nodeId: "temporary-script",
      decision: "approve",
      approvalFingerprint: "backend-review-token",
      currentGraph: graph,
    });

    expect(
      buildTemporaryScriptPermissionSubmitPayload({
        taskId: "task-1",
        node,
        decision: "reject",
        currentGraph: graph,
      }),
    ).toEqual({
      type: "temporary_script.permission",
      taskId: "task-1",
      nodeId: "temporary-script",
      decision: "reject",
      currentGraph: graph,
    });
  });

  it("fails closed when approving without a backend review fingerprint", () => {
    const node: AgentNode = {
      nodeId: "temporary-script",
      nodeType: "temporary_script",
      displayName: "Temporary script",
      status: "needs_permission",
      inputPorts: [],
      outputPorts: [],
      dependencies: [],
      summary: "Inspect project files.",
      createdBy: "agent",
      artifactRefs: [],
      retryCount: 0,
      position: { x: 0, y: 0 },
      scriptReview: {
        status: "reviewing",
        summary: "Needs review before execution.",
        permissions: ["read_project_files"],
        riskLevel: "high",
        requiresApproval: true,
        approvalFingerprint: null,
      },
    };

    expect(() =>
      buildTemporaryScriptPermissionSubmitPayload({
        taskId: "task-1",
        node,
        decision: "approve",
      }),
    ).toThrow("temporary script approval fingerprint is missing");
  });

  it("wires temporary script review callbacks into the app canvas", () => {
    expect(appSource).toContain("submitTemporaryScriptPermission(");
    expect(appSource).toContain("onApproveTemporaryScript={handleApproveTemporaryScript}");
    expect(appSource).toContain("onRejectTemporaryScript={handleRejectTemporaryScript}");
  });

  it("wires planning confirmation pending choices through the chat submit path", () => {
    expect(appSource).toContain("pendingPlanningChoiceRef");
    expect(appSource).toContain("setPendingPlanningChoice");
    expect(appSource).toContain("toPlanningConfirmationSubmitChoice");
    expect(appSource).toContain("onPlanningChoice={handlePlanningChoice}");
  });

  it("restores old planning choices only when no backend events were applied", () => {
    const pendingChoice: PendingPlanningChoice = {
      kind: "planning.confirmation",
      taskId: "task-1",
      runId: "run-planning-1",
      threadId: "thread-planning-1",
      graphId: "graph-planning-1",
      summary: "Review the generated plan.",
      pendingChoice: {
        kind: "planning.confirmation",
        runId: "run-planning-1",
        threadId: "thread-planning-1",
        graphId: "graph-planning-1",
      },
      choices: [{ id: "approve", label: "确认执行" }],
    };
    const newerPendingChoice: PendingPlanningChoice = {
      ...pendingChoice,
      runId: "run-planning-2",
      threadId: "thread-planning-2",
      summary: "Review the revised plan.",
      pendingChoice: {
        ...pendingChoice.pendingChoice,
        runId: "run-planning-2",
        threadId: "thread-planning-2",
      },
    };

    expect(
      restorePendingPlanningChoiceAfterFailure(pendingChoice, false),
    ).toBe(pendingChoice);
    expect(
      restorePendingPlanningChoiceAfterFailure(
        pendingChoice,
        true,
        newerPendingChoice,
      ),
    ).toBe(newerPendingChoice);
    expect(
      restorePendingPlanningChoiceAfterFailure(pendingChoice, true, null),
    ).toBeNull();
    expect(restorePendingPlanningChoiceAfterFailure(null)).toBeNull();
  });

  it("preserves newer planning choices after stream failures with backend progress", async () => {
    const planningEvent: BackendEvent = {
      type: "planning.confirmation_required",
      payload: {
        kind: "planning.confirmation",
        summary: "Review the new plan.",
        taskId: "task-1",
        runId: "run-planning-2",
        threadId: "thread-planning-2",
        graphId: "graph-planning-2",
        choices: [{ id: "approve", label: "确认执行" }],
        pendingChoice: {
          kind: "planning.confirmation",
          runId: "run-planning-2",
          threadId: "thread-planning-2",
          graphId: "graph-planning-2",
        },
      },
    };
    const oldPendingChoice: PendingPlanningChoice = {
      kind: "planning.confirmation",
      taskId: "task-1",
      runId: "run-planning-1",
      threadId: "thread-planning-1",
      graphId: "graph-planning-1",
      summary: "Review the old plan.",
      pendingChoice: {
        kind: "planning.confirmation",
        runId: "run-planning-1",
        threadId: "thread-planning-1",
        graphId: "graph-planning-1",
      },
      choices: [{ id: "approve", label: "确认执行" }],
    };
    const newerPendingChoice: PendingPlanningChoice = {
      kind: "planning.confirmation",
      taskId: planningEvent.payload.taskId,
      runId: planningEvent.payload.runId,
      threadId: planningEvent.payload.threadId,
      graphId: planningEvent.payload.graphId,
      summary: planningEvent.payload.summary,
      pendingChoice: planningEvent.payload.pendingChoice,
      choices: planningEvent.payload.choices,
    };
    const streamError = new Error("stream interrupted");
    const appliedEvents: BackendEvent[] = [];
    let currentPendingChoice: PendingPlanningChoice | null = oldPendingChoice;
    let fallbackCalled = false;
    let caughtError: unknown = null;

    try {
      await submitUserMessageWithStreamFallbackForTest({
        payload: {
          taskId: "task-1",
          content: "Confirm plan",
          attachments: [],
        },
        createSession: async () => "model-session-1",
        submitStream: async (_payload, onEvent) => {
          onEvent(planningEvent);
          throw streamError;
        },
        submitFallback: async () => {
          fallbackCalled = true;
          return [];
        },
        onEvent: (event) => {
          appliedEvents.push(event);
          currentPendingChoice = newerPendingChoice;
        },
      });
    } catch (error) {
      caughtError = error;
    }

    expect(didApplyBackendEvents(caughtError)).toBe(true);
    expect(
      restorePendingPlanningChoiceAfterFailure(
        oldPendingChoice,
        didApplyBackendEvents(caughtError),
        currentPendingChoice,
      ),
    ).toBe(newerPendingChoice);

    expect(appliedEvents).toEqual([planningEvent]);
    expect(fallbackCalled).toBe(false);
  });

  it("restores pending planning choices in typed and button submit failure paths", () => {
    const restoreCalls =
      appSource.match(
        /restorePendingPlanningChoiceAfterFailure\(\s*capturedPlanningChoice,\s*didApplyBackendEvents\(error\),\s*pendingPlanningChoiceRef\.current,\s*\)/g,
      ) ?? [];

    expect(restoreCalls).toHaveLength(2);
  });
});
