import type { AgentNode, NodeStatus, NodeType } from "../../shared/types";

type NodePopoverProps = {
  node: AgentNode;
  onClose(): void;
  onRunFromNode?: (nodeId: string) => void;
  onOpenArtifact?: (path: string) => void;
  onRevealArtifact?: (path: string) => void;
  onApproveTemporaryScript?: (nodeId: string) => void;
  onRejectTemporaryScript?: (nodeId: string) => void;
};

const nodeTypeLabels: Record<NodeType, string> = {
  fixed_tool: "固定工具",
  model: "模型调用",
  output: "输出节点",
  temporary_placeholder: "临时占位",
  planning: "规划节点",
  temporary_script: "临时代码",
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
  if (node.nodeType === "planning") {
    return "不可执行";
  }

  if (node.nodeType === "temporary_script") {
    return "临时代码审查";
  }

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

function renderMetricChips(
  metrics: AgentNode["estimate"] | AgentNode["resourceUsage"],
) {
  if (!metrics) {
    return <span className="nodePopoverEmpty">暂无</span>;
  }

  const chips = [
    formatDuration(metrics.durationMs),
    metrics.cpu ? `CPU ${metrics.cpu}` : null,
    metrics.memory ? `${metrics.memory}` : null,
    metrics.network ? `Net ${metrics.network}` : null,
  ];

  const extraChips = Object.entries(metrics)
    .filter(
      ([key, value]) =>
        !["durationMs", "cpu", "memory", "network"].includes(key) &&
        value !== undefined &&
        value !== null,
    )
    .map(([key, value]) => `${key}: ${String(value)}`);

  const visibleChips = [...chips, ...extraChips].filter(
    (chip): chip is string => Boolean(chip),
  );

  if (visibleChips.length === 0) {
    return <span className="nodePopoverEmpty">暂无</span>;
  }

  return (
    <ul className="nodePopoverPortList">
      {visibleChips.map((chip) => (
        <li key={chip}>{chip}</li>
      ))}
    </ul>
  );
}

function renderContract(contract: Record<string, unknown> | undefined) {
  if (!contract) {
    return null;
  }

  return (
    <pre className="nodePopoverCodePreview">
      {JSON.stringify(contract, null, 2)}
    </pre>
  );
}

function formatDuration(durationMs?: number | null): string | null {
  if (durationMs === undefined || durationMs === null) {
    return null;
  }

  if (durationMs < 1000) {
    return `${durationMs}ms`;
  }

  const seconds = durationMs / 1000;
  return `${Number.isInteger(seconds) ? seconds : seconds.toFixed(1)}s`;
}

export function NodePopover({
  node,
  onClose,
  onRunFromNode,
  onOpenArtifact,
  onRevealArtifact,
  onApproveTemporaryScript,
  onRejectTemporaryScript,
}: NodePopoverProps) {
  const canRunFromNode =
    onRunFromNode &&
    node.nodeType !== "temporary_placeholder" &&
    node.nodeType !== "planning" &&
    node.nodeType !== "temporary_script" &&
    !node.scriptReview;
  const canReviewTemporaryScript =
    node.nodeType === "temporary_script" &&
    node.status === "needs_permission" &&
    node.scriptReview?.requiresApproval === true &&
    node.scriptReview.riskLevel === "high" &&
    (onApproveTemporaryScript || onRejectTemporaryScript);

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
        {node.estimate ? (
          <div>
            <dt>预估</dt>
            <dd>{renderMetricChips(node.estimate)}</dd>
          </div>
        ) : null}
        {node.resourceUsage ? (
          <div>
            <dt>资源使用</dt>
            <dd>{renderMetricChips(node.resourceUsage)}</dd>
          </div>
        ) : null}
        {node.runtimeNotice ? (
          <div>
            <dt>运行提示</dt>
            <dd>{node.runtimeNotice.message}</dd>
          </div>
        ) : null}
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
              {node.scriptReview.riskLevel ? (
                <div>风险: {node.scriptReview.riskLevel}</div>
              ) : null}
              <div>审批: {node.scriptReview.status}</div>
              {node.scriptReview.requiresApproval ? <div>需要授权</div> : null}
              {node.scriptReview.approvalFingerprint ? (
                <div>{node.scriptReview.approvalFingerprint}</div>
              ) : null}
              {renderPermissions(node.scriptReview.permissions)}
              {node.scriptReview.codePreview ? (
                <pre className="nodePopoverCodePreview">
                  {node.scriptReview.codePreview}
                </pre>
              ) : null}
              {node.scriptReview.inputContract ? (
                <div>
                  <div>输入契约</div>
                  {renderContract(node.scriptReview.inputContract)}
                </div>
              ) : null}
              {node.scriptReview.outputContract ? (
                <div>
                  <div>输出契约</div>
                  {renderContract(node.scriptReview.outputContract)}
                </div>
              ) : null}
              {canReviewTemporaryScript ? (
                <div className="nodePopoverPermissionActions">
                  {onApproveTemporaryScript ? (
                    <button
                      className="nodePopoverInlineButton nodePopoverApproveButton"
                      onClick={() => onApproveTemporaryScript(node.nodeId)}
                      type="button"
                    >
                      批准
                    </button>
                  ) : null}
                  {onRejectTemporaryScript ? (
                    <button
                      className="nodePopoverInlineButton nodePopoverRejectButton"
                      onClick={() => onRejectTemporaryScript(node.nodeId)}
                      type="button"
                    >
                      拒绝
                    </button>
                  ) : null}
                </div>
              ) : null}
              <div>临时脚本节点当前仅可审查，尚不能执行。</div>
            </dd>
          </div>
        ) : null}
      </dl>
    </aside>
  );
}
