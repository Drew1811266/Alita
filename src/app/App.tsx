import "./app.css";

import { useEffect, useMemo, useRef, useState } from "react";

import { NodeCanvas } from "../features/canvas/NodeCanvas";
import { ArtifactPreviewPanel } from "../features/artifacts/ArtifactPreviewPanel";
import {
  artifactFileUrl,
  openArtifact,
  readArtifactText,
  revealArtifact,
  type ArtifactTextPreview,
} from "../features/artifacts/artifactApi";
import { resolvePreviewArtifactForNode } from "../features/artifacts/artifactPreview";
import {
  detectArtifactPreviewKind,
  shouldReadArtifactText,
} from "../features/artifacts/artifactPreviewKind";
import { pickChatAttachments } from "../features/chat/attachmentApi";
import { ChatPanel } from "../features/chat/ChatPanel";
import {
  getAsrStatus,
  transcribeVoiceAudio,
} from "../features/voice/asrApi";
import {
  buildLevelBuckets,
  encodeWav,
  MAX_RECORDING_SECONDS,
} from "../features/voice/audioCapture";
import {
  insertTranscriptIntoDraft,
  type DraftSelection,
} from "../features/voice/draftInsertion";
import {
  createInitialVoiceInput,
  voiceFailed,
  voiceRecording,
  voiceTranscribing,
} from "../features/voice/voiceSession";
import {
  canStartVoiceRecording,
  canStopVoiceRecording,
} from "../features/voice/voiceRecordingGuards";
import {
  addModelFile,
  addSpeechToTextModelDirectory,
  getPreferences,
  importModelFile,
  pickModelDirectory,
  pickModelFile,
  pickSpeechToTextModelDirectory,
  scanModelDirectory,
  setDefaultModel,
  setModelAssignment,
  setModelStorageDirectory,
  setToolEnabled,
  type ModelAssignmentRole,
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
import { scriptReviewFingerprint } from "../features/task/scriptReviewFingerprint";
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
import { WorkbenchTopBar } from "../features/workbench/WorkbenchTopBar";
import {
  reduceBackendEvents,
  toGraphOverwriteSubmitChoice,
  type PendingGraphOverwriteChoice,
  type PendingResearchChoice,
} from "./backendEvents";
import type {
  AlitaProject,
  AgentNode,
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
import type { ResearchChoiceId } from "../shared/events";

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
  const messagesRef = useRef<ChatMessage[]>(initialMessages);
  const [draft, setDraft] = useState("");
  const [voiceInput, setVoiceInput] = useState(() =>
    createInitialVoiceInput(null),
  );
  const lastDraftSelectionRef = useRef<DraftSelection | null>(null);
  const recordingStreamRef = useRef<MediaStream | null>(null);
  const recordingStartingRef = useRef(false);
  const recordingStoppingRef = useRef(false);
  const recordingChunksRef = useRef<Float32Array[]>([]);
  const recordingSampleRateRef = useRef(16_000);
  const recordingStartedAtRef = useRef(0);
  const recordingTimerRef = useRef<number | null>(null);
  const recordingAudioContextRef = useRef<AudioContext | null>(null);
  const recordingProcessorRef = useRef<ScriptProcessorNode | null>(null);
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
  const [pendingResearchChoice, setPendingResearchChoice] =
    useState<PendingResearchChoice | null>(null);
  const pendingResearchChoiceRef = useRef<PendingResearchChoice | null>(null);
  const [pendingGraphOverwriteChoice, setPendingGraphOverwriteChoice] =
    useState<PendingGraphOverwriteChoice | null>(null);
  const pendingGraphOverwriteChoiceRef =
    useRef<PendingGraphOverwriteChoice | null>(null);
  const [selectedCanvasNodeId, setSelectedCanvasNodeId] = useState<
    string | null
  >(null);
  const [artifactPreview, setArtifactPreview] =
    useState<ArtifactTextPreview | null>(null);
  const [artifactPreviewLoading, setArtifactPreviewLoading] = useState(false);
  const [artifactPreviewError, setArtifactPreviewError] = useState<
    string | null
  >(null);
  const [preferencesView, setPreferencesView] =
    useState<PreferencesView | null>(null);
  const [preferencesLoading, setPreferencesLoading] = useState(false);
  const [preferencesError, setPreferencesError] = useState<string | null>(null);
  const [recentProjects, setRecentProjects] = useState<string[]>([]);

  const stopRecordingStream = () => {
    if (recordingTimerRef.current !== null) {
      window.clearInterval(recordingTimerRef.current);
      recordingTimerRef.current = null;
    }

    recordingProcessorRef.current?.disconnect();
    recordingProcessorRef.current = null;

    const audioContext = recordingAudioContextRef.current;
    recordingAudioContextRef.current = null;
    void audioContext?.close();

    recordingStreamRef.current?.getTracks().forEach((track) => track.stop());
    recordingStreamRef.current = null;
  };

  useEffect(() => {
    getPreferences()
      .then((view) => setRecentProjects(view.preferences.recentProjects))
      .catch(() => setRecentProjects([]));
  }, []);

  useEffect(() => {
    let cancelled = false;

    getAsrStatus().then((status) => {
      if (!cancelled) {
        setVoiceInput(createInitialVoiceInput(status));
      }
    });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return () => {
      stopRecordingStream();
    };
  }, []);

  useEffect(() => {
    graphRef.current = graph;
  }, [graph]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    pendingResearchChoiceRef.current = pendingResearchChoice;
  }, [pendingResearchChoice]);

  useEffect(() => {
    pendingGraphOverwriteChoiceRef.current = pendingGraphOverwriteChoice;
  }, [pendingGraphOverwriteChoice]);

  useEffect(() => {
    activeRunIdRef.current = activeRunId;
  }, [activeRunId]);

  useEffect(() => {
    runHistoryRef.current = runHistory;
  }, [runHistory]);

  useEffect(() => {
    artifactsRef.current = artifacts;
  }, [artifacts]);

  const selectedCanvasNode = useMemo<AgentNode | null>(
    () =>
      graph?.nodes.find((node) => node.nodeId === selectedCanvasNodeId) ?? null,
    [graph, selectedCanvasNodeId],
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
      setArtifactPreview(null);
      setArtifactPreviewError(null);
      setArtifactPreviewLoading(false);
      return () => {
        cancelled = true;
      };
    }

    setArtifactPreview(null);
    setArtifactPreviewError(null);
    setArtifactPreviewLoading(true);
    readArtifactText(selectedPreviewPath)
      .then((preview) => {
        if (!cancelled) {
          setArtifactPreview(preview);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setArtifactPreviewError(String(error));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setArtifactPreviewLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [selectedPreviewKind, selectedPreviewPath]);

  const applyProjectOpenResult = (result: ProjectOpenResult) => {
    const projectMessages =
      result.project.messages.length > 0 ? result.project.messages : initialMessages;
    setActiveProject({ ...result.project, messages: projectMessages });
    setMessages(projectMessages);
    messagesRef.current = projectMessages;
    setGraph(result.project.graph);
    setRunHistory(result.project.runHistory);
    runHistoryRef.current = result.project.runHistory;
    setArtifacts([]);
    artifactsRef.current = [];
    setSelectedCanvasNodeId(null);
    setActiveRunId(null);
    activeRunIdRef.current = null;
    setPendingResearchChoice(null);
    pendingResearchChoiceRef.current = null;
    setPendingGraphOverwriteChoice(null);
    pendingGraphOverwriteChoiceRef.current = null;
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
    setMessages((current) => {
      const result = reduceBackendEvents(
        {
          messages: current,
          graph: graphRef.current,
          dirty: false,
          pendingResearchChoice: pendingResearchChoiceRef.current,
          pendingGraphOverwriteChoice: pendingGraphOverwriteChoiceRef.current,
          activeRunId: activeRunIdRef.current,
          runHistory: runHistoryRef.current,
          artifacts: artifactsRef.current,
        },
        [event],
        (eventContent) => createMessage("assistant", eventContent),
        submittedPayload,
      );

      graphRef.current = result.graph;
      setGraph(result.graph);
      pendingResearchChoiceRef.current = result.pendingResearchChoice ?? null;
      pendingGraphOverwriteChoiceRef.current =
        result.pendingGraphOverwriteChoice ?? null;
      activeRunIdRef.current = result.activeRunId ?? null;
      runHistoryRef.current = result.runHistory ?? runHistoryRef.current;
      artifactsRef.current = result.artifacts ?? artifactsRef.current;
      setActiveRunId(activeRunIdRef.current);
      setPendingResearchChoice(pendingResearchChoiceRef.current);
      setPendingGraphOverwriteChoice(pendingGraphOverwriteChoiceRef.current);
      setRunHistory(runHistoryRef.current);
      setArtifacts(artifactsRef.current);
      if (result.dirty) {
        setDirty(true);
      }

      messagesRef.current = result.messages;
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
    setSelectedCanvasNodeId(node?.nodeId ?? null);
  };

  const handleDraftSelectionChange = (selection: DraftSelection | null) => {
    lastDraftSelectionRef.current = selection;
  };

  const startVoiceRecording = async () => {
    if (
      !canStartVoiceRecording({
        starting: recordingStartingRef.current,
        stopping: recordingStoppingRef.current,
        hasActiveStream: recordingStreamRef.current !== null,
      })
    ) {
      return;
    }

    recordingStartingRef.current = true;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recordingStreamRef.current = stream;

      const audioContext = new AudioContext();
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      const monitorGain = audioContext.createGain();

      monitorGain.gain.value = 0;
      analyser.fftSize = 64;
      recordingChunksRef.current = [];
      recordingSampleRateRef.current = audioContext.sampleRate;
      recordingStartedAtRef.current = Date.now();
      recordingAudioContextRef.current = audioContext;
      recordingProcessorRef.current = processor;

      processor.onaudioprocess = (event) => {
        const input = event.inputBuffer.getChannelData(0);
        recordingChunksRef.current.push(new Float32Array(input));
      };

      source.connect(analyser);
      source.connect(processor);
      processor.connect(monitorGain);
      monitorGain.connect(audioContext.destination);

      setVoiceInput((current) => voiceRecording(current));

      const levelData = new Uint8Array(analyser.frequencyBinCount);
      recordingTimerRef.current = window.setInterval(() => {
        analyser.getByteTimeDomainData(levelData);
        const elapsedSeconds = Math.min(
          MAX_RECORDING_SECONDS,
          Math.floor((Date.now() - recordingStartedAtRef.current) / 1000),
        );

        setVoiceInput((current) =>
          voiceRecording(
            current,
            buildLevelBuckets(levelData, 32),
            elapsedSeconds,
          ),
        );

        if (elapsedSeconds >= MAX_RECORDING_SECONDS) {
          void stopVoiceRecording(lastDraftSelectionRef.current);
        }
      }, 250);
    } catch (error) {
      stopRecordingStream();
      setVoiceInput((current) =>
        voiceFailed(current, `麦克风不可用：${formatUnknownError(error)}`),
      );
    } finally {
      recordingStartingRef.current = false;
    }
  };

  const stopVoiceRecording = async (selection?: DraftSelection | null) => {
    if (recordingStoppingRef.current) {
      return;
    }

    if (recordingStreamRef.current === null) {
      return;
    }

    recordingStoppingRef.current = true;

    const capturedSelection = selection ?? lastDraftSelectionRef.current;
    const chunks = [...recordingChunksRef.current];
    const sampleRate = recordingSampleRateRef.current;

    if (
      !canStopVoiceRecording({
        stopping: false,
        hasActiveStream: recordingStreamRef.current !== null,
        chunkCount: chunks.length,
      })
    ) {
      stopRecordingStream();
      recordingChunksRef.current = [];
      setVoiceInput((current) => ({
        ...current,
        available: true,
        status: "idle",
        message: "语音模型已就绪",
        elapsedSeconds: 0,
        levels: [],
      }));
      recordingStoppingRef.current = false;
      return;
    }

    stopRecordingStream();
    recordingChunksRef.current = [];
    setVoiceInput((current) => voiceTranscribing(current));

    try {
      const samples = concatenateFloat32Arrays(chunks);
      const transcript = await transcribeVoiceAudio(encodeWav(samples, sampleRate));

      setDraft((currentDraft) =>
        insertTranscriptIntoDraft({
          currentDraft,
          transcript: transcript.text,
          selection: capturedSelection,
        }),
      );
      setVoiceInput((current) => ({
        ...current,
        available: true,
        status: "idle",
        message: "语音模型已就绪",
        elapsedSeconds: 0,
        levels: [],
      }));
    } catch (error) {
      setVoiceInput((current) =>
        voiceFailed(current, `语音转写失败：${formatUnknownError(error)}`),
      );
    } finally {
      recordingChunksRef.current = [];
      recordingStoppingRef.current = false;
    }
  };

  const handleVoiceToggle = async (selection: DraftSelection | null) => {
    if (!voiceInput.available || voiceInput.status === "transcribing") {
      return;
    }

    if (voiceInput.status === "recording") {
      await stopVoiceRecording(selection);
      return;
    }

    await startVoiceRecording();
  };

  const submitAgentMessagePayload = async (payload: SubmitMessagePayload) => {
    let receivedStreamEvent = false;
    try {
      await submitUserMessageStream(payload, (event) => {
        receivedStreamEvent = true;
        applyBackendEvent(event, payload);
      });
    } catch (streamError) {
      if (receivedStreamEvent) {
        throw streamError;
      }

      const events = await submitUserMessage(payload);
      for (const event of events) {
        applyBackendEvent(event, payload);
      }
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

    const capturedGraphOverwriteChoice = pendingGraphOverwriteChoiceRef.current;
    const sentAttachments = [...pendingAttachments];
    const agentAttachments =
      sentAttachments.length > 0 ? sentAttachments : contextAttachments;
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

  const refreshVoiceInputAvailability = async () => {
    setVoiceInput(createInitialVoiceInput(null));
    const status = await getAsrStatus();
    setVoiceInput(createInitialVoiceInput(status));
  };

  const applyPreferencesView = (view: PreferencesView) => {
    const shouldRefreshAsr = shouldRefreshAsrForPreferencesUpdate(
      preferencesView,
      view,
    );
    setPreferencesView(view);
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
      setPreferencesView(await addModelFile(path));
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
      onAddSpeechToTextModel={handleAddSpeechToTextModel}
      onClose={() => setPreferencesOpen(false)}
      onImportModel={handleImportModel}
      onScanModelDirectory={handleScanModelDirectory}
      onSetDefaultModel={handleSetDefaultModel}
      onSetModelAssignment={handleSetModelAssignment}
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

function concatenateFloat32Arrays(chunks: Float32Array[]): Float32Array {
  const totalLength = chunks.reduce((total, chunk) => total + chunk.length, 0);
  const samples = new Float32Array(totalLength);
  let offset = 0;

  for (const chunk of chunks) {
    samples.set(chunk, offset);
    offset += chunk.length;
  }

  return samples;
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
  return createTemporaryScriptPermissionPayload({
    taskId,
    nodeId: node.nodeId,
    decision,
    ...(decision === "approve" && node.scriptReview
      ? { approvalFingerprint: scriptReviewFingerprint(node.scriptReview) }
      : {}),
    ...(currentGraph ? { currentGraph } : {}),
  });
}

function speechToTextAssignmentId(view: PreferencesView | null): string | null {
  return view?.preferences.modelAssignments.speechToTextModelId ?? null;
}
