import type { ComponentProps, ReactElement, ReactNode } from "react";
import { isValidElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

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
        apiKeyStatus: "configured",
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
        hasApiKey: false,
        apiKeyStatus: "unknown",
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
  onChange?: (event: {
    currentTarget: TestFormElement;
  }) => void;
  onInput?: (event: {
    currentTarget: TestFormElement;
  }) => void;
  onReset?: (event: {
    currentTarget: TestFormElement;
    preventDefault(): void;
  }) => void;
  onSubmit?: (event: {
    preventDefault(): void;
    currentTarget: TestFormElement;
  }) => void | Promise<void>;
}>;

type TestFormField = {
  checked?: boolean;
  appendChild?(child: unknown): void;
  children?: Array<{ textContent: string | null; value: string }>;
  innerHTML?: string;
  textContent?: string | null;
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

afterEach(() => {
  vi.unstubAllGlobals();
});

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
  values: Record<string, string | boolean | TestFormField>,
): { form: TestFormElement; fields: Record<string, TestFormField> } {
  const fields = Object.fromEntries(
    Object.entries(values).map(([name, value]) => [
      name,
      typeof value === "boolean"
        ? { checked: value, value: "" }
        : typeof value === "string"
          ? { value }
          : value,
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

function createOptionField(value: string): TestFormField {
  return {
    textContent: value,
    value,
  };
}

function createSelectField(options: string[]): TestFormField {
  const field = {
    children: options.map((value) => ({ textContent: value, value })),
    value: options[0] ?? "",
    appendChild(child: unknown) {
      const option = child as { textContent?: string | null; value?: string };
      this.children?.push({
        textContent: option.textContent ?? null,
        value: option.value ?? "",
      });
      if (!this.value) {
        this.value = option.value ?? "";
      }
    },
  } satisfies TestFormField;
  let innerHTML = options.join("");
  Object.defineProperty(field, "innerHTML", {
    get() {
      return innerHTML;
    },
    set(value: string) {
      innerHTML = value;
      if (value === "") {
        field.children = [];
      }
    },
  });
  return field;
}

function optionValues(field: TestFormField): string[] {
  return field.children?.map((child) => child.value) ?? [];
}

function stubDocumentCreateElement(): void {
  vi.stubGlobal("document", {
    createElement: () => createOptionField(""),
  });
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
    expect(markup).toContain('role="status"');
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
    expect(markup).toContain("密钥状态不可用");
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

  it("clears stale fetched models when fetch returns an empty or failed result", async () => {
    stubDocumentCreateElement();
    const onFetchApiProviderModels = vi
      .fn<() => Promise<ApiProviderConnectionResult>>()
      .mockResolvedValueOnce({
        ok: true,
        message: "Fetched models",
        models: ["deepseek-chat"],
      })
      .mockResolvedValueOnce({
        ok: true,
        message: "",
        models: [],
      })
      .mockResolvedValueOnce({
        ok: false,
        message: "Fetch failed",
        models: ["wrong-provider-model"],
      });
    const elements = renderPreferenceElements({ onFetchApiProviderModels });
    const fetchedModel = createSelectField(["stale-model"]);
    const providerHelperMessage = {
      textContent: "Old helper message",
      value: "",
    } satisfies TestFormField;
    const { form } = createProviderForm({
      ...providerFormValues,
      fetchedModel,
      providerHelperMessage,
    });
    const event = { currentTarget: { form } };
    const fetchButton = findButtonsByText(elements, "拉取模型列表")[0];

    await fetchButton.props.onClick?.(event);

    expect(optionValues(fetchedModel)).toEqual(["deepseek-chat"]);
    expect(providerHelperMessage.textContent).toBe("Fetched models");

    await fetchButton.props.onClick?.(event);

    expect(optionValues(fetchedModel)).toEqual([""]);
    expect(fetchedModel.value).toBe("");
    expect(providerHelperMessage.textContent).toBe("");

    await fetchButton.props.onClick?.(event);

    expect(optionValues(fetchedModel)).toEqual([""]);
    expect(fetchedModel.value).toBe("");
    expect(providerHelperMessage.textContent).toBe("Fetch failed");
  });

  it("handles helper rejections without rejecting the click promise", async () => {
    stubDocumentCreateElement();
    const onFetchApiProviderModels = vi
      .fn<() => Promise<ApiProviderConnectionResult>>()
      .mockResolvedValueOnce({
        ok: true,
        message: "Fetched models",
        models: ["deepseek-chat"],
      })
      .mockRejectedValueOnce(new Error("network unavailable"));
    const elements = renderPreferenceElements({ onFetchApiProviderModels });
    const fetchedModel = createSelectField(["stale-model"]);
    const providerHelperMessage = {
      textContent: "Old helper message",
      value: "",
    } satisfies TestFormField;
    const { form } = createProviderForm({
      ...providerFormValues,
      fetchedModel,
      providerHelperMessage,
    });
    const event = { currentTarget: { form } };
    const fetchButton = findButtonsByText(elements, "拉取模型列表")[0];

    await fetchButton.props.onClick?.(event);
    await expect(fetchButton.props.onClick?.(event)).resolves.toBeUndefined();

    expect(optionValues(fetchedModel)).toEqual([""]);
    expect(fetchedModel.value).toBe("");
    expect(providerHelperMessage.textContent).toContain("network unavailable");
  });

  it("ignores stale API provider helper responses after the form changes", async () => {
    stubDocumentCreateElement();
    let resolveFetch:
      | ((result: ApiProviderConnectionResult) => void)
      | undefined;
    const pendingFetch = new Promise<ApiProviderConnectionResult>((resolve) => {
      resolveFetch = resolve;
    });
    const onFetchApiProviderModels = vi.fn(
      (_payload: SaveApiProviderPayload) => pendingFetch,
    );
    const elements = renderPreferenceElements({ onFetchApiProviderModels });
    const fetchedModel = createSelectField([""]);
    const providerHelperMessage = {
      textContent: "",
      value: "",
    } satisfies TestFormField;
    const { fields, form } = createProviderForm({
      ...providerFormValues,
      providerId: "api-1",
      baseUrl: "https://api.openai.com/v1",
      model: "",
      fetchedModel,
      providerHelperMessage,
    });
    const fetchButton = findButtonsByText(elements, "拉取模型列表")[0];

    const clickPromise = fetchButton.props.onClick?.({
      currentTarget: { form },
    });

    fields.providerId.value = "api-2";
    fields.baseUrl.value = "https://api.deepseek.com/v1";
    resolveFetch?.({
      ok: true,
      message: "Fetched stale models",
      models: ["gpt-stale"],
    });
    await clickPromise;

    expect(optionValues(fetchedModel)).toEqual([""]);
    expect(fetchedModel.value).toBe("");
    expect(fields.model.value).toBe("");
    expect(providerHelperMessage.textContent).toBe("");
  });

  it("ignores helper responses after the form changes back to the original payload", async () => {
    stubDocumentCreateElement();
    let resolveFetch:
      | ((result: ApiProviderConnectionResult) => void)
      | undefined;
    const pendingFetch = new Promise<ApiProviderConnectionResult>((resolve) => {
      resolveFetch = resolve;
    });
    const onFetchApiProviderModels = vi.fn(
      (_payload: SaveApiProviderPayload) => pendingFetch,
    );
    const elements = renderPreferenceElements({ onFetchApiProviderModels });
    const fetchedModel = createSelectField([""]);
    const providerHelperMessage = {
      textContent: "",
      value: "",
    } satisfies TestFormField;
    const { fields, form } = createProviderForm({
      ...providerFormValues,
      providerId: "api-1",
      baseUrl: "https://api.openai.com/v1",
      model: "",
      fetchedModel,
      providerHelperMessage,
    });
    const apiProviderForm = findFormByLabel(elements, "API 供应商表单");
    const fetchButton = findButtonsByText(elements, "拉取模型列表")[0];

    const clickPromise = fetchButton.props.onClick?.({
      currentTarget: { form },
    });

    fields.providerId.value = "api-2";
    fields.baseUrl.value = "https://api.deepseek.com/v1";
    apiProviderForm.props.onChange?.({ currentTarget: form });
    fields.providerId.value = "api-1";
    fields.baseUrl.value = "https://api.openai.com/v1";
    apiProviderForm.props.onChange?.({ currentTarget: form });
    resolveFetch?.({
      ok: true,
      message: "Fetched stale models",
      models: ["gpt-stale"],
    });
    await clickPromise;

    expect(optionValues(fetchedModel)).toEqual([""]);
    expect(fetchedModel.value).toBe("");
    expect(fields.model.value).toBe("");
    expect(providerHelperMessage.textContent).toBe("");
  });

  it("keeps the latest API provider helper response when requests finish out of order", async () => {
    stubDocumentCreateElement();
    let resolveFirst:
      | ((result: ApiProviderConnectionResult) => void)
      | undefined;
    let resolveSecond:
      | ((result: ApiProviderConnectionResult) => void)
      | undefined;
    const firstFetch = new Promise<ApiProviderConnectionResult>((resolve) => {
      resolveFirst = resolve;
    });
    const secondFetch = new Promise<ApiProviderConnectionResult>((resolve) => {
      resolveSecond = resolve;
    });
    const onFetchApiProviderModels = vi
      .fn<() => Promise<ApiProviderConnectionResult>>()
      .mockReturnValueOnce(firstFetch)
      .mockReturnValueOnce(secondFetch);
    const elements = renderPreferenceElements({ onFetchApiProviderModels });
    const fetchedModel = createSelectField([""]);
    const providerHelperMessage = {
      textContent: "",
      value: "",
    } satisfies TestFormField;
    const { fields, form } = createProviderForm({
      ...providerFormValues,
      model: "",
      fetchedModel,
      providerHelperMessage,
    });
    const fetchButton = findButtonsByText(elements, "拉取模型列表")[0];

    const firstClick = fetchButton.props.onClick?.({ currentTarget: { form } });
    const secondClick = fetchButton.props.onClick?.({ currentTarget: { form } });

    resolveSecond?.({
      ok: true,
      message: "Fetched current models",
      models: ["current-model"],
    });
    await secondClick;
    resolveFirst?.({
      ok: true,
      message: "Fetched stale models",
      models: ["stale-model"],
    });
    await firstClick;

    expect(optionValues(fetchedModel)).toEqual(["current-model"]);
    expect(fetchedModel.value).toBe("current-model");
    expect(fields.model.value).toBe("current-model");
    expect(providerHelperMessage.textContent).toBe("Fetched current models");
  });

  it("clears fetched models and helper message on API provider form reset", () => {
    const elements = renderPreferenceElements();
    const fetchedModel = createSelectField(["stale-model"]);
    const providerHelperMessage = {
      textContent: "Fetched models",
      value: "",
    } satisfies TestFormField;
    const { form } = createProviderForm({
      ...providerFormValues,
      fetchedModel,
      providerHelperMessage,
    });
    const preventDefault = vi.fn();

    findFormByLabel(elements, "API 供应商表单").props.onReset?.({
      currentTarget: form,
      preventDefault,
    });

    expect(preventDefault).not.toHaveBeenCalled();
    expect(optionValues(fetchedModel)).toEqual([""]);
    expect(fetchedModel.value).toBe("");
    expect(providerHelperMessage.textContent).toBe("");
  });

  it("clears fetched models and helper message when provider selections change", () => {
    const elements = renderPreferenceElements();
    const fetchedModel = createSelectField(["stale-model"]);
    const providerHelperMessage = {
      textContent: "Fetched models",
      value: "",
    } satisfies TestFormField;
    const { fields, form } = createProviderForm({
      ...providerFormValues,
      savedProvider: "api-1",
      providerId: "api-1",
      providerType: "deepseek",
      fetchedModel,
      providerHelperMessage,
    });

    findSelectByName(elements, "providerType").props.onChange?.({
      currentTarget: { form },
    });

    expect(optionValues(fetchedModel)).toEqual([""]);
    expect(fetchedModel.value).toBe("");
    expect(providerHelperMessage.textContent).toBe("");

    fetchedModel.children = [{ textContent: "stale-model", value: "stale-model" }];
    fetchedModel.value = "stale-model";
    providerHelperMessage.textContent = "Fetched models";
    fields.savedProvider.value = "api-2";

    findSelectByName(elements, "savedProvider").props.onChange?.({
      currentTarget: { form },
    });

    expect(fields.providerId.value).toBe("api-2");
    expect(fields.model.value).toBe("deepseek-chat");
    expect(optionValues(fetchedModel)).toEqual([""]);
    expect(fetchedModel.value).toBe("");
    expect(providerHelperMessage.textContent).toBe("");

    fetchedModel.children = [{ textContent: "stale-model", value: "stale-model" }];
    fetchedModel.value = "stale-model";
    providerHelperMessage.textContent = "Fetched models";
    fields.savedProvider.value = "";

    findSelectByName(elements, "savedProvider").props.onChange?.({
      currentTarget: { form },
    });

    expect(fields.providerId.value).toBe("");
    expect(fields.model.value).toBe("deepseek-chat");
    expect(optionValues(fetchedModel)).toEqual([""]);
    expect(fetchedModel.value).toBe("");
    expect(providerHelperMessage.textContent).toBe("");
  });
});
