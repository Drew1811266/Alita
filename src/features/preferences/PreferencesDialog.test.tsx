import type { ComponentProps, ReactElement, ReactNode } from "react";
import { isValidElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { PreferencesDialog } from "./PreferencesDialog";
import type {
  ApiProviderConnectionResult,
  PreferencesView,
  SaveApiProviderPayload,
} from "./preferencesApi";

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
    agentModelMode: "api",
    activeApiProviderId: "api-1",
    apiProviderConfigs: [
      {
        providerId: "api-1",
        providerType: "openai",
        displayName: "OpenAI",
        baseUrl: "https://api.openai.com/v1",
        model: "gpt-4.1",
        credentialRef: "alita.api-provider.api-1",
        enabled: true,
        capabilities: ["chat_completions", "streaming", "model_list"],
        hasApiKey: true,
        createdAt: "2026-05-24T00:00:00.000Z",
        updatedAt: "2026-05-24T00:00:00.000Z",
        secretSentinel: "sk-test",
      } as unknown as PreferencesView["preferences"]["apiProviderConfigs"][number],
      {
        providerId: "api-2",
        providerType: "deepseek",
        displayName: "DeepSeek",
        baseUrl: "https://api.deepseek.com/v1",
        model: "deepseek-chat",
        credentialRef: "alita.api-provider.api-2",
        enabled: true,
        capabilities: ["chat_completions", "streaming"],
        hasApiKey: true,
        createdAt: "2026-05-24T00:00:00.000Z",
        updatedAt: "2026-05-24T00:00:00.000Z",
      },
    ],
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

type TestButton = ReactElement<{
  "aria-label"?: string;
  "aria-pressed"?: boolean | "true" | "false";
  children?: ReactNode;
  onClick?: (event?: unknown) => void | Promise<void>;
}>;

type TestForm = ReactElement<{
  "aria-label"?: string;
  children?: ReactNode;
  onSubmit?: (event: {
    preventDefault(): void;
    currentTarget: TestFormElement;
  }) => void | Promise<void>;
}>;

type TestFormField = {
  checked?: boolean;
  value: string;
};

type TestSelect = ReactElement<{
  name?: string;
  onChange?: (event: {
    currentTarget: {
      form: TestFormElement;
    };
  }) => void;
}>;

type TestFormElement = {
  elements: {
    namedItem(name: string): TestFormField | null;
  };
};

function renderPreferenceElements(
  props: Partial<ComponentProps<typeof PreferencesDialog>> = {},
): ReactElement[] {
  return collectElements(
    <PreferencesDialog
      error={null}
      loading={false}
      onAddModel={() => undefined}
      onAddSpeechToTextModel={() => undefined}
      onClose={() => undefined}
      onImportModel={() => undefined}
      onScanModelDirectory={() => undefined}
      onDeleteApiProvider={() => undefined}
      onFetchApiProviderModels={() =>
        Promise.resolve({ ok: true, message: "", models: [] })
      }
      onSaveApiProvider={() => undefined}
      onSetActiveApiProvider={() => undefined}
      onSetDefaultModel={() => undefined}
      onSetAgentModelMode={() => undefined}
      onSetModelAssignment={() => undefined}
      onSetModelStorageDirectory={() => undefined}
      onSetToolEnabled={() => undefined}
      onTestApiProviderConnection={() =>
        Promise.resolve({ ok: true, message: "", models: [] })
      }
      open
      view={view}
      {...props}
    />,
  );
}

function collectElements(node: ReactNode): ReactElement[] {
  const elements: ReactElement[] = [];

  function visit(current: ReactNode): void {
    if (Array.isArray(current)) {
      current.forEach(visit);
      return;
    }

    if (!isValidElement(current)) {
      return;
    }

    if (typeof current.type === "function") {
      const FunctionComponent = current.type as (props: unknown) => ReactNode;
      visit(FunctionComponent(current.props));
      return;
    }

    elements.push(current);
    visit((current.props as { children?: ReactNode }).children);
  }

  visit(node);
  return elements;
}

function buttonText(button: TestButton): string {
  return textContent(button.props.children);
}

function textContent(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }

  if (Array.isArray(node)) {
    return node.map(textContent).join("");
  }

  if (isValidElement(node)) {
    return textContent((node.props as { children?: ReactNode }).children);
  }

  return "";
}

function findButtonByLabel(elements: ReactElement[], label: string): TestButton {
  const button = elements.find(
    (element): element is TestButton =>
      element.type === "button" &&
      (element.props as { "aria-label"?: string })["aria-label"] === label,
  );

  if (!button) {
    throw new Error(`Button with aria-label "${label}" was not found.`);
  }

  return button;
}

function findButtonsByText(
  elements: ReactElement[],
  text: string,
): TestButton[] {
  return elements.filter(
    (element): element is TestButton =>
      element.type === "button" && buttonText(element as TestButton) === text,
  );
}

function findFormByLabel(elements: ReactElement[], label: string): TestForm {
  const form = elements.find(
    (element): element is TestForm =>
      element.type === "form" &&
      (element.props as { "aria-label"?: string })["aria-label"] === label,
  );

  if (!form) {
    throw new Error(`Form with aria-label "${label}" was not found.`);
  }

  return form;
}

function findSelectByName(elements: ReactElement[], name: string): TestSelect {
  const select = elements.find(
    (element): element is TestSelect =>
      element.type === "select" &&
      (element.props as { name?: string }).name === name,
  );

  if (!select) {
    throw new Error(`Select with name "${name}" was not found.`);
  }

  return select;
}

function createProviderForm(
  values: Record<string, string | boolean>,
): { form: TestFormElement; fields: Record<string, TestFormField> } {
  const fields = Object.fromEntries(
    Object.entries(values).map(([name, value]) => [
      name,
      typeof value === "boolean" ? { checked: value, value: "" } : { value },
    ]),
  ) as Record<string, TestFormField>;

  return {
    fields,
    form: {
      elements: {
        namedItem(name: string) {
          return fields[name] ?? null;
        },
      },
    },
  };
}

const providerFormValues = {
  providerId: "",
  savedProvider: "",
  providerType: "deepseek",
  displayName: "DeepSeek",
  baseUrl: "https://api.deepseek.com",
  model: "deepseek-chat",
  apiKey: "sk-form",
  enabled: true,
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
        onDeleteApiProvider={() => undefined}
        onFetchApiProviderModels={() =>
          Promise.resolve({ ok: true, message: "", models: [] })
        }
        onSaveApiProvider={() => undefined}
        onSetActiveApiProvider={() => undefined}
        onSetDefaultModel={() => undefined}
        onSetAgentModelMode={() => undefined}
        onSetModelAssignment={() => undefined}
        onSetModelStorageDirectory={() => undefined}
        onSetToolEnabled={() => undefined}
        onTestApiProviderConnection={() =>
          Promise.resolve({ ok: true, message: "", models: [] })
        }
        open
        view={view}
      />,
    );

    expect(markup).toContain("首选项");
    expect(markup).toContain("Agent 模型配置");
    expect(markup).toContain("Agent 模型来源");
    expect(markup).toContain('role="group"');
    expect(markup).toContain('aria-pressed="false"');
    expect(markup).toContain('aria-pressed="true"');
    expect(markup).toContain("本地模型");
    expect(markup).toContain("API 模型");
    expect(markup).toContain("API 供应商");
    expect(markup).toContain("添加 API 供应商");
    expect(markup).toContain("测试连接");
    expect(markup).toContain("拉取模型列表");
    expect(markup).toContain("供应商类型");
    expect(markup).toContain("显示名称");
    expect(markup).toContain("Base URL");
    expect(markup).toContain("模型名称");
    expect(markup).toContain("API 密钥");
    expect(markup).toContain("启用供应商");
    expect(markup).toContain("OpenAI");
    expect(markup).toContain("gpt-4.1");
    expect(markup).toContain("https://api.openai.com/v1");
    expect(markup).toContain("密钥已配置");
    expect(markup).toContain("当前 Agent API");
    expect(markup).toContain("设为当前 API：DeepSeek");
    expect(markup).toContain("删除 API 供应商：OpenAI");
    expect(markup).toContain("删除 API 供应商：DeepSeek");
    expect(markup).toContain("删除");
    expect(markup).not.toContain("sk-test");
    expect(markup).not.toContain("credentialRef");
    expect(markup).not.toContain("alita.api-provider.api-1");
    expect(markup).not.toContain("alita.api-provider.api-2");
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

  it("calls the mode change handler from local and API buttons", () => {
    const onSetAgentModelMode = vi.fn();
    const elements = renderPreferenceElements({ onSetAgentModelMode });

    const [localButton] = findButtonsByText(elements, "本地模型");
    const [apiButton] = findButtonsByText(elements, "API 模型");

    expect(localButton.props["aria-pressed"]).toBe(false);
    expect(apiButton.props["aria-pressed"]).toBe(true);

    localButton.props.onClick?.();
    apiButton.props.onClick?.();

    expect(onSetAgentModelMode).toHaveBeenNthCalledWith(1, "local");
    expect(onSetAgentModelMode).toHaveBeenNthCalledWith(2, "api");
  });

  it("calls the set-active handler for a provider-specific action", () => {
    const onSetActiveApiProvider = vi.fn();
    const elements = renderPreferenceElements({ onSetActiveApiProvider });

    findButtonByLabel(elements, "设为当前 API：DeepSeek").props.onClick?.();

    expect(onSetActiveApiProvider).toHaveBeenCalledWith("api-2");
  });

  it("calls the delete handler for provider-specific actions", () => {
    const onDeleteApiProvider = vi.fn();
    const elements = renderPreferenceElements({ onDeleteApiProvider });

    findButtonByLabel(elements, "删除 API 供应商：OpenAI").props.onClick?.();
    findButtonByLabel(elements, "删除 API 供应商：DeepSeek").props.onClick?.();

    expect(onDeleteApiProvider).toHaveBeenNthCalledWith(1, "api-1");
    expect(onDeleteApiProvider).toHaveBeenNthCalledWith(2, "api-2");
  });

  it("submits the API provider form payload and clears only the API key", async () => {
    const onSaveApiProvider = vi.fn(() => Promise.resolve());
    const elements = renderPreferenceElements({ onSaveApiProvider });
    const { fields, form } = createProviderForm(providerFormValues);

    await findFormByLabel(elements, "API 供应商表单").props.onSubmit?.({
      currentTarget: form,
      preventDefault: () => undefined,
    });

    expect(onSaveApiProvider).toHaveBeenCalledWith({
      providerType: "deepseek",
      displayName: "DeepSeek",
      baseUrl: "https://api.deepseek.com",
      model: "deepseek-chat",
      enabled: true,
      apiKey: "sk-form",
    } satisfies SaveApiProviderPayload);
    expect(fields.apiKey.value).toBe("");
    expect(fields.model.value).toBe("deepseek-chat");
  });

  it("keeps the API key when saving the provider fails", async () => {
    const saveError = new Error("save failed");
    const onSaveApiProvider = vi.fn(() => Promise.reject(saveError));
    const elements = renderPreferenceElements({ onSaveApiProvider });
    const { fields, form } = createProviderForm(providerFormValues);

    await expect(
      findFormByLabel(elements, "API 供应商表单").props.onSubmit?.({
        currentTarget: form,
        preventDefault: () => undefined,
      }),
    ).resolves.toBeUndefined();

    expect(onSaveApiProvider).toHaveBeenCalledWith({
      providerType: "deepseek",
      displayName: "DeepSeek",
      baseUrl: "https://api.deepseek.com",
      model: "deepseek-chat",
      enabled: true,
      apiKey: "sk-form",
    } satisfies SaveApiProviderPayload);
    expect(fields.apiKey.value).toBe("sk-form");
  });

  it("keeps the edited provider id when applying a provider type preset", async () => {
    const onSaveApiProvider = vi.fn(() => Promise.resolve());
    const elements = renderPreferenceElements({ onSaveApiProvider });
    const { fields, form } = createProviderForm({
      ...providerFormValues,
      providerId: "api-1",
      savedProvider: "api-1",
      providerType: "deepseek",
      displayName: "OpenAI",
      baseUrl: "https://api.openai.com/v1",
      model: "gpt-4.1",
    });

    findSelectByName(elements, "providerType").props.onChange?.({
      currentTarget: { form },
    });

    expect(fields.providerId.value).toBe("api-1");
    expect(fields.savedProvider.value).toBe("api-1");

    await findFormByLabel(elements, "API 供应商表单").props.onSubmit?.({
      currentTarget: form,
      preventDefault: () => undefined,
    });

    expect(onSaveApiProvider).toHaveBeenCalledWith({
      providerId: "api-1",
      providerType: "deepseek",
      displayName: "DeepSeek",
      baseUrl: "https://api.deepseek.com",
      model: "gpt-4.1",
      enabled: true,
      apiKey: "sk-form",
    } satisfies SaveApiProviderPayload);
  });

  it("tests and fetches API provider helpers with the current form payload", async () => {
    const helperResult: ApiProviderConnectionResult = {
      ok: true,
      message: "Fetched models",
      models: ["deepseek-chat"],
    };
    const onTestApiProviderConnection = vi.fn(() => Promise.resolve(helperResult));
    const onFetchApiProviderModels = vi.fn(() => Promise.resolve(helperResult));
    const elements = renderPreferenceElements({
      onFetchApiProviderModels,
      onTestApiProviderConnection,
    });
    const { form } = createProviderForm(providerFormValues);
    const event = { currentTarget: { form } };

    await findButtonsByText(elements, "测试连接")[0].props.onClick?.(event);
    await findButtonsByText(elements, "拉取模型列表")[0].props.onClick?.(event);

    const expectedPayload = {
      providerType: "deepseek",
      displayName: "DeepSeek",
      baseUrl: "https://api.deepseek.com",
      model: "deepseek-chat",
      enabled: true,
      apiKey: "sk-form",
    } satisfies SaveApiProviderPayload;
    expect(onTestApiProviderConnection).toHaveBeenCalledWith(expectedPayload);
    expect(onFetchApiProviderModels).toHaveBeenCalledWith(expectedPayload);
  });
});
