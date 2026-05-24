import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PreferencesDialog } from "./PreferencesDialog";
import type { PreferencesView } from "./preferencesApi";

const view: PreferencesView = {
  preferences: {
    schemaVersion: 3,
    recentProjects: [],
    modelDirectories: ["D:\\Models"],
    modelStorageDir:
      "C:\\Users\\Drew\\AppData\\Local\\Alita\\models",
    defaultModelId: "model-1",
    modelAssignments: {
      agentChatModelId: "model-1",
      speechToTextModelId: "asr-1",
    },
    agentModelMode: "local",
    activeApiProviderId: null,
    apiProviderConfigs: [],
    models: [
      {
        modelId: "model-1",
        name: "qwen3-8b",
        path: "D:\\Models\\qwen3-8b.gguf",
        modelKind: "agent_llm",
        source: "manual",
        runtime: "llama_cpp",
        pathKind: "file",
        fileExists: true,
        createdAt: "2026-05-09T12:00:00.000Z",
        updatedAt: "2026-05-09T12:00:00.000Z",
      },
      {
        modelId: "asr-1",
        name: "Qwen3-ASR-1.7B",
        path: "D:\\Models\\Qwen3-ASR-1.7B",
        modelKind: "speech_to_text",
        source: "manual",
        runtime: "qwen_asr",
        pathKind: "directory",
        fileExists: true,
        createdAt: "2026-05-09T12:00:00.000Z",
        updatedAt: "2026-05-09T12:00:00.000Z",
      },
    ],
    toolEnablement: { "document.read_write": true },
  },
  tools: [
    {
      toolId: "document.read_write",
      name: "文档处理工具包",
      description: "读取和写入文档。",
      version: "0.1.0",
      sourceType: "python_plugin",
      license: "internal",
      capabilities: [],
      permissions: ["read_project_files"],
      enabled: true,
      valid: true,
    },
    {
      toolId: "document.markitdown_convert",
      name: "MarkItDown 文档转 Markdown",
      description: "把本地文档转换为适合模型读取的 Markdown 文本。",
      version: "0.1.0",
      sourceType: "external_python_package",
      license: "MIT",
      runtime: "python_sidecar",
      packageName: "markitdown",
      packageSource: "github",
      upstreamUrl: "https://github.com/microsoft/markitdown",
      capabilities: ["document.convert.markdown"],
      permissions: [
        "read_project_files",
        "write_project_outputs",
        "run_python_plugin",
      ],
      enabled: true,
      valid: true,
    },
  ],
};

describe("PreferencesDialog", () => {
  it("renders model storage and tool management sections", () => {
    const markup = renderToStaticMarkup(
      <PreferencesDialog
        error={null}
        loading={false}
        onAddModel={() => undefined}
        onAddSpeechToTextModel={() => undefined}
        onClose={() => undefined}
        onImportModel={() => undefined}
        onScanModelDirectory={() => undefined}
        onSetDefaultModel={() => undefined}
        onSetModelAssignment={() => undefined}
        onSetModelStorageDirectory={() => undefined}
        onSetToolEnabled={() => undefined}
        open
        view={view}
      />,
    );

    expect(markup).toContain("首选项");
    expect(markup).toContain("模型");
    expect(markup).toContain("模型存储目录");
    expect(markup).toContain("更改目录");
    expect(markup).toContain("导入 GGUF 到模型库");
    expect(markup).toContain("引用外部 GGUF");
    expect(markup).toContain("扫描模型目录");
    expect(markup).toContain("模型库");
    expect(markup).toContain("当前模型分配");
    expect(markup).toContain("Agent 模型");
    expect(markup).toContain("语音转文字");
    expect(markup).toContain("添加语音转文字模型");
    expect(markup).toContain("qwen3-8b");
    expect(markup).toContain("Qwen3-ASR-1.7B");
    expect(markup).toContain("Qwen ASR");
    expect(markup).toContain("当前语音转文字模型");
    expect(markup).toContain("当前 Agent 模型");
    expect(markup).toContain("MarkItDown 文档转 Markdown");
    expect(markup).toContain("external_python_package");
    expect(markup).toContain("python_sidecar");
    expect(markup).toContain("MIT");
    expect(markup).toContain("document.convert.markdown");
    expect(markup).toContain("工具节点");
    expect(markup).toContain("文档处理工具包");
    expect(markup).toContain("启用");
  });
});
