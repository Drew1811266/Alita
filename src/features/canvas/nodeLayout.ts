import type { AgentNode, NodeGraph } from "../../shared/types";

export const CANVAS_LAYOUT_NODE_WIDTH = 236;
export const CANVAS_LAYOUT_NODE_HEIGHT = 220;

const CANVAS_LAYOUT_ORIGIN_X = 260;
const CANVAS_LAYOUT_ORIGIN_Y = 40;
const CANVAS_LAYOUT_COLUMN_STEP = 340;
const CANVAS_LAYOUT_ROW_STEP = 260;

function createNode(node: AgentNode): AgentNode {
  return node;
}

export function layoutGraphForCanvas(graph: NodeGraph): NodeGraph {
  const indexById = new Map(
    graph.nodes.map((node, index) => [node.nodeId, index] as const),
  );
  const dependenciesById = buildDependenciesById(graph);
  const layerById = new Map<string, number>();

  const getLayer = (nodeId: string, visiting = new Set<string>()): number => {
    const cached = layerById.get(nodeId);
    if (cached !== undefined) {
      return cached;
    }
    if (visiting.has(nodeId)) {
      return 0;
    }

    visiting.add(nodeId);
    const dependencies = dependenciesById.get(nodeId) ?? [];
    const layer =
      dependencies.length === 0
        ? 0
        : Math.max(
            ...dependencies.map((dependency) => getLayer(dependency, visiting)),
          ) + 1;
    visiting.delete(nodeId);
    layerById.set(nodeId, layer);
    return layer;
  };

  for (const node of graph.nodes) {
    getLayer(node.nodeId);
  }

  const nodesByLayer = new Map<number, AgentNode[]>();
  for (const node of graph.nodes) {
    const layer = layerById.get(node.nodeId) ?? 0;
    nodesByLayer.set(layer, [...(nodesByLayer.get(layer) ?? []), node]);
  }

  const positionById = new Map<string, { x: number; y: number }>();
  for (const [layer, nodes] of [...nodesByLayer.entries()].sort(
    ([first], [second]) => first - second,
  )) {
    const orderedNodes = [...nodes].sort((first, second) => {
      const xDelta = first.position.x - second.position.x;
      if (xDelta !== 0) {
        return xDelta;
      }
      const yDelta = first.position.y - second.position.y;
      if (yDelta !== 0) {
        return yDelta;
      }
      return (indexById.get(first.nodeId) ?? 0) - (indexById.get(second.nodeId) ?? 0);
    });
    const layerWidth = (orderedNodes.length - 1) * CANVAS_LAYOUT_COLUMN_STEP;

    for (const [index, node] of orderedNodes.entries()) {
      positionById.set(node.nodeId, {
        x: CANVAS_LAYOUT_ORIGIN_X - layerWidth / 2 + index * CANVAS_LAYOUT_COLUMN_STEP,
        y: CANVAS_LAYOUT_ORIGIN_Y + layer * CANVAS_LAYOUT_ROW_STEP,
      });
    }
  }

  return {
    ...graph,
    nodes: graph.nodes.map((node) => ({
      ...node,
      position: positionById.get(node.nodeId) ?? node.position,
    })),
  };
}

function buildDependenciesById(graph: NodeGraph): Map<string, string[]> {
  const nodeIds = new Set(graph.nodes.map((node) => node.nodeId));
  const dependenciesById = new Map<string, Set<string>>();

  for (const node of graph.nodes) {
    dependenciesById.set(
      node.nodeId,
      new Set(node.dependencies.filter((dependency) => nodeIds.has(dependency))),
    );
  }

  for (const edge of graph.edges) {
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) {
      continue;
    }
    dependenciesById.get(edge.target)?.add(edge.source);
  }

  return new Map(
    [...dependenciesById.entries()].map(([nodeId, dependencies]) => [
      nodeId,
      [...dependencies],
    ]),
  );
}

export function createDocumentGraph(): NodeGraph {
  const nodes: AgentNode[] = [
    createNode({
      nodeId: "document-input",
      nodeType: "fixed_tool",
      displayName: "文档输入",
      status: "ready",
      inputPorts: [{ id: "user-file", label: "用户附件", dataType: "document" }],
      outputPorts: [{ id: "document-file", label: "文档文件", dataType: "document" }],
      dependencies: [],
      toolRef: "document.receive_attachment",
      summary: "接收用户上传的文档，并准备后续解析所需的文件引用。",
      createdBy: "agent",
      artifactRefs: [],
      retryCount: 0,
      position: { x: 260, y: 20 },
    }),
    createNode({
      nodeId: "document-parse",
      nodeType: "fixed_tool",
      displayName: "文档解析",
      status: "ready",
      inputPorts: [{ id: "document-file", label: "文档文件", dataType: "document" }],
      outputPorts: [{ id: "structured-content", label: "结构化内容", dataType: "json" }],
      dependencies: ["document-input"],
      toolRef: "document.extract_text",
      summary: "读取正文、标题层级和基础元数据，形成可供模型处理的结构化内容。",
      createdBy: "agent",
      artifactRefs: [],
      retryCount: 0,
      position: { x: 260, y: 190 },
    }),
    createNode({
      nodeId: "content-organize",
      nodeType: "model",
      displayName: "内容整理",
      status: "waiting",
      inputPorts: [{ id: "structured-content", label: "结构化内容", dataType: "json" }],
      outputPorts: [{ id: "outline", label: "整理提纲", dataType: "json" }],
      dependencies: ["document-parse"],
      modelRef: "gpt-content-organizer",
      summary: "梳理文档结构、关键观点和可复用素材，为报告生成提供提纲。",
      createdBy: "agent",
      artifactRefs: [],
      retryCount: 0,
      position: { x: 80, y: 370 },
    }),
    createNode({
      nodeId: "report-generate",
      nodeType: "model",
      displayName: "报告生成",
      status: "waiting",
      inputPorts: [{ id: "structured-content", label: "结构化内容", dataType: "json" }],
      outputPorts: [{ id: "report-draft", label: "报告正文", dataType: "text" }],
      dependencies: ["document-parse"],
      modelRef: "gpt-report-writer",
      summary: "根据解析结果生成中文报告初稿，并保留可追溯的内容依据。",
      createdBy: "agent",
      artifactRefs: [],
      retryCount: 0,
      position: { x: 440, y: 370 },
    }),
    createNode({
      nodeId: "typst-export",
      nodeType: "fixed_tool",
      displayName: "Typst PDF 导出",
      status: "waiting",
      inputPorts: [
        { id: "outline", label: "整理提纲", dataType: "json" },
        { id: "report-draft", label: "报告正文", dataType: "text" },
      ],
      outputPorts: [
        { id: "typst-source", label: "Typst 源文件", dataType: "artifact" },
        { id: "pdf-file", label: "PDF 文件", dataType: "artifact" },
      ],
      dependencies: ["content-organize", "report-generate"],
      toolRef: "document.typst_compile",
      summary: "把整理提纲和报告正文排版为 Typst 源文件，并编译为 PDF。",
      createdBy: "agent",
      artifactRefs: [],
      retryCount: 0,
      position: { x: 260, y: 560 },
    }),
    createNode({
      nodeId: "file-export",
      nodeType: "output",
      displayName: "导出文件",
      status: "waiting",
      inputPorts: [{ id: "pdf-file", label: "PDF 文件", dataType: "artifact" }],
      outputPorts: [{ id: "exported-file", label: "导出文件", dataType: "artifact" }],
      dependencies: ["typst-export"],
      summary: "汇总 Typst 源文件和 PDF，生成可下载的最终文件。",
      createdBy: "agent",
      artifactRefs: [],
      retryCount: 0,
      position: { x: 260, y: 750 },
    }),
  ];

  return {
    graphId: "sample-document-flow",
    nodes,
    edges: [
      {
        id: "document-input-document-parse",
        source: "document-input",
        target: "document-parse",
      },
      {
        id: "document-parse-content-organize",
        source: "document-parse",
        target: "content-organize",
      },
      {
        id: "document-parse-report-generate",
        source: "document-parse",
        target: "report-generate",
      },
      {
        id: "content-organize-typst-export",
        source: "content-organize",
        target: "typst-export",
      },
      {
        id: "report-generate-typst-export",
        source: "report-generate",
        target: "typst-export",
      },
      {
        id: "typst-export-file-export",
        source: "typst-export",
        target: "file-export",
      },
    ],
  };
}
