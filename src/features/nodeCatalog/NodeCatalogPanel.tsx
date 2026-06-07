import { useMemo, useState } from "react";

import type { NodeCatalogEntry, NodeCatalogSnapshot } from "../../shared/types";

type NodeCatalogPanelProps = {
  catalog: NodeCatalogSnapshot | null;
  loading: boolean;
  error: string | null;
  onClose(): void;
  onReload(): void;
};

const categoryLabels: Record<NodeCatalogEntry["category"], string> = {
  document: "文档",
  web: "联网",
  data: "数据",
  reasoning: "推理",
  human: "人机协作",
  verification: "验证",
  output: "输出",
};

const statusLabels: Record<NodeCatalogEntry["availability"]["status"], string> = {
  available: "available",
  degraded: "degraded",
  unavailable: "unavailable",
};

export function NodeCatalogPanel({
  catalog,
  loading,
  error,
  onClose,
  onReload,
}: NodeCatalogPanelProps) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<
    NodeCatalogEntry["category"] | "all"
  >("all");

  const nodes = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();

    return (catalog?.nodes ?? []).filter((node) => {
      const matchesCategory = category === "all" || node.category === category;
      const searchableText = [
        node.nodeId,
        node.displayName,
        node.description,
        ...node.capabilities,
      ]
        .join(" ")
        .toLowerCase();

      return (
        matchesCategory &&
        (!normalizedQuery || searchableText.includes(normalizedQuery))
      );
    });
  }, [catalog, category, query]);

  return (
    <aside className="nodeCatalogPanel" aria-label="节点库">
      <header className="nodeCatalogHeader">
        <div className="nodeCatalogTitleGroup">
          <p className="nodeCatalogKicker">Node Catalog</p>
          <h2>节点库</h2>
          <p>
            {catalog
              ? `${catalog.nodes.length} 个节点 · schema ${catalog.schemaVersion}`
              : "等待节点目录加载"}
          </p>
        </div>
        <div className="nodeCatalogActions">
          <button
            className="secondaryButton compactButton"
            type="button"
            onClick={onReload}
          >
            重新加载
          </button>
          <button
            className="secondaryButton compactButton"
            type="button"
            onClick={onClose}
          >
            关闭
          </button>
        </div>
      </header>

      {loading ? <p className="nodeCatalogState">正在加载节点库</p> : null}
      {error ? (
        <p className="nodeCatalogState nodeCatalogError">{error}</p>
      ) : null}

      <div className="nodeCatalogControls">
        <label>
          <span>搜索节点、能力或说明</span>
          <input
            aria-label="搜索节点、能力或说明"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="nodeId / 名称 / capability"
            type="search"
            value={query}
          />
        </label>
        <label>
          <span>节点分类</span>
          <select
            aria-label="节点分类"
            onChange={(event) =>
              setCategory(
                event.target.value as NodeCatalogEntry["category"] | "all",
              )
            }
            value={category}
          >
            <option value="all">全部分类</option>
            {Object.entries(categoryLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {catalog ? <CatalogSummary catalog={catalog} /> : null}

      <div className="nodeCatalogList" aria-live="polite">
        {nodes.length > 0 ? (
          nodes.map((node) => <CatalogNodeItem key={node.nodeId} node={node} />)
        ) : (
          <p className="nodeCatalogEmpty">没有匹配的节点。</p>
        )}
      </div>
    </aside>
  );
}

function CatalogSummary({ catalog }: { catalog: NodeCatalogSnapshot }) {
  return (
    <dl className="nodeCatalogSummary">
      <div>
        <dt>internal</dt>
        <dd>{catalog.sourceSummary.internalToolCount}</dd>
      </div>
      <div>
        <dt>system</dt>
        <dd>{catalog.sourceSummary.systemNodeCount}</dd>
      </div>
      <div>
        <dt>mcp</dt>
        <dd>{catalog.sourceSummary.mcpNodeCount}</dd>
      </div>
      <div>
        <dt>plugin</dt>
        <dd>{catalog.sourceSummary.pluginNodeCount}</dd>
      </div>
    </dl>
  );
}

function CatalogNodeItem({ node }: { node: NodeCatalogEntry }) {
  const reasonCode = node.availability.reasonCode;

  return (
    <article className="nodeCatalogItem">
      <header>
        <div>
          <h3>{node.displayName}</h3>
          <p className="nodeCatalogNodeId">{node.nodeId}</p>
        </div>
        <span
          className={`nodeCatalogStatus nodeCatalogStatus-${node.availability.status}`}
        >
          {statusLabels[node.availability.status]}
        </span>
      </header>

      <p className="nodeCatalogDescription">{node.description}</p>
      {reasonCode ? <p className="nodeCatalogReason">{reasonCode}</p> : null}

      <dl className="nodeCatalogDetails">
        <Detail label="分类" value={categoryLabels[node.category]} />
        <Detail label="能力" value={formatList(node.capabilities)} />
        <Detail label="输入" value={formatPorts(node.inputPorts)} />
        <Detail label="输出" value={formatPorts(node.outputPorts)} />
        <Detail label="权限" value={formatList(node.permissions.permissions)} />
        <Detail label="风险" value={node.permissions.riskLevel} />
        <Detail label="文件" value={node.permissions.filesystem} />
        <Detail label="沙箱" value={node.permissions.sandbox} />
        <Detail label="执行" value={formatExecution(node)} />
        <Detail label="来源" value={node.source} />
      </dl>
    </article>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function formatPorts(ports: NodeCatalogEntry["inputPorts"]): string {
  if (ports.length === 0) {
    return "无";
  }

  return ports
    .map((port) => {
      const required = port.required ? "必填" : "可选";
      const multiple = port.multiple ? " · 多值" : "";
      return `${port.label} · ${port.dataType} · ${required}${multiple}`;
    })
    .join(", ");
}

function formatList(values: string[]): string {
  return values.length > 0 ? values.join(", ") : "无";
}

function formatExecution(node: NodeCatalogEntry): string {
  const parts = [
    node.execution.type,
    node.execution.bindingRef,
    node.execution.toolId,
    node.execution.operation,
    node.execution.modelPolicy,
    node.execution.verifierType,
    node.execution.outputType,
  ].filter((part): part is string => Boolean(part));

  return Array.from(new Set(parts)).join(" · ");
}
