type WorkbenchTopBarProps = {
  projectName: string;
  dirty: boolean;
  saving: boolean;
  onSave(): void;
  onSaveAs(): void;
  onOpenPreferences(): void;
};

export function WorkbenchTopBar({
  projectName,
  dirty,
  saving,
  onSave,
  onSaveAs,
  onOpenPreferences,
}: WorkbenchTopBarProps) {
  return (
    <header className="workbenchTopBar">
      <div className="projectIdentity">
        <strong>{projectName}</strong>
        <span className={dirty ? "saveState saveStateDirty" : "saveState"}>
          {saving ? "保存中" : dirty ? "未保存" : "已保存"}
        </span>
      </div>
      <div className="workbenchActions">
        <button
          className="secondaryButton"
          disabled={saving}
          onClick={onSave}
          type="button"
        >
          保存
        </button>
        <button
          className="secondaryButton"
          disabled={saving}
          onClick={onSaveAs}
          type="button"
        >
          另存为
        </button>
        <button
          className="secondaryButton"
          onClick={onOpenPreferences}
          type="button"
        >
          首选项
        </button>
      </div>
    </header>
  );
}
