import type { AgentNode, NodeGraph } from "../../shared/types";

function createNode(node: AgentNode): AgentNode {
  return node;
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
      nodeId: "file-export",
      nodeType: "output",
      displayName: "导出文件",
      status: "waiting",
      inputPorts: [
        { id: "outline", label: "整理提纲", dataType: "json" },
        { id: "report-draft", label: "报告正文", dataType: "text" },
      ],
      outputPorts: [{ id: "exported-file", label: "导出文件", dataType: "artifact" }],
      dependencies: ["content-organize", "report-generate"],
      summary: "汇合整理提纲和报告正文，生成可下载的最终文件。",
      createdBy: "agent",
      artifactRefs: [],
      retryCount: 0,
      position: { x: 260, y: 560 },
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
        id: "content-organize-file-export",
        source: "content-organize",
        target: "file-export",
      },
      {
        id: "report-generate-file-export",
        source: "report-generate",
        target: "file-export",
      },
    ],
  };
}
