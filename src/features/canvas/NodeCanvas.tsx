import "@xyflow/react/dist/style.css";

import { useMemo, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeMouseHandler,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";

import { NodePopover } from "./NodePopover";
import type { AgentNode, NodeGraph } from "../../shared/types";

type AgentNodeData = {
  agentNode: AgentNode;
};

type AgentFlowNode = Node<AgentNodeData, "agent">;

type NodeCanvasProps = {
  graph: NodeGraph | null;
  running?: boolean;
  cancelling?: boolean;
  canRetryFailed?: boolean;
  onRun?: () => void;
  onStop?: () => void;
  onRetryFailed?: () => void;
  onRunFromNode?: (nodeId: string) => void;
  onNodeSelect?: (node: AgentNode | null) => void;
  onOpenArtifact?: (path: string) => void;
  onRevealArtifact?: (path: string) => void;
};

const nodeTypes: NodeTypes = {
  agent: AgentNodeView,
};

const nodeTypeLabels: Record<AgentNode["nodeType"], string> = {
  fixed_tool: "工具",
  model: "模型",
  output: "输出",
  temporary_placeholder: "占位",
};

const statusLabels: Record<AgentNode["status"], string> = {
  waiting: "等待",
  ready: "就绪",
  running: "运行",
  completed: "完成",
  failed: "失败",
  needs_user_input: "待输入",
  needs_permission: "待授权",
  skipped: "跳过",
};

function AgentNodeView({ data, selected }: NodeProps<AgentFlowNode>) {
  const node = data.agentNode;

  return (
    <div
      className={`agentNode agentNode-${node.nodeType}${selected ? " agentNode-selected" : ""}`}
    >
      <Handle
        className="agentNodeHandle agentNodeHandleInput"
        id="input"
        position={Position.Top}
        type="target"
      />
      <div className="agentNodeTopLine">
        <span className="agentNodeType">{nodeTypeLabels[node.nodeType]}</span>
        <span className={`agentNodeStatus agentNodeStatus-${node.status}`}>
          {statusLabels[node.status]}
        </span>
      </div>
      <h3>{node.displayName}</h3>
      <p>{node.summary}</p>
      <Handle
        className="agentNodeHandle agentNodeHandleOutput"
        id="output"
        position={Position.Bottom}
        type="source"
      />
    </div>
  );
}

export function NodeCanvas({
  graph,
  running = false,
  cancelling = false,
  canRetryFailed = false,
  onRun,
  onStop,
  onRetryFailed,
  onRunFromNode,
  onNodeSelect,
  onOpenArtifact,
  onRevealArtifact,
}: NodeCanvasProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const nodes = useMemo<AgentFlowNode[]>(() => {
    if (!graph) {
      return [];
    }

    return graph.nodes.map((node) => ({
      id: node.nodeId,
      type: "agent",
      data: { agentNode: node },
      position: node.position,
      targetPosition: Position.Top,
      sourcePosition: Position.Bottom,
      draggable: false,
    }));
  }, [graph]);

  const edges = useMemo<Edge[]>(() => {
    if (!graph) {
      return [];
    }

    return graph.edges.map((edge) => ({
      ...edge,
      sourceHandle: "output",
      targetHandle: "input",
      type: "smoothstep",
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: "#64748b",
      },
      style: {
        stroke: "#64748b",
        strokeWidth: 1.5,
      },
    }));
  }, [graph]);

  const selectedNode =
    graph?.nodes.find((node) => node.nodeId === selectedNodeId) ?? null;

  const handleNodeClick: NodeMouseHandler<AgentFlowNode> = (_event, node) => {
    setSelectedNodeId(node.id);
    onNodeSelect?.(node.data.agentNode);
  };

  const clearSelectedNode = () => {
    setSelectedNodeId(null);
    onNodeSelect?.(null);
  };

  if (!graph) {
    return (
      <div className="canvasEmptyState">
        <p className="canvasEyebrow">节点画布</p>
        <h2>等待 Agent 生成工具流程</h2>
        <p>发送带文档附件的任务后，这里会显示从输入到导出的节点流程。</p>
      </div>
    );
  }

  return (
    <div className="nodeCanvas">
      <div className="nodeCanvasToolbar">
        <button
          className="nodeCanvasRunButton"
          disabled={running}
          onClick={onRun}
          type="button"
        >
          {running ? "运行中" : "运行流程"}
        </button>
        {running ? (
          <button
            className="nodeCanvasSecondaryButton"
            disabled={cancelling}
            onClick={onStop}
            type="button"
          >
            停止运行
          </button>
        ) : null}
        {canRetryFailed ? (
          <button
            className="nodeCanvasSecondaryButton"
            disabled={running}
            onClick={onRetryFailed}
            type="button"
          >
            重试失败节点
          </button>
        ) : null}
      </div>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        onPaneClick={clearSelectedNode}
        fitView
        fitViewOptions={{ padding: 0.18 }}
        minZoom={0.55}
        maxZoom={1.3}
        nodesDraggable={false}
        nodesConnectable={false}
        edgesFocusable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background
          color="#d7dee7"
          gap={24}
          size={1}
          variant={BackgroundVariant.Dots}
        />
      </ReactFlow>
      {selectedNode ? (
        <NodePopover
          node={selectedNode}
          onClose={clearSelectedNode}
          onRunFromNode={onRunFromNode}
          onOpenArtifact={onOpenArtifact}
          onRevealArtifact={onRevealArtifact}
        />
      ) : null}
    </div>
  );
}
