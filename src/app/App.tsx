import "./app.css";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { NodeCanvas } from "../features/canvas/NodeCanvas";
import { ArtifactPreviewPanel } from "../features/artifacts/ArtifactPreviewPanel";
import {
  artifactFileUrl,
  openArtifact,
  readArtifactText,
  revealArtifact,
} from "../features/artifacts/artifactApi";
import { resolvePreviewArtifactForNode } from "../features/artifacts/artifactPreview";
import {
  detectArtifactPreviewKind,
  shouldReadArtifactText,
} from "../features/artifacts/artifactPreviewKind";
import { useArtifactPreviewController } from "../features/artifacts/useArtifactPreviewController";
import { pickChatAttachments } from "../features/chat/attachmentApi";
import { ChatPanel } from "../features/chat/ChatPanel";
import {
  collectProjectAttachments,
  createId,
  createMessage,
  initialMessages,
  selectAgentAttachments,
  useChatSessionController,
} from "../features/chat/useChatSessionController";
import { usePermissionController } from "../features/permissions/usePermissionController";
import { useVoiceInputController } from "../features/voice/useVoiceInputController";
import {
  addModelFile,
  addSpeechToTextModelDirectory,
  deleteApiProviderConfig,
  deleteMcpToolProviderConfig,
  fetchApiProviderModels,
  importModelFile,
  pickModelDirectory,
  pickModelFile,
  pickSpeechToTextModelDirectory,
  prepareAgentModelSession,
  refreshMcpToolProviderTools,
  saveApiProviderConfig,
  saveMcpToolProviderConfig,
  scanModelDirectory,
  setActiveApiProvider,
  setAgentModelMode,
  setDefaultModel,
  setModelAssignment,
  setModelStorageDirectory,
  setToolEnabled,
  testApiProviderConnection,
  type ApiProviderConnectionResult,
  type ModelAssignmentRole,
  type PreferencesView,
  type SaveApiProviderPayload,
  type SaveMcpToolProviderPayload,
} from "../features/preferences/preferencesApi";
import { PreferencesDialog } from "../features/preferences/PreferencesDialog";
import { usePreferencesController } from "../features/preferences/usePreferencesController";
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
  rememberRecentProject,
  useProjectController,
} from "../features/project/useProjectController";
import {
  cancelNodeGraphRun,
  createTemporaryScriptPermissionPayload,
  runNodeGraphStream,
  submitResearchChoice,
  type RunNodeGraphMode,
  type SubmitMessagePayload,
  submitUserMessage,
  submitUserMessageStream,
  submitTemporaryScriptPermission,
  type TemporaryScriptPermissionDecision,
  type TemporaryScriptPermissionPayload,
} from "../features/task/useTaskEvents";
import {
  reduceGraphRunControllerEvents,
  useGraphRunController,
} from "../features/task/useGraphRunController";
import { useGraphRuntimeController } from "../features/task/useGraphRuntimeController";
import { WorkbenchTopBar } from "../features/workbench/WorkbenchTopBar";
import {
  toGraphOverwriteSubmitChoice,
  type PendingGraphOverwriteChoice,
  type PendingResearchChoice,
} from "./backendEvents";
import type {
  AlitaProject,
  AgentNode,
  ArtifactRef,
  ChatMessage,
  NodeGraph,
  ProjectOpenResult,
  RunHistoryEntry,
} from "../shared/types";
import type { BackendEvent } from "../shared/events";
import type { ResearchChoiceId } from "../shared/events";

function resolveLocalStateAction<T>(action: LocalStateAction<T>, current: T): T {
  return typeof action === "function"
    ? (action as (current: T) => T)(current)
    : action;
}

export const createAgentSession = async (): Promise<string | null> => {
  try {
    return await prepareAgentModelSession();
  } catch (error) {
    throw new Error(`Agent 模型配置不可用：${formatUnknownError(error)}`);
  }
};

type SubmitUserMessageWithStreamFallbackArgs = {
  payload: SubmitMessagePayload;
  createSession: () => Promise<string | null>;
  submitStream: (
    payload: SubmitMessagePayload,
    onEvent: (event: BackendEvent) => void,
  ) => Promise<void>;
  submitFallback: (payload: SubmitMessagePayload) => Promise<BackendEvent[]>;
  onEvent: (event: BackendEvent) => void;
};

type LocalStateAction<T> = T | ((current: T) => T);

async function submitUserMessageWithStreamFallback({
  payload,
  createSession,
  submitStream,
  submitFallback,
  onEvent,
}: SubmitUserMessageWithStreamFallbackArgs): Promise<void> {
  const streamModelSessionId = await createSession();
  let receivedStreamEvent = false;
  try {
    await submitStream(
      { ...payload, modelSessionId: streamModelSessionId },
      (event) => {
        receivedStreamEvent = true;
        onEvent(event);
      },
    );
  } catch (streamError) {
    if (receivedStreamEvent) {
      throw streamError;
    }

    const fallbackModelSessionId = await createSession();
    const events = await submitFallback({
      ...payload,
      modelSessionId: fallbackModelSessionId,
    });
    for (const event of events) {
      onEvent(event);
    }
  }
}

export const submitUserMessageWithStreamFallbackForTest =
  submitUserMessageWithStreamFallback;

export function App() {
  const projectController = useProjectController();
  const {
    activeProject,
    projectWarnings,
    projectError,
    saving,
    recentProjects,
  } = projectController.state;
  const {
    setActiveProject,
    setProjectWarnings,
    setProjectError,
    setSaving,
    setRecentProjects,
  } = projectController;

  const chatSessionController = useChatSessionController();
  const { draft, pendingAttachments, contextAttachments } =
    chatSessionController.state;
  const {
    setDraft,
    applyVoiceTranscript,
    setPendingAttachments,
    setContextAttachments,
    addPendingAttachments,
  } = chatSessionController;

  const graphRuntimeController = useGraphRuntimeController();
  const { running: graphRunning, cancelling: graphCancelling } =
    graphRuntimeController.state;
  const {
    activeRunIdRef,
    setRunning: setGraphRunning,
    setCancelling: setGraphCancelling,
    setActiveRunIdRef,
  } = graphRuntimeController;

  const permissionController = usePermissionController<
    PendingResearchChoice,
    PendingGraphOverwriteChoice
  >();
  const {
    pendingResearchChoiceRef,
    pendingGraphOverwriteChoiceRef,
    syncPendingPermissionChoices,
    clearPendingPermissionChoices,
  } = permissionController;

  const graphRunController = useGraphRunController({
    messages: initialMessages,
  });
  const {
    messages,
    graph,
    runHistory,
    artifacts,
    pendingResearchChoice,
    pendingGraphOverwriteChoice,
    activeRunId,
    dirty,
  } = graphRunController.state;
  const setGraphRunState = graphRunController.setState;
  const messagesRef = useRef<ChatMessage[]>(initialMessages);
  const voiceInputController = useVoiceInputController({
    onTranscript: applyVoiceTranscript,
  });
  const { voiceInput } = voiceInputController.state;
  const {
    handleDraftSelectionChange,
    handleVoiceToggle,
    refreshVoiceInputAvailability,
  } = voiceInputController;
  const graphRef = useRef<NodeGraph | null>(null);
  const [preferencesOpen, setPreferencesOpen] = useState(false);
  const runHistoryRef = useRef<RunHistoryEntry[]>([]);
  const artifactsRef = useRef<ArtifactRef[]>([]);
  const artifactPreviewController = useArtifactPreviewController();
  const {
    clearPreview,
    setArtifactPreview,
    setPreviewError,
    setPreviewLoading,
    startPreviewLoad,
  } = artifactPreviewController;
  const {
    artifactPreview,
    loading: artifactPreviewLoading,
    error: artifactPreviewError,
  } = artifactPreviewController.state;
  const preferencesController = usePreferencesController();
  const {
    preferences: preferencesView,
    loading: preferencesLoading,
    error: preferencesError,
  } = preferencesController.state;
  const {
    reloadPreferences,
    setPreferences,
    setPreferencesError,
  } = preferencesController;

  const setMessages = useCallback(
    (action: LocalStateAction<ChatMessage[]>) => {
      setGraphRunState((current) => {
        const messages = resolveLocalStateAction(action, current.messages);
        messagesRef.current = messages;
        return { ...current, messages };
      });
    },
    [setGraphRunState],
  );

  const setGraph = useCallback(
    (action: LocalStateAction<NodeGraph | null>) => {
      setGraphRunState((current) => {
        const graph = resolveLocalStateAction(action, current.graph);
        graphRef.current = graph;
        return { ...current, graph };
      });
    },
    [setGraphRunState],
  );

  const setRunHistory = useCallback(
    (action: LocalStateAction<RunHistoryEntry[]>) => {
      setGraphRunState((current) => {
        const runHistory = resolveLocalStateAction(action, current.runHistory);
        runHistoryRef.current = runHistory;
        return { ...current, runHistory };
      });
    },
    [setGraphRunState],
  );

  const setArtifacts = useCallback(
    (action: LocalStateAction<ArtifactRef[]>) => {
      setGraphRunState((current) => {
        const artifacts = resolveLocalStateAction(action, current.artifacts);
        artifactsRef.current = artifacts;
        return { ...current, artifacts };
      });
    },
    [setGraphRunState],
  );

  const setPendingResearchChoice = useCallback(
    (action: LocalStateAction<PendingResearchChoice | null>) => {
      setGraphRunState((current) => {
        const pendingResearchChoice = resolveLocalStateAction(
          action,
          current.pendingResearchChoice,
        );
        pendingResearchChoiceRef.current = pendingResearchChoice;
        return { ...current, pendingResearchChoice };
      });
    },
    [setGraphRunState],
  );

  const setPendingGraphOverwriteChoice = useCallback(
    (action: LocalStateAction<PendingGraphOverwriteChoice | null>) => {
      setGraphRunState((current) => {
        const pendingGraphOverwriteChoice = resolveLocalStateAction(
          action,
          current.pendingGraphOverwriteChoice,
        );
        pendingGraphOverwriteChoiceRef.current = pendingGraphOverwriteChoice;
        return { ...current, pendingGraphOverwriteChoice };
      });
    },
    [setGraphRunState],
  );

  const setActiveRunId = useCallback(
    (action: LocalStateAction<string | null>) => {
      setGraphRunState((current) => {
        const activeRunId = resolveLocalStateAction(
          action,
          current.activeRunId,
        );
        setActiveRunIdRef(activeRunId);
        return { ...current, activeRunId };
      });
    },
    [setActiveRunIdRef, setGraphRunState],
  );

  const setDirty = useCallback(
    (action: LocalStateAction<boolean>) => {
      setGraphRunState((current) => ({
        ...current,
        dirty: resolveLocalStateAction(action, current.dirty),
      }));
    },
    [setGraphRunState],
  );

  const setSelectedCanvasNode = useCallback(
    (node: AgentNode | null) => {
      setGraphRunState((current) => ({
        ...current,
        selectedCanvasNode: node
          ? current.graph?.nodes.find(
              (candidate) => candidate.nodeId === node.nodeId,
            ) ?? node
          : null,
      }));
    },
    [setGraphRunState],
  );

  useEffect(() => {
    reloadPreferences()
      .then((view) => setRecentProjects(view.preferences.recentProjects))
      .catch(() => setRecentProjects([]));
  }, [reloadPreferences]);

  useEffect(() => {
    graphRef.current = graph;
  }, [graph]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    syncPendingPermissionChoices({
      pendingResearchChoice,
      pendingGraphOverwriteChoice,
    });
  }, [
    pendingGraphOverwriteChoice,
    pendingResearchChoice,
    syncPendingPermissionChoices,
  ]);

  useEffect(() => {
    setActiveRunIdRef(activeRunId);
  }, [activeRunId, setActiveRunIdRef]);

  useEffect(() => {
    runHistoryRef.current = runHistory;
  }, [runHistory]);

  useEffect(() => {
    artifactsRef.current = artifacts;
  }, [artifacts]);

  const selectedCanvasNode = useMemo<AgentNode | null>(
    () =>
      graph?.nodes.find(
        (node) =>
          node.nodeId === graphRunController.state.selectedCanvasNode?.nodeId,
      ) ?? null,
    [graph, graphRunController.state.selectedCanvasNode],
  );

  const selectedPreviewArtifact = useMemo(
    () => resolvePreviewArtifactForNode(selectedCanvasNode, artifacts),
    [selectedCanvasNode, artifacts],
  );

  const selectedPreviewPath = selectedPreviewArtifact?.path ?? null;
  const selectedPreviewKind = selectedPreviewPath
    ? detectArtifactPreviewKind(selectedPreviewPath)
    : "unsupported";
  const selectedPreviewFileUrl = selectedPreviewPath
    ? artifactFileUrl(selectedPreviewPath)
    : null;

  useEffect(() => {
    let cancelled = false;

    if (!selectedPreviewPath || !shouldReadArtifactText(selectedPreviewKind)) {
      clearPreview();
      return () => {
        cancelled = true;
      };
    }

    startPreviewLoad();
    readArtifactText(selectedPreviewPath)
      .then((preview) => {
        if (!cancelled) {
          setArtifactPreview(preview);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setPreviewError(String(error));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setPreviewLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [
    clearPreview,
    selectedPreviewKind,
    selectedPreviewPath,
    setArtifactPreview,
    setPreviewError,
    setPreviewLoading,
    startPreviewLoad,
  ]);

  const applyProjectOpenResult = (result: ProjectOpenResult) => {
    const projectMessages =
      result.project.messages.length > 0
        ? result.project.messages
        : initialMessages;
    setActiveProject({ ...result.project, messages: projectMessages });
    setMessages(projectMessages);
    messagesRef.current = projectMessages;
    setGraph(result.project.graph);
    setRunHistory(result.project.runHistory);
    runHistoryRef.current = result.project.runHistory;
    setArtifacts([]);
    artifactsRef.current = [];
    setSelectedCanvasNode(null);
    setActiveRunId(null);
    setActiveRunIdRef(null);
    setPendingResearchChoice(null);
    setPendingGraphOverwriteChoice(null);
    clearPendingPermissionChoices();
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
      rememberRecentProject(current, result.project.path),
    );
  };

  const handleAddFile = async () => {
    try {
      setProjectError(null);
      const selectedAttachments = await pickChatAttachments();
      if (selectedAttachments.length === 0) {
        return;
      }

      addPendingAttachments(selectedAttachments);
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

  const openProjectFromPath = async (path: string) => {
    try {
      setProjectError(null);
      const result = await openProject(path);
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

    await openProjectFromPath(path);
  };

  const handleOpenRecentProject = async (path: string) => {
    await openProjectFromPath(path);
  };

  const applyBackendEvent = (
    event: BackendEvent,
    submittedPayload?: SubmitMessagePayload,
  ) => {
    setGraphRunState((current) => {
      const result = reduceGraphRunControllerEvents(
        current,
        [event],
        (eventContent) => createMessage("assistant", eventContent),
        submittedPayload,
      );
      const selectedNodeId = current.selectedCanvasNode?.nodeId;
      const next = {
        ...result,
        selectedCanvasNode: selectedNodeId
          ? result.graph?.nodes.find((node) => node.nodeId === selectedNodeId) ??
            null
          : null,
        dirty: current.dirty || result.dirty,
      };

      graphRef.current = next.graph;
      pendingResearchChoiceRef.current = next.pendingResearchChoice ?? null;
      pendingGraphOverwriteChoiceRef.current =
        next.pendingGraphOverwriteChoice ?? null;
      activeRunIdRef.current = next.activeRunId ?? null;
      runHistoryRef.current = next.runHistory;
      artifactsRef.current = next.artifacts;
      messagesRef.current = next.messages;
      return next;
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
      const modelSessionId = await createAgentSession();
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
          modelSessionId,
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
        view = await reloadPreferences();
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

  const submitTemporaryScriptPermissionDecision = async (
    nodeId: string,
    decision: TemporaryScriptPermissionDecision,
  ) => {
    if (!activeProject) {
      return;
    }

    const currentGraph = graphRef.current;
    const node = currentGraph?.nodes.find(
      (candidate) => candidate.nodeId === nodeId,
    );
    if (!node) {
      return;
    }

    try {
      setProjectError(null);
      const events = await submitTemporaryScriptPermission(
        buildTemporaryScriptPermissionSubmitPayload({
          taskId: activeProject.projectId,
          node,
          decision,
          ...(currentGraph ? { currentGraph } : {}),
        }),
      );
      for (const event of events) {
        applyBackendEvent(event);
      }
    } catch (error) {
      setMessages((current) => [
        ...current,
        createMessage("assistant", `后台 Agent 暂不可用：${String(error)}`),
      ]);
      setDirty(true);
    }
  };

  const handleApproveTemporaryScript = async (nodeId: string) => {
    await submitTemporaryScriptPermissionDecision(nodeId, "approve");
  };

  const handleRejectTemporaryScript = async (nodeId: string) => {
    await submitTemporaryScriptPermissionDecision(nodeId, "reject");
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

  const handleNodeSelect = (node: AgentNode | null) => {
    setSelectedCanvasNode(node);
  };

  const submitAgentMessagePayload = async (payload: SubmitMessagePayload) => {
    await submitUserMessageWithStreamFallback({
      payload,
      createSession: createAgentSession,
      submitStream: submitUserMessageStream,
      submitFallback: submitUserMessage,
      onEvent: (event) => applyBackendEvent(event, payload),
    });
  };

  const handleSend = async () => {
    if (!activeProject) {
      return;
    }

    const content = draft.trim();
    if (!content && pendingAttachments.length === 0) {
      return;
    }

    const capturedGraphOverwriteChoice = pendingGraphOverwriteChoiceRef.current;
    const sentAttachments = [...pendingAttachments];
    const agentAttachments = selectAgentAttachments({
      content,
      sentAttachments,
      contextAttachments,
    });
    const userMessage = createMessage(
      "user",
      content || "已添加文档。",
      sentAttachments,
    );

    setMessages((current) => [...current, userMessage]);
    messagesRef.current = [...messagesRef.current, userMessage];
    setDraft("");
    setPendingAttachments([]);
    setPendingResearchChoice(null);
    pendingResearchChoiceRef.current = null;
    setPendingGraphOverwriteChoice(null);
    pendingGraphOverwriteChoiceRef.current = null;
    setDirty(true);

    try {
      const currentGraph = graphRef.current;
      const payload: SubmitMessagePayload = {
        taskId: activeProject.projectId,
        content: userMessage.content,
        attachments: agentAttachments,
        ...(currentGraph
          ? {
              currentGraph,
              hasRunHistory: runHistoryRef.current.length > 0,
              artifactRefs: artifactsRef.current.map(
                (artifact) => artifact.artifactId,
              ),
              ...(capturedGraphOverwriteChoice
                ? {
                    pendingChoice: toGraphOverwriteSubmitChoice(
                      capturedGraphOverwriteChoice,
                      userMessage.content,
                    ),
                  }
                : {}),
            }
          : {}),
      };

      await submitAgentMessagePayload(payload);

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

  const handleResearchChoice = async (choiceId: ResearchChoiceId) => {
    if (!activeProject || !pendingResearchChoiceRef.current) {
      return;
    }

    const payload = buildResearchChoiceSubmitPayload({
      pendingChoice: pendingResearchChoiceRef.current,
      choiceId,
    });

    if (!payload) {
      return;
    }

    setPendingResearchChoice(null);
    pendingResearchChoiceRef.current = null;
    setDirty(true);

    try {
      const events = await submitResearchChoice(payload);
      for (const event of events) {
        applyBackendEvent(event);
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
    try {
      const view = await reloadPreferences();
      setRecentProjects(view.preferences.recentProjects);
    } catch (error) {
      void error;
    }
  };

  const applyPreferencesView = (view: PreferencesView) => {
    const shouldRefreshAsr = shouldRefreshAsrForPreferencesUpdate(
      preferencesView,
      view,
    );
    setPreferences(view);
    setRecentProjects(view.preferences.recentProjects);
    if (shouldRefreshAsr) {
      void refreshVoiceInputAvailability();
    }
  };

  const handleAddModel = async () => {
    const path = await pickModelFile();
    if (!path) {
      return;
    }
    try {
      setPreferences(await addModelFile(path));
    } catch (error) {
      setPreferencesError(String(error));
    }
  };

  const handleAddSpeechToTextModel = async () => {
    const path = await pickSpeechToTextModelDirectory();
    if (!path) {
      return;
    }
    try {
      setPreferencesError(null);
      applyPreferencesView(await addSpeechToTextModelDirectory(path));
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
      setPreferences(await importModelFile(path));
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
      setPreferences(await scanModelDirectory(path));
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
      setPreferences(await setModelStorageDirectory(path));
    } catch (error) {
      setPreferencesError(String(error));
    }
  };

  const handleSetDefaultModel = async (modelId: string) => {
    try {
      setPreferencesError(null);
      setPreferences(await setDefaultModel(modelId));
    } catch (error) {
      setPreferencesError(String(error));
    }
  };

  const handleSetModelAssignment = async (
    role: ModelAssignmentRole,
    modelId: string,
  ) => {
    try {
      setPreferencesError(null);
      applyPreferencesView(await setModelAssignment(role, modelId));
    } catch (error) {
      setPreferencesError(String(error));
    }
  };

  const handleSetAgentModelMode = async (
    mode: "local" | "api",
  ): Promise<void> => {
    try {
      setPreferencesError(null);
      applyPreferencesView(await setAgentModelMode(mode));
    } catch (error) {
      setPreferencesError(String(error));
    }
  };

  const handleSaveApiProvider = async (payload: SaveApiProviderPayload) => {
    try {
      setPreferencesError(null);
      const view = await saveApiProviderConfig(payload);
      applyPreferencesView(view);
      return view;
    } catch (error) {
      setPreferencesError(String(error));
      throw error;
    }
  };

  const handleTestApiProviderConnection = async (
    payload: SaveApiProviderPayload,
  ): Promise<ApiProviderConnectionResult> => {
    try {
      return await testApiProviderConnection(payload);
    } catch (error) {
      return { ok: false, message: String(error), models: [] };
    }
  };

  const handleFetchApiProviderModels = async (
    payload: SaveApiProviderPayload,
  ): Promise<ApiProviderConnectionResult> => {
    try {
      return await fetchApiProviderModels(payload);
    } catch (error) {
      return { ok: false, message: String(error), models: [] };
    }
  };

  const handleDeleteApiProvider = async (providerId: string) => {
    try {
      setPreferencesError(null);
      applyPreferencesView(await deleteApiProviderConfig(providerId));
    } catch (error) {
      setPreferencesError(String(error));
    }
  };

  const handleSetActiveApiProvider = async (providerId: string) => {
    try {
      setPreferencesError(null);
      applyPreferencesView(await setActiveApiProvider(providerId));
    } catch (error) {
      setPreferencesError(String(error));
    }
  };

  const handleSaveMcpToolProvider = async (
    payload: SaveMcpToolProviderPayload,
  ) => {
    try {
      setPreferencesError(null);
      const view = await saveMcpToolProviderConfig(payload);
      applyPreferencesView(view);
      return view;
    } catch (error) {
      setPreferencesError(String(error));
      throw error;
    }
  };

  const handleDeleteMcpToolProvider = async (providerId: string) => {
    try {
      setPreferencesError(null);
      applyPreferencesView(await deleteMcpToolProviderConfig(providerId));
    } catch (error) {
      setPreferencesError(String(error));
    }
  };

  const handleRefreshMcpToolProvider = async (providerId: string) => {
    try {
      setPreferencesError(null);
      await refreshMcpToolProviderTools(providerId);
    } catch (error) {
      setPreferencesError(String(error));
    }
  };

  const handleSetToolEnabled = async (toolId: string, enabled: boolean) => {
    try {
      setPreferences(await setToolEnabled(toolId, enabled));
    } catch (error) {
      setPreferencesError(String(error));
    }
  };

  const preferencesDialog = (
    <PreferencesDialog
      error={preferencesError}
      loading={preferencesLoading}
      onAddModel={handleAddModel}
      onAddSpeechToTextModel={handleAddSpeechToTextModel}
      onClose={() => setPreferencesOpen(false)}
      onDeleteApiProvider={handleDeleteApiProvider}
      onDeleteMcpToolProvider={handleDeleteMcpToolProvider}
      onFetchApiProviderModels={handleFetchApiProviderModels}
      onImportModel={handleImportModel}
      onRefreshMcpToolProvider={handleRefreshMcpToolProvider}
      onScanModelDirectory={handleScanModelDirectory}
      onSaveApiProvider={handleSaveApiProvider}
      onSaveMcpToolProvider={handleSaveMcpToolProvider}
      onSetActiveApiProvider={handleSetActiveApiProvider}
      onSetAgentModelMode={handleSetAgentModelMode}
      onSetDefaultModel={handleSetDefaultModel}
      onSetModelAssignment={handleSetModelAssignment}
      onSetModelStorageDirectory={handleSetModelStorageDirectory}
      onSetToolEnabled={handleSetToolEnabled}
      onTestApiProviderConnection={handleTestApiProviderConnection}
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
          onOpenRecentProject={handleOpenRecentProject}
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
          pendingResearchChoice={pendingResearchChoice}
          draft={draft}
          onDraftChange={setDraft}
          onSend={handleSend}
          onAddFile={handleAddFile}
          onResearchChoice={handleResearchChoice}
          voiceInput={voiceInput}
          onVoiceToggle={handleVoiceToggle}
          onDraftSelectionChange={handleDraftSelectionChange}
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
          onNodeSelect={handleNodeSelect}
          onOpenArtifact={handleOpenArtifact}
          onRevealArtifact={handleRevealArtifact}
          onApproveTemporaryScript={handleApproveTemporaryScript}
          onRejectTemporaryScript={handleRejectTemporaryScript}
        />
      </section>
      <section className="previewColumn" aria-label="文件预览区域">
        <ArtifactPreviewPanel
          selectedNode={selectedCanvasNode}
          artifact={selectedPreviewArtifact}
          previewKind={selectedPreviewKind}
          fileUrl={selectedPreviewFileUrl}
          preview={artifactPreview}
          loading={artifactPreviewLoading}
          error={artifactPreviewError}
          onOpenArtifact={handleOpenArtifact}
          onRevealArtifact={handleRevealArtifact}
        />
      </section>
      {preferencesDialog}
    </main>
  );
}

function lastRunHistoryEntry(
  runHistory: RunHistoryEntry[],
): RunHistoryEntry | undefined {
  return runHistory.length > 0 ? runHistory[runHistory.length - 1] : undefined;
}

function formatUnknownError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return String(error);
}

export function shouldRefreshAsrForPreferencesUpdate(
  previousView: PreferencesView | null,
  nextView: PreferencesView,
): boolean {
  return (
    speechToTextAssignmentId(previousView) !== speechToTextAssignmentId(nextView)
  );
}

export function buildResearchChoiceSubmitPayload({
  pendingChoice,
  choiceId,
}: {
  pendingChoice: PendingResearchChoice;
  choiceId: ResearchChoiceId;
}): (SubmitMessagePayload & { inquiryChoice: ResearchChoiceId }) | null {
  if (!pendingChoice.submittedPayload) {
    return null;
  }

  return {
    ...pendingChoice.submittedPayload,
    inquiryChoice: choiceId,
  };
}

export function buildTemporaryScriptPermissionSubmitPayload({
  taskId,
  node,
  decision,
  currentGraph,
}: {
  taskId: string;
  node: AgentNode;
  decision: TemporaryScriptPermissionDecision;
  currentGraph?: NodeGraph;
}): TemporaryScriptPermissionPayload {
  const approvalFingerprint = node.scriptReview?.approvalFingerprint;
  if (decision === "approve" && !approvalFingerprint) {
    throw new Error("temporary script approval fingerprint is missing");
  }

  return createTemporaryScriptPermissionPayload({
    taskId,
    nodeId: node.nodeId,
    decision,
    ...(decision === "approve"
      ? { approvalFingerprint }
      : {}),
    ...(currentGraph ? { currentGraph } : {}),
  });
}

function speechToTextAssignmentId(view: PreferencesView | null): string | null {
  return view?.preferences.modelAssignments.speechToTextModelId ?? null;
}
