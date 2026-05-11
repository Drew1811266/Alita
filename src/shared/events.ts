import type { AgentNode, ChatMessage, NodeGraph, NodeRunRecord } from "./types";

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
