import type { ModelEntry, ToolSummary } from "../../shared/types";
import type { PreferencesView } from "./preferencesApi";

type PreferencesDialogProps = {
  open: boolean;
  loading: boolean;
  error: string | null;
  view: PreferencesView | null;
  onClose(): void;
  onAddModel(): void;
  onImportModel(): void;
  onScanModelDirectory(): void;
  onSetDefaultModel(modelId: string): void;
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
  onImportModel,
  onScanModelDirectory,
  onSetDefaultModel,
  onSetModelStorageDirectory,
  onSetToolEnabled,
}: PreferencesDialogProps) {
  if (!open) {
    return null;
  }

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
                  <h3>模型</h3>
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

                {view.preferences.models.length > 0 ? (
                  <ul className="modelList">
                    {view.preferences.models.map((model) => (
                      <ModelItem
                        isDefault={
                          model.modelId === view.preferences.defaultModelId
                        }
                        key={model.modelId}
                        model={model}
                        onSetDefaultModel={onSetDefaultModel}
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

function ModelItem({
  isDefault,
  model,
  onSetDefaultModel,
}: {
  isDefault: boolean;
  model: ModelEntry;
  onSetDefaultModel(modelId: string): void;
}) {
  return (
    <li>
      <div className="modelItemHeader">
        <strong>{model.name}</strong>
        {isDefault ? (
          <span className="modelDefaultBadge">默认模型</span>
        ) : (
          <button
            className="secondaryButton compactButton"
            onClick={() => onSetDefaultModel(model.modelId)}
            type="button"
          >
            设为默认
          </button>
        )}
      </div>
      <span>{sourceLabel(model.source)}</span>
      <span>{model.runtime}</span>
      <span>{model.fileExists ? model.path : `文件缺失：${model.path}`}</span>
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
