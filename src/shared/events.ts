import type {
  AgentNode,
  ChatMessage,
  NodeGraph,
  NodeRunRecord,
  RuntimeNotice,
  ScriptReviewState,
} from "./types";

export type BackendEvent =
  | {
      type: "run.started";
      payload: {
        runId: string;
        taskId: string;
        startedAt: string;
      };
    }
  | {
      type: "run.cancelled";
      payload: {
        runId: string;
        taskId: string;
        completedAt: string;
      };
    }
  | {
      type: "message.started";
      payload: {
        message: ChatMessage;
      };
    }
  | {
      type: "message.delta";
      payload: {
        messageId: string;
        delta: string;
      };
    }
  | {
      type: "message.completed";
      payload: {
        messageId: string;
      };
    }
  | {
      type: "message.created";
      payload: {
        message: ChatMessage;
      };
    }
  | {
      type: "input.required";
      payload: {
        prompt: string;
        missing: string[];
      };
    }
  | {
      type: "node_graph.created";
      payload: {
        graph: NodeGraph;
      };
    }
  | {
      type: "node.created";
      payload: {
        node: AgentNode;
      };
    }
  | {
      type: "node.updated";
      payload: {
        node: AgentNode;
      };
    }
  | {
      type: "node.running";
      payload: {
        nodeId: string;
      };
    }
  | {
      type: "node.completed";
      payload: {
        nodeId: string;
        artifactRefs: string[];
      };
    }
  | {
      type: "node.failed";
      payload: {
        nodeId: string;
        taskId?: string;
        runId?: string;
        error: string;
        errorCode?: string;
      };
    }
  | {
      type: "node.skipped";
      payload: {
        nodeId: string;
        reason: string;
      };
    }
  | {
      type: "node.run_recorded";
      payload: {
        record: NodeRunRecord;
      };
    }
  | {
      type: "permission.required";
      payload: {
        nodeId: string;
        permissions: string[];
      };
    }
  | {
      type: "research.completed";
      payload: {
        taskId: string;
        reportArtifactId?: string;
        summary?: string;
        acceptedSources?: Array<{
          title: string;
          url: string;
          snippet?: string;
        }>;
        rejectedSources?: Array<{
          title: string;
          url: string;
          reason?: string;
        }>;
      };
    }
  | {
      type: "research.choice_required";
      payload: {
        taskId: string;
        prompt: string;
        choices: Array<{
          id: string;
          label: string;
          description?: string;
        }>;
      };
    }
  | {
      type: "node.needs_permission";
      payload: {
        nodeId: string;
        permissions: string[];
        scriptReview?: ScriptReviewState;
      };
    }
  | {
      type: "node.runtime_notice";
      payload: {
        nodeId: string;
        notice: RuntimeNotice;
      };
    }
  | {
      type: "graph.replanned";
      payload: {
        graph: NodeGraph;
        previousGraphId?: string;
        summary?: string;
      };
    }
  | {
      type: "artifact.created";
      payload: {
        artifactId: string;
        path: string;
        sourceNodeId?: string;
        createdAt?: string;
      };
    }
  | {
      type: "task.completed";
      payload: {
        taskId: string;
        runId?: string;
      };
    }
  | {
      type: "task.failed";
      payload: {
        taskId: string;
        error: string;
        runId?: string;
        errorCode?: string;
      };
    };
