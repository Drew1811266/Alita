import type {
  AgentModelMode,
  ApiProviderConfig,
  ApiProviderType,
  ModelEntry,
  ToolSummary,
} from "../../shared/types";
import type {
  ApiProviderConnectionResult,
  PreferencesView,
  SaveApiProviderPayload,
} from "./preferencesApi";

type ModelAssignmentRole = "agentChat" | "speechToText";

type PreferencesDialogProps = {
  open: boolean;
  loading: boolean;
  error: string | null;
  view: PreferencesView | null;
  onClose(): void;
  onAddModel(): void;
  onAddSpeechToTextModel(): void;
  onImportModel(): void;
  onScanModelDirectory(): void;
  onSetAgentModelMode(mode: AgentModelMode): void;
  onSaveApiProvider(payload: SaveApiProviderPayload): void | Promise<void>;
  onTestApiProviderConnection(
    payload: SaveApiProviderPayload,
  ): ApiProviderConnectionResult | Promise<ApiProviderConnectionResult>;
  onFetchApiProviderModels(
    payload: SaveApiProviderPayload,
  ): ApiProviderConnectionResult | Promise<ApiProviderConnectionResult>;
  onDeleteApiProvider(providerId: string): void;
  onSetActiveApiProvider(providerId: string): void;
  onSetDefaultModel(modelId: string): void;
  onSetModelAssignment(role: ModelAssignmentRole, modelId: string): void;
  onSetModelStorageDirectory(): void;
  onSetToolEnabled(toolId: string, enabled: boolean): void;
};

export function PreferencesDialog({
  open,
  loading,
  error,
  view,
  onClose,
  onAddModel,
  onAddSpeechToTextModel,
  onImportModel,
  onScanModelDirectory,
  onSetAgentModelMode,
  onDeleteApiProvider,
  onFetchApiProviderModels,
  onSaveApiProvider,
  onSetActiveApiProvider,
  onSetDefaultModel,
  onSetModelAssignment,
  onSetModelStorageDirectory,
  onSetToolEnabled,
  onTestApiProviderConnection,
}: PreferencesDialogProps) {
  if (!open) {
    return null;
  }

  const agentAssignmentId =
    view?.preferences.modelAssignments.agentChatModelId ??
    view?.preferences.defaultModelId ??
    null;
  const speechToTextAssignmentId =
    view?.preferences.modelAssignments.speechToTextModelId ?? null;
  const agentModel = findModelById(view?.preferences.models, agentAssignmentId);
  const speechToTextModel = findModelById(
    view?.preferences.models,
    speechToTextAssignmentId,
  );

  return (
    <div className="preferencesBackdrop" role="presentation">
      <section className="preferencesDialog" aria-labelledby="preferences-title">
        <header className="preferencesHeader">
          <div>
            <h2 id="preferences-title">首选项</h2>
            <p>管理本地模型和 Agent 可使用的工具节点。</p>
          </div>
          <button className="secondaryButton" onClick={onClose} type="button">
            关闭
          </button>
        </header>

        {loading ? <p className="preferencesState">正在加载首选项。</p> : null}
        {error ? <p className="errorText">{error}</p> : null}

        {view ? (
          <div className="preferencesGrid">
            <aside className="preferencesSidebar">
              <strong>首选项</strong>
              <span>模型</span>
              <span>工具节点</span>
              <span>Agent</span>
              <span>安全</span>
            </aside>
            <div className="preferencesContent">
              <section className="preferencesSection">
                <div className="preferencesSectionHeader">
                  <h3>Agent 模型配置</h3>
                  <div
                    aria-label="Agent 模型来源"
                    className="agentModelSourceControls"
                    role="group"
                  >
                    <button
                      aria-pressed={view.preferences.agentModelMode === "local"}
                      className={
                        view.preferences.agentModelMode === "local"
                          ? "primaryButton"
                          : "secondaryButton"
                      }
                      onClick={() => onSetAgentModelMode("local")}
                      type="button"
                    >
                      本地模型
                    </button>
                    <button
                      aria-pressed={view.preferences.agentModelMode === "api"}
                      className={
                        view.preferences.agentModelMode === "api"
                          ? "primaryButton"
                          : "secondaryButton"
                      }
                      onClick={() => onSetAgentModelMode("api")}
                      type="button"
                    >
                      API 模型
                    </button>
                  </div>
                </div>

                {view.preferences.agentModelMode === "api" ? (
                  <>
                    <ApiProviderForm
                      providers={view.preferences.apiProviderConfigs}
                      onFetchApiProviderModels={onFetchApiProviderModels}
                      onSaveApiProvider={onSaveApiProvider}
                      onTestApiProviderConnection={onTestApiProviderConnection}
                    />
                    <ApiProviderList
                      activeApiProviderId={view.preferences.activeApiProviderId}
                      providers={view.preferences.apiProviderConfigs}
                      onDeleteApiProvider={onDeleteApiProvider}
                      onSetActiveApiProvider={onSetActiveApiProvider}
                    />
                  </>
                ) : null}
              </section>

              <section className="preferencesSection">
                <div className="preferencesSectionHeader">
                  <h3>模型库</h3>
                  <div className="preferencesActions">
                    <button
                      className="secondaryButton"
                      onClick={onImportModel}
                      type="button"
                    >
                      导入 GGUF 到模型库
                    </button>
                    <button
                      className="secondaryButton"
                      onClick={onAddModel}
                      type="button"
                    >
                      引用外部 GGUF
                    </button>
                    <button
                      className="secondaryButton"
                      onClick={onScanModelDirectory}
                      type="button"
                    >
                      扫描模型目录
                    </button>
                    <button
                      className="secondaryButton"
                      onClick={onAddSpeechToTextModel}
                      type="button"
                    >
                      添加语音转文字模型
                    </button>
                  </div>
                </div>

                <div className="modelStorageBox">
                  <div>
                    <strong>模型存储目录</strong>
                    <span>{view.preferences.modelStorageDir}</span>
                  </div>
                  <button
                    className="secondaryButton"
                    onClick={onSetModelStorageDirectory}
                    type="button"
                  >
                    更改目录
                  </button>
                </div>

                <div className="modelAssignments" aria-label="当前模型分配">
                  <div>
                    <span>Agent 模型</span>
                    <strong>{agentModel?.name ?? "未配置"}</strong>
                  </div>
                  <div>
                    <span>语音转文字</span>
                    <strong>{speechToTextModel?.name ?? "未配置"}</strong>
                  </div>
                </div>

                {view.preferences.models.length > 0 ? (
                  <ul className="modelList">
                    {view.preferences.models.map((model) => (
                      <ModelItem
                        agentAssignmentId={agentAssignmentId}
                        key={model.modelId}
                        model={model}
                        onSetModelAssignment={onSetModelAssignment}
                        speechToTextAssignmentId={speechToTextAssignmentId}
                      />
                    ))}
                  </ul>
                ) : (
                  <p>还没有添加本地模型。</p>
                )}
              </section>

              <section className="preferencesSection">
                <h3>工具节点</h3>
                <ul className="toolList">
                  {view.tools.map((tool) => (
                    <ToolItem
                      key={tool.toolId}
                      onSetToolEnabled={onSetToolEnabled}
                      tool={tool}
                    />
                  ))}
                </ul>
              </section>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}

const API_PROVIDER_PRESETS: Array<{
  providerType: ApiProviderType;
  displayName: string;
  baseUrl: string;
}> = [
  {
    providerType: "openai",
    displayName: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
  },
  {
    providerType: "deepseek",
    displayName: "DeepSeek",
    baseUrl: "https://api.deepseek.com",
  },
  {
    providerType: "kimi",
    displayName: "Kimi",
    baseUrl: "https://api.moonshot.ai/v1",
  },
  {
    providerType: "glm",
    displayName: "GLM",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
  },
  {
    providerType: "minimax",
    displayName: "MiniMax",
    baseUrl: "https://api.minimax.io/v1",
  },
  {
    providerType: "custom",
    displayName: "Custom API",
    baseUrl: "",
  },
];

type ProviderFormField = {
  checked?: boolean;
  textContent?: string | null;
  value?: string;
  innerHTML?: string;
  appendChild?(child: unknown): void;
};

type ProviderFormLike = {
  elements: {
    namedItem(name: string): ProviderFormField | null;
  };
  querySelector?(selector: string): ProviderFormField | null;
};

function ApiProviderForm({
  providers,
  onFetchApiProviderModels,
  onSaveApiProvider,
  onTestApiProviderConnection,
}: {
  providers: ApiProviderConfig[];
  onSaveApiProvider(payload: SaveApiProviderPayload): void | Promise<void>;
  onTestApiProviderConnection(
    payload: SaveApiProviderPayload,
  ): ApiProviderConnectionResult | Promise<ApiProviderConnectionResult>;
  onFetchApiProviderModels(
    payload: SaveApiProviderPayload,
  ): ApiProviderConnectionResult | Promise<ApiProviderConnectionResult>;
}) {
  return (
    <form
      aria-label="API 供应商表单"
      className="apiProviderForm"
      id="api-provider-form"
      name="api-provider-form"
      onSubmit={async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        await onSaveApiProvider(readApiProviderPayload(form));
        setFormFieldValue(form, "apiKey", "");
      }}
    >
      <div className="apiProviderFormHeader">
        <h4>添加 API 供应商</h4>
        <button className="secondaryButton compactButton" type="reset">
          添加 API 供应商
        </button>
      </div>
      <input name="providerId" type="hidden" />

      <div className="apiProviderFields">
        <label>
          <span>已保存供应商</span>
          <select
            defaultValue=""
            name="savedProvider"
            onChange={(event) =>
              applySavedProviderToForm(event.currentTarget.form, providers)
            }
          >
            <option value="">新建供应商</option>
            {providers.map((provider) => (
              <option key={provider.providerId} value={provider.providerId}>
                {provider.displayName}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>供应商类型</span>
          <select
            defaultValue="openai"
            name="providerType"
            onChange={(event) =>
              applyProviderPresetToForm(event.currentTarget.form)
            }
          >
            {API_PROVIDER_PRESETS.map((preset) => (
              <option key={preset.providerType} value={preset.providerType}>
                {preset.providerType}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>显示名称</span>
          <input
            defaultValue="OpenAI"
            name="displayName"
            type="text"
            autoComplete="off"
          />
        </label>
        <label>
          <span>Base URL</span>
          <input
            defaultValue="https://api.openai.com/v1"
            name="baseUrl"
            type="url"
            autoComplete="off"
          />
        </label>
        <label>
          <span>模型名称</span>
          <input name="model" type="text" autoComplete="off" />
        </label>
        <label>
          <span>API 密钥</span>
          <input
            name="apiKey"
            type="password"
            autoComplete="new-password"
            placeholder="仅用于本次保存或测试"
          />
        </label>
        <label className="apiProviderEnabledToggle">
          <input defaultChecked name="enabled" type="checkbox" />
          <span>启用供应商</span>
        </label>
      </div>

      <div className="apiProviderHelperRow">
        <button className="primaryButton compactButton" type="submit">
          保存
        </button>
        <button
          className="secondaryButton compactButton"
          onClick={(event) =>
            runApiProviderHelper(
              event.currentTarget.form,
              onTestApiProviderConnection,
              false,
            )
          }
          type="button"
        >
          测试连接
        </button>
        <button
          className="secondaryButton compactButton"
          onClick={(event) =>
            runApiProviderHelper(
              event.currentTarget.form,
              onFetchApiProviderModels,
              true,
            )
          }
          type="button"
        >
          拉取模型列表
        </button>
        <select
          aria-label="已拉取模型列表"
          className="apiProviderModelSelect"
          name="fetchedModel"
          onChange={(event) => {
            setFormFieldValue(
              event.currentTarget.form,
              "model",
              event.currentTarget.value,
            );
          }}
        >
          <option value="">尚未拉取模型</option>
        </select>
      </div>
      <output className="apiProviderHelperMessage" name="providerHelperMessage" />
    </form>
  );
}

function readApiProviderPayload(form: ProviderFormLike): SaveApiProviderPayload {
  const payload: SaveApiProviderPayload = {
    providerType: fieldValue(form, "providerType") as ApiProviderType,
    displayName: fieldValue(form, "displayName"),
    baseUrl: fieldValue(form, "baseUrl"),
    model: fieldValue(form, "model"),
    enabled: Boolean(form.elements.namedItem("enabled")?.checked),
  };
  const providerId = fieldValue(form, "providerId");
  const apiKey = fieldValue(form, "apiKey");
  if (providerId) {
    payload.providerId = providerId;
  }
  if (apiKey) {
    payload.apiKey = apiKey;
  }
  return payload;
}

function fieldValue(form: ProviderFormLike | null, name: string): string {
  return form?.elements.namedItem(name)?.value?.trim() ?? "";
}

function setFormFieldValue(
  form: ProviderFormLike | null,
  name: string,
  value: string,
): void {
  const field = form?.elements.namedItem(name);
  if (field) {
    field.value = value;
  }
}

function setFormCheckbox(
  form: ProviderFormLike | null,
  name: string,
  checked: boolean,
): void {
  const field = form?.elements.namedItem(name);
  if (field) {
    field.checked = checked;
  }
}

function applyProviderPresetToForm(form: ProviderFormLike | null): void {
  const providerType = fieldValue(form, "providerType");
  const preset = API_PROVIDER_PRESETS.find(
    (candidate) => candidate.providerType === providerType,
  );
  if (!preset) {
    return;
  }
  setFormFieldValue(form, "providerId", "");
  setFormFieldValue(form, "savedProvider", "");
  setFormFieldValue(form, "displayName", preset.displayName);
  setFormFieldValue(form, "baseUrl", preset.baseUrl);
}

function applySavedProviderToForm(
  form: ProviderFormLike | null,
  providers: ApiProviderConfig[],
): void {
  const providerId = fieldValue(form, "savedProvider");
  if (!providerId) {
    setFormFieldValue(form, "providerId", "");
    applyProviderPresetToForm(form);
    return;
  }
  const provider = providers.find(
    (candidate) => candidate.providerId === providerId,
  );
  if (!provider) {
    return;
  }
  fillApiProviderForm(form, provider);
}

function fillApiProviderFormFromConfig(provider: ApiProviderConfig): void {
  const form = document.getElementById("api-provider-form") as
    | ProviderFormLike
    | null;
  fillApiProviderForm(form, provider);
}

function fillApiProviderForm(
  form: ProviderFormLike | null,
  provider: ApiProviderConfig,
): void {
  setFormFieldValue(form, "providerId", provider.providerId);
  setFormFieldValue(form, "savedProvider", provider.providerId);
  setFormFieldValue(form, "providerType", provider.providerType);
  setFormFieldValue(form, "displayName", provider.displayName);
  setFormFieldValue(form, "baseUrl", provider.baseUrl);
  setFormFieldValue(form, "model", provider.model);
  setFormFieldValue(form, "apiKey", "");
  setFormCheckbox(form, "enabled", provider.enabled);
}

async function runApiProviderHelper(
  form: ProviderFormLike | null,
  handler: (
    payload: SaveApiProviderPayload,
  ) => ApiProviderConnectionResult | Promise<ApiProviderConnectionResult>,
  fillFirstModel: boolean,
): Promise<void> {
  if (!form) {
    return;
  }
  const result = await handler(readApiProviderPayload(form));
  setHelperMessage(form, result.message);
  if (result.models.length > 0) {
    populateFetchedModelSelect(form, result.models);
    if (fillFirstModel && !fieldValue(form, "model")) {
      setFormFieldValue(form, "model", result.models[0]);
    }
  }
}

function setHelperMessage(form: ProviderFormLike, message: string): void {
  const output =
    form.elements.namedItem("providerHelperMessage") ??
    form.querySelector?.("[name='providerHelperMessage']");
  if (output) {
    output.textContent = message;
  }
}

function populateFetchedModelSelect(
  form: ProviderFormLike,
  models: string[],
): void {
  const select = form.elements.namedItem("fetchedModel");
  if (!select) {
    return;
  }
  select.innerHTML = "";
  for (const model of models) {
    const option = document.createElement("option");
    option.value = model;
    option.textContent = model;
    select.appendChild?.(option);
  }
}

function ApiProviderList({
  activeApiProviderId,
  providers,
  onDeleteApiProvider,
  onSetActiveApiProvider,
}: {
  activeApiProviderId: string | null;
  providers: ApiProviderConfig[];
  onDeleteApiProvider(providerId: string): void;
  onSetActiveApiProvider(providerId: string): void;
}) {
  if (providers.length === 0) {
    return (
      <p aria-label="API 供应商" className="preferencesState">
        还没有配置 API 供应商。
      </p>
    );
  }

  return (
    <ul aria-label="API 供应商" className="apiProviderList">
      {providers.map((provider) => {
        const isActive = provider.providerId === activeApiProviderId;

        return (
          <li className="apiProviderItem" key={provider.providerId}>
            <div className="apiProviderHeader">
              <strong>{provider.displayName}</strong>
              {isActive ? (
                <span className="modelDefaultBadge">当前 Agent API</span>
              ) : null}
            </div>
            <span>{provider.model}</span>
            <span>{provider.baseUrl}</span>
            <span>{provider.hasApiKey ? "密钥已配置" : "未配置密钥"}</span>
            <div className="apiProviderActions">
              {!isActive ? (
                <button
                  aria-label={`设为当前 API：${provider.displayName}`}
                  className="secondaryButton compactButton"
                  onClick={() => onSetActiveApiProvider(provider.providerId)}
                  type="button"
                >
                  设为当前 API
                </button>
              ) : null}
              <button
                aria-label={`编辑 API 供应商：${provider.displayName}`}
                className="secondaryButton compactButton"
                onClick={() => fillApiProviderFormFromConfig(provider)}
                type="button"
              >
                编辑
              </button>
              <button
                aria-label={`删除 API 供应商：${provider.displayName}`}
                className="secondaryButton compactButton"
                onClick={() => onDeleteApiProvider(provider.providerId)}
                type="button"
              >
                删除
              </button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function ModelItem({
  agentAssignmentId,
  model,
  onSetModelAssignment,
  speechToTextAssignmentId,
}: {
  agentAssignmentId: string | null;
  model: ModelEntry;
  onSetModelAssignment(role: ModelAssignmentRole, modelId: string): void;
  speechToTextAssignmentId: string | null;
}) {
  const isAgentModel = model.modelKind === "agent_llm";
  const isSpeechToTextModel = model.modelKind === "speech_to_text";
  const isAssignedAgent = isAgentModel && model.modelId === agentAssignmentId;
  const isAssignedSpeechToText =
    isSpeechToTextModel && model.modelId === speechToTextAssignmentId;

  return (
    <li>
      <div className="modelItemHeader">
        <strong>{model.name}</strong>
        {isAssignedAgent ? (
          <span className="modelDefaultBadge">当前 Agent 模型</span>
        ) : null}
        {isAssignedSpeechToText ? (
          <span className="modelDefaultBadge">当前语音转文字模型</span>
        ) : null}
        {isAgentModel && !isAssignedAgent ? (
          <button
            className="secondaryButton compactButton"
            onClick={() => onSetModelAssignment("agentChat", model.modelId)}
            type="button"
          >
            设为 Agent 默认模型
          </button>
        ) : null}
        {isSpeechToTextModel && !isAssignedSpeechToText ? (
          <button
            className="secondaryButton compactButton"
            onClick={() => onSetModelAssignment("speechToText", model.modelId)}
            type="button"
          >
            设为语音转文字模型
          </button>
        ) : null}
      </div>
      <span className="modelMetaLine">{modelKindLabel(model.modelKind)}</span>
      <span className="modelMetaLine">{sourceLabel(model.source)}</span>
      <span className="modelMetaLine">{runtimeLabel(model.runtime)}</span>
      <span className="modelMetaLine">
        {model.fileExists ? model.path : `文件缺失：${model.path}`}
      </span>
    </li>
  );
}

function ToolItem({
  tool,
  onSetToolEnabled,
}: {
  tool: ToolSummary;
  onSetToolEnabled(toolId: string, enabled: boolean): void;
}) {
  return (
    <li className={tool.valid ? "toolItem" : "toolItem toolItemInvalid"}>
      <div>
        <strong>{tool.name}</strong>
        <p>{tool.description}</p>
        <span>版本 {tool.version || "未知"}</span>
        <span>来源 {tool.sourceType || "未知"}</span>
        <span>运行时 {tool.runtime || "未知"}</span>
        <span>许可证 {tool.license || "未知"}</span>
        {tool.packageName ? <span>包 {tool.packageName}</span> : null}
        {tool.capabilities.length > 0 ? (
          <span>能力 {tool.capabilities.join("、")}</span>
        ) : null}
        {tool.permissions.length > 0 ? (
          <span>权限 {tool.permissions.join("、")}</span>
        ) : null}
        {tool.error ? <p className="errorText">{tool.error}</p> : null}
      </div>
      <label className="toolToggle">
        <input
          checked={tool.enabled}
          disabled={!tool.valid}
          onChange={(event) =>
            onSetToolEnabled(tool.toolId, event.target.checked)
          }
          type="checkbox"
        />
        {tool.enabled ? "启用" : "禁用"}
      </label>
    </li>
  );
}

function sourceLabel(source: ModelEntry["source"]): string {
  if (source === "imported") {
    return "模型库";
  }
  if (source === "scan") {
    return "扫描目录";
  }
  return "外部引用";
}

function findModelById(
  models: ModelEntry[] | undefined,
  modelId: string | null,
): ModelEntry | undefined {
  if (!modelId) {
    return undefined;
  }

  return models?.find((model) => model.modelId === modelId);
}

function modelKindLabel(modelKind: ModelEntry["modelKind"]): string {
  return modelKind === "speech_to_text" ? "语音转文字" : "Agent 模型";
}

function runtimeLabel(runtime: ModelEntry["runtime"]): string {
  return runtime === "qwen_asr" ? "Qwen ASR" : "llama.cpp";
}
