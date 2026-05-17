import type { AgentNode, NodeStatus, NodeType } from "../../shared/types";

type NodePopoverProps = {
  node: AgentNode;
  onClose(): void;
  onRunFromNode?: (nodeId: string) => void;
  onOpenArtifact?: (path: string) => void;
  onRevealArtifact?: (path: string) => void;
};

const nodeTypeLabels: Record<NodeType, string> = {
  fixed_tool: "固定工具",
  model: "模型调用",
  output: "输出节点",
  temporary_placeholder: "临时占位",
};

const statusLabels: Record<NodeStatus, string> = {
  waiting: "等待中",
  ready: "准备中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  needs_user_input: "等待用户输入",
  needs_permission: "等待授权",
  skipped: "已跳过",
};

const toolCapabilityLabels: Record<string, string> = {
  "document.receive_attachment": "接收附件文档",
  "document.extract_text": "提取文档正文和结构",
  "document.typst_compile": "Typst PDF 排版导出",
};

const modelCapabilityLabels: Record<string, string> = {
  "gpt-content-organizer": "整理内容提纲",
  "gpt-report-writer": "生成报告初稿",
};

function getCapability(node: AgentNode): string {
  if (node.toolRef) {
    return toolCapabilityLabels[node.toolRef] ?? "已注册工具能力";
  }

  if (node.modelRef) {
    return modelCapabilityLabels[node.modelRef] ?? "模型推理能力";
  }

  return "内部流程节点";
}

function renderPorts(ports: AgentNode["inputPorts"]) {
  if (ports.length === 0) {
    return <span className="nodePopoverEmpty">无</span>;
  }

  return (
    <ul className="nodePopoverPortList">
      {ports.map((port) => (
        <li key={port.id}>{port.label}</li>
      ))}
    </ul>
  );
}

function renderArtifacts(
  artifactRefs: AgentNode["artifactRefs"],
  onOpenArtifact?: (path: string) => void,
  onRevealArtifact?: (path: string) => void,
) {
  if (artifactRefs.length === 0) {
    return <span className="nodePopoverEmpty">暂无</span>;
  }

  return (
    <ul className="nodePopoverPortList">
      {artifactRefs.map((artifactRef) => (
        <li key={artifactRef}>
          <span>{artifactRef}</span>
          {onOpenArtifact || onRevealArtifact ? (
            <span className="nodePopoverArtifactActions">
              {onOpenArtifact ? (
                <button
                  className="nodePopoverInlineButton"
                  onClick={() => onOpenArtifact(artifactRef)}
                  type="button"
                >
                  打开
                </button>
              ) : null}
              {onRevealArtifact ? (
                <button
                  className="nodePopoverInlineButton"
                  onClick={() => onRevealArtifact(artifactRef)}
                  type="button"
                >
                  定位
                </button>
              ) : null}
            </span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function renderPermissions(permissions: string[]) {
  if (permissions.length === 0) {
    return <span className="nodePopoverEmpty">无</span>;
  }

  return (
    <ul className="nodePopoverPortList">
      {permissions.map((permission) => (
        <li key={permission}>{permission}</li>
      ))}
    </ul>
  );
}

export function NodePopover({
  node,
  onClose,
  onRunFromNode,
  onOpenArtifact,
  onRevealArtifact,
}: NodePopoverProps) {
  const canRunFromNode =
    onRunFromNode &&
    node.nodeType !== "temporary_placeholder" &&
    !node.scriptReview;

  return (
    <aside className="nodePopover" aria-label={`${node.displayName} 节点信息`}>
      <div className="nodePopoverHeader">
        <div className="nodePopoverTitleGroup">
          <p className="nodePopoverKicker">节点信息</p>
          <h2>{node.displayName}</h2>
          <p>
            {nodeTypeLabels[node.nodeType]} / {statusLabels[node.status]}
          </p>
        </div>
        <button
          aria-label="关闭节点信息"
          className="nodePopoverClose"
          onClick={onClose}
          type="button"
        >
          关闭
        </button>
      </div>
      {canRunFromNode ? (
        <button
          className="nodePopoverAction"
          onClick={() => onRunFromNode(node.nodeId)}
          type="button"
        >
          从此节点重跑
        </button>
      ) : null}

      <dl className="nodePopoverDetails">
        <div>
          <dt>AI 调用目的</dt>
          <dd>{node.summary}</dd>
        </div>
        <div>
          <dt>将调用的功能</dt>
          <dd>{getCapability(node)}</dd>
        </div>
        <div>
          <dt>输入端口</dt>
          <dd>{renderPorts(node.inputPorts)}</dd>
        </div>
        <div>
          <dt>输出端口</dt>
          <dd>{renderPorts(node.outputPorts)}</dd>
        </div>
        <div>
          <dt>重试次数</dt>
          <dd>{node.retryCount} 次</dd>
        </div>
        <div>
          <dt>产物</dt>
          <dd>
            {renderArtifacts(
              node.artifactRefs,
              onOpenArtifact,
              onRevealArtifact,
            )}
          </dd>
        </div>
        {node.lastRun ? (
          <div>
            <dt>最近运行</dt>
            <dd>
              <div>{statusLabels[node.lastRun.status]}</div>
              <div>{node.lastRun.startedAt}</div>
              {node.lastRun.completedAt ? (
                <div>{node.lastRun.completedAt}</div>
              ) : null}
              {node.lastRun.error ? <div>{node.lastRun.error}</div> : null}
              {node.lastRun.errorCode ? (
                <div>
                  <span>错误码</span>
                  <span>{node.lastRun.errorCode}</span>
                </div>
              ) : null}
            </dd>
          </div>
        ) : null}
        {node.scriptReview ? (
          <div>
            <dt>安全审查</dt>
            <dd>
              <div>{node.scriptReview.summary}</div>
              {renderPermissions(node.scriptReview.permissions)}
              <div>临时脚本节点当前仅可审查，尚不能执行。</div>
            </dd>
          </div>
        ) : null}
      </dl>
    </aside>
  );
}
