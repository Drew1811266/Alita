import "./app.css";

import { useEffect, useRef, useState } from "react";

import { NodeCanvas } from "../features/canvas/NodeCanvas";
import {
  openArtifact,
  revealArtifact,
} from "../features/artifacts/artifactApi";
import { pickChatAttachments } from "../features/chat/attachmentApi";
import { ChatPanel } from "../features/chat/ChatPanel";
import {
  addModelFile,
  getPreferences,
  importModelFile,
  pickModelDirectory,
  pickModelFile,
  scanModelDirectory,
  setDefaultModel,
  setModelStorageDirectory,
  setToolEnabled,
  type PreferencesView,
} from "../features/preferences/preferencesApi";
import { PreferencesDialog } from "../features/preferences/PreferencesDialog";
import {
  createProject,
  openProject,
  pickCreateProjectPath,
  pickOpenProjectPath,
  pickSaveProjectAsPath,
  saveProject,
} from "../features/project/projectApi";
import { ProjectHome } from "../features/project/ProjectHome";
import {
  cancelNodeGraphRun,
  runNodeGraphStream,
  type RunNodeGraphMode,
  submitUserMessage,
  submitUserMessageStream,
} from "../features/task/useTaskEvents";
import { WorkbenchTopBar } from "../features/workbench/WorkbenchTopBar";
import { reduceBackendEvents } from "./backendEvents";
import type {
  AlitaProject,
  ArtifactRef,
  ChatAttachment,
  ChatMessage,
  NodeGraph,
  ProjectAttachmentRef,
  ProjectOpenResult,
  ProjectOpenWarning,
  RunHistoryEntry,
} from "../shared/types";
import type { BackendEvent } from "../shared/events";

const initialMessages: ChatMessage[] = [
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

function createId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

function createMessage(
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

export function App() {
  const [activeProject, setActiveProject] = useState<AlitaProject | null>(
    null,
  );
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [draft, setDraft] = useState("");
  const [pendingAttachments, setPendingAttachments] = useState<
    ChatAttachment[]
  >([]);
  const [contextAttachments, setContextAttachments] = useState<
    ChatAttachment[]
  >([]);
  const [graph, setGraph] = useState<NodeGraph | null>(null);
  const graphRef = useRef<NodeGraph | null>(null);
  const [projectWarnings, setProjectWarnings] = useState<ProjectOpenWarning[]>(
    [],
  );
  const [projectError, setProjectError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [preferencesOpen, setPreferencesOpen] = useState(false);
  const [graphRunning, setGraphRunning] = useState(false);
  const [graphCancelling, setGraphCancelling] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const activeRunIdRef = useRef<string | null>(null);
  const [runHistory, setRunHistory] = useState<RunHistoryEntry[]>([]);
  const runHistoryRef = useRef<RunHistoryEntry[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactRef[]>([]);
  const artifactsRef = useRef<ArtifactRef[]>([]);
  const [preferencesView, setPreferencesView] =
    useState<PreferencesView | null>(null);
  const [preferencesLoading, setPreferencesLoading] = useState(false);
  const [preferencesError, setPreferencesError] = useState<string | null>(null);
  const [recentProjects, setRecentProjects] = useState<string[]>([]);

  useEffect(() => {
    getPreferences()
      .then((view) => setRecentProjects(view.preferences.recentProjects))
      .catch(() => setRecentProjects([]));
  }, []);

  useEffect(() => {
    graphRef.current = graph;
  }, [graph]);

  useEffect(() => {
    activeRunIdRef.current = activeRunId;
  }, [activeRunId]);

  useEffect(() => {
    runHistoryRef.current = runHistory;
  }, [runHistory]);

  useEffect(() => {
    artifactsRef.current = artifacts;
  }, [artifacts]);

  const applyProjectOpenResult = (result: ProjectOpenResult) => {
    const projectMessages =
      result.project.messages.length > 0 ? result.project.messages : initialMessages;
    setActiveProject({ ...result.project, messages: projectMessages });
    setMessages(projectMessages);
    setGraph(result.project.graph);
    setRunHistory(result.project.runHistory);
    runHistoryRef.current = result.project.runHistory;
    setArtifacts([]);
    artifactsRef.current = [];
    setActiveRunId(null);
    activeRunIdRef.current = null;
    setGraphRunning(false);
    setGraphCancelling(false);
    setContextAttachments(
      result.project.attachments.map((attachment) => ({
        attachmentId: attachment.attachmentId,
        name: attachment.name,
        path: attachment.path,
        sizeBytes: attachment.sizeBytes,
        mimeType: attachment.mimeType,
      })),
    );
    setProjectWarnings(result.warnings);
    setDirty(false);
    setRecentProjects((current) =>
      [
        result.project.path,
        ...current.filter((path) => path !== result.project.path),
      ].slice(0, 8),
    );
  };

  const handleAddFile = async () => {
    try {
      setProjectError(null);
      const selectedAttachments = await pickChatAttachments();
      if (selectedAttachments.length === 0) {
        return;
      }

      setPendingAttachments((current) => {
        const existingPaths = new Set(
          current.map((attachment) => attachment.path),
        );
        return [
          ...current,
          ...selectedAttachments.filter(
            (attachment) => !existingPaths.has(attachment.path),
          ),
        ];
      });
    } catch (error) {
      setProjectError(String(error));
    }
  };

  const handleCreateProject = async () => {
    const path = await pickCreateProjectPath();
    if (!path) {
      return;
    }

    const fileName = path.split(/[\\/]/).pop() ?? "未命名工程.alita";
    const name = fileName.replace(/\.alita$/i, "");

    try {
      setProjectError(null);
      const result = await createProject(path, name);
      applyProjectOpenResult(result);
    } catch (error) {
      setProjectError(String(error));
    }
  };

  const handleOpenProject = async () => {
    const path = await pickOpenProjectPath();
    if (!path) {
      return;
    }

    try {
      setProjectError(null);
      const result = await openProject(path);
      applyProjectOpenResult(result);
    } catch (error) {
      setProjectError(String(error));
    }
  };

  const applyBackendEvent = (event: BackendEvent) => {
    setMessages((current) => {
      const result = reduceBackendEvents(
        {
          messages: current,
          graph: graphRef.current,
          dirty: false,
          activeRunId: activeRunIdRef.current,
          runHistory: runHistoryRef.current,
          artifacts: artifactsRef.current,
        },
        [event],
        (eventContent) => createMessage("assistant", eventContent),
      );

      graphRef.current = result.graph;
      setGraph(result.graph);
      activeRunIdRef.current = result.activeRunId ?? null;
      runHistoryRef.current = result.runHistory ?? runHistoryRef.current;
      artifactsRef.current = result.artifacts ?? artifactsRef.current;
      setActiveRunId(activeRunIdRef.current);
      setRunHistory(runHistoryRef.current);
      setArtifacts(artifactsRef.current);
      if (result.dirty) {
        setDirty(true);
      }

      return result.messages;
    });
  };

  const runGraphWithMode = async (mode: RunNodeGraphMode) => {
    if (!activeProject || !graph || graphRunning) {
      return;
    }

    const runId = createId("run");

    try {
      setProjectError(null);
      const disabledToolIds = await resolveDisabledToolIds();
      setGraphRunning(true);
      setGraphCancelling(false);
      setActiveRunId(runId);
      activeRunIdRef.current = runId;
      await runNodeGraphStream(
        {
          runId,
          taskId: activeProject.projectId,
          projectPath: activeProject.path,
          graph,
          attachments: contextAttachments,
          mode,
          disabledToolIds,
        },
        applyBackendEvent,
      );
    } catch (error) {
      setMessages((current) => [
        ...current,
        createMessage("assistant", `流程执行失败：${String(error)}`),
      ]);
      setDirty(true);
    } finally {
      setGraphRunning(false);
      setGraphCancelling(false);
    }
  };

  const resolveDisabledToolIds = async (): Promise<string[]> => {
    let view = preferencesView;
    if (!view) {
      try {
        view = await getPreferences();
        setPreferencesView(view);
        setRecentProjects(view.preferences.recentProjects);
      } catch {
        return [];
      }
    }

    return view.tools.filter((tool) => !tool.enabled).map((tool) => tool.toolId);
  };

  const handleRunGraph = async () => {
    await runGraphWithMode({ type: "full" });
  };

  const handleRetryFailed = async () => {
    const sourceRunId = lastRunHistoryEntry(runHistory)?.runId;
    if (!sourceRunId) {
      await runGraphWithMode({ type: "full" });
      return;
    }
    await runGraphWithMode({ type: "failed_only", sourceRunId });
  };

  const handleRunFromNode = async (nodeId: string) => {
    const sourceRunId = lastRunHistoryEntry(runHistory)?.runId;
    await runGraphWithMode(
      sourceRunId
        ? { type: "from_node", nodeId, sourceRunId }
        : { type: "from_node", nodeId },
    );
  };

  const handleStopGraph = async () => {
    if (!activeRunId || graphCancelling) {
      return;
    }

    try {
      setGraphCancelling(true);
      await cancelNodeGraphRun(activeRunId);
    } catch (error) {
      setProjectError(String(error));
      setGraphCancelling(false);
    }
  };

  const handleOpenArtifact = async (path: string) => {
    try {
      setProjectError(null);
      await openArtifact(path);
    } catch (error) {
      setProjectError(String(error));
    }
  };

  const handleRevealArtifact = async (path: string) => {
    try {
      setProjectError(null);
      await revealArtifact(path);
    } catch (error) {
      setProjectError(String(error));
    }
  };

  const handleSend = async () => {
    if (!activeProject) {
      return;
    }

    const content = draft.trim();
    if (!content && pendingAttachments.length === 0) {
      return;
    }

    const sentAttachments = [...pendingAttachments];
    const agentAttachments =
      sentAttachments.length > 0 ? sentAttachments : contextAttachments;
    const userMessage = createMessage(
      "user",
      content || "已添加文档。",
      sentAttachments,
    );

    setMessages((current) => [...current, userMessage]);
    setDraft("");
    setPendingAttachments([]);
    setDirty(true);

    try {
      const payload = {
        taskId: activeProject.projectId,
        content: userMessage.content,
        attachments: agentAttachments,
      };

      let receivedStreamEvent = false;
      try {
        await submitUserMessageStream(payload, (event) => {
          receivedStreamEvent = true;
          applyBackendEvent(event);
        });
      } catch (streamError) {
        if (receivedStreamEvent) {
          throw streamError;
        }

        const events = await submitUserMessage(payload);
        for (const event of events) {
          applyBackendEvent(event);
        }
      }

      if (sentAttachments.length > 0) {
        setContextAttachments(sentAttachments);
      }
    } catch (error) {
      setMessages((current) => [
        ...current,
        createMessage("assistant", `后台 Agent 暂不可用：${String(error)}`),
      ]);
      setDirty(true);
    }
  };

  const buildCurrentProject = (): AlitaProject | null => {
    if (!activeProject) {
      return null;
    }

    return {
      ...activeProject,
      messages,
      graph,
      runHistory,
      attachments: collectProjectAttachments(
        activeProject.attachments,
        contextAttachments,
        messages,
      ),
    };
  };

  const handleSaveProject = async () => {
    const project = buildCurrentProject();
    if (!project) {
      return;
    }

    try {
      setSaving(true);
      const result = await saveProject(project);
      applyProjectOpenResult(result);
    } catch (error) {
      setProjectError(String(error));
    } finally {
      setSaving(false);
    }
  };

  const handleSaveProjectAs = async () => {
    const project = buildCurrentProject();
    if (!project) {
      return;
    }

    const path = await pickSaveProjectAsPath(project.path);
    if (!path) {
      return;
    }

    try {
      setSaving(true);
      const result = await saveProject(project, path);
      applyProjectOpenResult(result);
    } catch (error) {
      setProjectError(String(error));
    } finally {
      setSaving(false);
    }
  };

  const handleOpenPreferences = async () => {
    setPreferencesOpen(true);
    setPreferencesLoading(true);
    setPreferencesError(null);
    try {
      const view = await getPreferences();
      setPreferencesView(view);
      setRecentProjects(view.preferences.recentProjects);
    } catch (error) {
      setPreferencesError(String(error));
    } finally {
      setPreferencesLoading(false);
    }
  };

  const handleAddModel = async () => {
    const path = await pickModelFile();
    if (!path) {
      return;
    }
    try {
      setPreferencesView(await addModelFile(path));
    } catch (error) {
      setPreferencesError(String(error));
    }
  };

  const handleImportModel = async () => {
    const path = await pickModelFile();
    if (!path) {
      return;
    }
    try {
      setPreferencesError(null);
      setPreferencesView(await importModelFile(path));
    } catch (error) {
      setPreferencesError(String(error));
    }
  };

  const handleScanModelDirectory = async () => {
    const path = await pickModelDirectory();
    if (!path) {
      return;
    }
    try {
      setPreferencesView(await scanModelDirectory(path));
    } catch (error) {
      setPreferencesError(String(error));
    }
  };

  const handleSetModelStorageDirectory = async () => {
    const path = await pickModelDirectory();
    if (!path) {
      return;
    }
    try {
      setPreferencesError(null);
      setPreferencesView(await setModelStorageDirectory(path));
    } catch (error) {
      setPreferencesError(String(error));
    }
  };

  const handleSetDefaultModel = async (modelId: string) => {
    try {
      setPreferencesError(null);
      setPreferencesView(await setDefaultModel(modelId));
    } catch (error) {
      setPreferencesError(String(error));
    }
  };

  const handleSetToolEnabled = async (toolId: string, enabled: boolean) => {
    try {
      setPreferencesView(await setToolEnabled(toolId, enabled));
    } catch (error) {
      setPreferencesError(String(error));
    }
  };

  const preferencesDialog = (
    <PreferencesDialog
      error={preferencesError}
      loading={preferencesLoading}
      onAddModel={handleAddModel}
      onClose={() => setPreferencesOpen(false)}
      onImportModel={handleImportModel}
      onScanModelDirectory={handleScanModelDirectory}
      onSetDefaultModel={handleSetDefaultModel}
      onSetModelStorageDirectory={handleSetModelStorageDirectory}
      onSetToolEnabled={handleSetToolEnabled}
      open={preferencesOpen}
      view={preferencesView}
    />
  );

  if (!activeProject) {
    return (
      <>
        <ProjectHome
          error={projectError}
          onCreateProject={handleCreateProject}
          onOpenPreferences={handleOpenPreferences}
          onOpenProject={handleOpenProject}
          recentProjects={recentProjects}
        />
        {preferencesDialog}
      </>
    );
  }

  return (
    <main className="appShell">
      <WorkbenchTopBar
        dirty={dirty}
        onOpenPreferences={handleOpenPreferences}
        onSave={handleSaveProject}
        onSaveAs={handleSaveProjectAs}
        projectName={activeProject.name}
        saving={saving}
      />
      {projectError || projectWarnings.length > 0 ? (
        <div className="projectNoticeStack">
          {projectError ? (
            <div className="projectWarningBar">{projectError}</div>
          ) : null}
          {projectWarnings.length > 0 ? (
            <div className="projectWarningBar">
              {projectWarnings.map((warning) => warning.message).join("；")}
            </div>
          ) : null}
        </div>
      ) : null}
      <section className="chatColumn" aria-label="对话区域">
        <ChatPanel
          messages={messages}
          pendingAttachments={pendingAttachments}
          draft={draft}
          onDraftChange={setDraft}
          onSend={handleSend}
          onAddFile={handleAddFile}
        />
      </section>
      <section className="canvasColumn" aria-label="节点画布区域">
        <NodeCanvas
          graph={graph}
          running={graphRunning}
          cancelling={graphCancelling}
          canRetryFailed={graph?.nodes.some((node) => node.status === "failed")}
          onRun={handleRunGraph}
          onStop={handleStopGraph}
          onRetryFailed={handleRetryFailed}
          onRunFromNode={handleRunFromNode}
          onOpenArtifact={handleOpenArtifact}
          onRevealArtifact={handleRevealArtifact}
        />
      </section>
      {preferencesDialog}
    </main>
  );
}

function collectProjectAttachments(
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

function lastRunHistoryEntry(
  runHistory: RunHistoryEntry[],
): RunHistoryEntry | undefined {
  return runHistory.length > 0 ? runHistory[runHistory.length - 1] : undefined;
}
