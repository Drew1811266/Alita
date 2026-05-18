import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  App,
  buildResearchChoiceSubmitPayload,
  buildTemporaryScriptPermissionSubmitPayload,
  shouldRefreshAsrForPreferencesUpdate,
} from "./App";
import type { AgentNode, ChatAttachment, NodeGraph } from "../shared/types";
import type { PendingResearchChoice } from "./backendEvents";
import type { PreferencesView } from "../features/preferences/preferencesApi";

// @ts-expect-error Vitest runs in Node, but the app tsconfig intentionally only includes browser types.
import { readFileSync } from "node:fs";

const appSource = readFileSync("src/app/App.tsx", "utf8");

function preferencesViewWithSpeechModel(
  speechToTextModelId: string | null,
): PreferencesView {
  return {
    preferences: {
      schemaVersion: 2,
      recentProjects: [],
      modelDirectories: [],
      modelStorageDir: "D:\\Models",
      models: [],
      defaultModelId: null,
      modelAssignments: {
        agentChatModelId: null,
        speechToTextModelId,
      },
      toolEnablement: {},
    },
    tools: [],
  };
}

describe("App", () => {
  it("starts on the project home before a project is active", () => {
    const markup = renderToStaticMarkup(<App />);

    expect(markup).toContain("新建工程");
    expect(markup).toContain("打开工程");
    expect(markup).toContain("最近工程");
    expect(markup).not.toContain("消息内容");
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
      content: "Research current packaging tools",
      attachments: [originalAttachment],
      inquiryChoice: "research_flow",
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
        approvalFingerprint: "sha256:abc123",
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
      approvalFingerprint: "sha256:abc123",
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

  it("wires temporary script review callbacks into the app canvas", () => {
    expect(appSource).toContain("submitTemporaryScriptPermission(");
    expect(appSource).toContain("onApproveTemporaryScript={handleApproveTemporaryScript}");
    expect(appSource).toContain("onRejectTemporaryScript={handleRejectTemporaryScript}");
  });
});
