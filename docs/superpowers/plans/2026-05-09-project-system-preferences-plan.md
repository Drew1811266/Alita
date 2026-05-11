# 工程系统与首选项 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Alita 的 `.alita` 工程文件入口、工作台保存/打开流程，以及全局首选项中的模型管理和工具节点启用状态管理。

**Architecture:** 启动后 React 先显示工程主页；用户通过 Tauri dialog 选择 `.alita` 路径后，由 Rust 负责创建、读取、校验和保存工程 JSON。全局首选项存放在 Tauri app config 目录，Rust 负责持久化、扫描 `.gguf` 模型和汇总工具 manifest，前端只负责呈现和调用 Tauri commands。

**Tech Stack:** Tauri 2, Rust, React 19, TypeScript, Vitest, PowerShell, JSON project files, `@tauri-apps/plugin-dialog`, `tauri-plugin-dialog`, `uuid`, `chrono`.

---

## 文件结构

- 修改：`package.json`
- 修改：`package-lock.json`
- 修改：`src-tauri/Cargo.toml`
- 修改：`src-tauri/src/lib.rs`
- 修改：`src-tauri/src/commands.rs`
- 新建：`src-tauri/capabilities/default.json`
- 新建：`src-tauri/src/project.rs`
- 新建：`src-tauri/src/preferences.rs`
- 新建：`src-tauri/tests/project_tests.rs`
- 新建：`src-tauri/tests/preferences_tests.rs`
- 修改：`src/shared/types.ts`
- 新建：`src/features/project/projectApi.ts`
- 新建：`src/features/project/ProjectHome.tsx`
- 新建：`src/features/project/ProjectHome.test.tsx`
- 新建：`src/features/workbench/WorkbenchTopBar.tsx`
- 新建：`src/features/workbench/WorkbenchTopBar.test.tsx`
- 新建：`src/features/preferences/preferencesApi.ts`
- 新建：`src/features/preferences/PreferencesDialog.tsx`
- 新建：`src/features/preferences/PreferencesDialog.test.tsx`
- 修改：`src/app/App.tsx`
- 修改：`src/app/app.css`
- 修改：`docs/mvp-verification.md`

当前目录不是 git 仓库，所以计划中的每个任务以“检查变更范围”作为交付检查。如果后续初始化 git，可以在每个任务结束后提交一次。

---

## Task 1: 增加依赖和共享类型

**Files:**
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `src-tauri/Cargo.toml`
- Modify: `src/shared/types.ts`

- [ ] **Step 1: 安装前端 dialog 插件**

Run:

```powershell
npm install @tauri-apps/plugin-dialog@2
```

Expected: `package.json` 和 `package-lock.json` 增加 `@tauri-apps/plugin-dialog`。

- [ ] **Step 2: 增加 Rust 依赖**

在 `src-tauri/Cargo.toml` 的 `[dependencies]` 中加入：

```toml
chrono = { version = "0.4", features = ["serde"] }
tauri-plugin-dialog = "2"
uuid = { version = "1", features = ["v4", "serde"] }
```

这些依赖分别用于 ISO 时间戳、系统文件选择框插件、工程和模型 id。

- [ ] **Step 3: 扩展共享 TypeScript 类型**

在 `src/shared/types.ts` 追加工程和首选项类型：

```ts
export type ProjectAttachmentRef = ChatAttachment & {
  originalPath: string;
  fileExists: boolean;
};

export type ToolSnapshotEntry = {
  toolId: string;
  name: string;
  version: string;
  enabled: boolean;
};

export type RunHistoryEntry = {
  runId: string;
  startedAt: string;
  completedAt?: string;
  status: "completed" | "failed" | "cancelled";
  summary: string;
};

export type AlitaProject = {
  schemaVersion: 1;
  projectId: string;
  name: string;
  path: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
  graph: NodeGraph | null;
  attachments: ProjectAttachmentRef[];
  modelRef: string | null;
  toolSnapshot: ToolSnapshotEntry[];
  runHistory: RunHistoryEntry[];
};

export type ProjectOpenWarning = {
  code: "missing_attachment";
  message: string;
  path: string;
};

export type ProjectOpenResult = {
  project: AlitaProject;
  warnings: ProjectOpenWarning[];
};

export type ModelSource = "manual" | "scan";

export type ModelEntry = {
  modelId: string;
  name: string;
  path: string;
  source: ModelSource;
  runtime: "llama_cpp";
  fileExists: boolean;
  createdAt: string;
  updatedAt: string;
};

export type ToolSummary = {
  toolId: string;
  name: string;
  description: string;
  version: string;
  sourceType: string;
  license: string;
  permissions: string[];
  enabled: boolean;
  valid: boolean;
  error?: string;
};

export type AppPreferences = {
  schemaVersion: 1;
  recentProjects: string[];
  modelDirectories: string[];
  models: ModelEntry[];
  defaultModelId: string | null;
  toolEnablement: Record<string, boolean>;
};
```

- [ ] **Step 4: 运行前端类型检查**

Run:

```powershell
npm run frontend:lint
```

Expected: PASS。

---

## Task 2: Rust 工程文件领域模型

**Files:**
- Create: `src-tauri/src/project.rs`
- Create: `src-tauri/tests/project_tests.rs`
- Modify: `src-tauri/src/lib.rs`

- [ ] **Step 1: 写失败测试**

Create `src-tauri/tests/project_tests.rs`:

```rust
use alita_lib::project::{
    load_project_from_path, new_project, save_project_to_path, ProjectFileError,
};
use std::fs;

#[test]
fn new_project_uses_schema_version_one_and_empty_state() {
    let project = new_project("文档整理测试", "D:\\Projects\\文档整理测试.alita");

    assert_eq!(project.schema_version, 1);
    assert_eq!(project.name, "文档整理测试");
    assert!(project.messages.is_empty());
    assert!(project.graph.is_none());
    assert!(project.attachments.is_empty());
    assert!(project.model_ref.is_none());
}

#[test]
fn saves_and_loads_project_json() {
    let temp_dir = tempfile::tempdir().unwrap();
    let project_path = temp_dir.path().join("demo.alita");
    let mut project = new_project("Demo", project_path.to_string_lossy().as_ref());
    project.messages.push(serde_json::json!({
        "messageId": "message-1",
        "role": "system",
        "content": "工程已创建。",
        "attachments": [],
        "createdAt": "2026-05-09T12:00:00.000Z"
    }));

    save_project_to_path(&project_path, &project).unwrap();
    let result = load_project_from_path(&project_path).unwrap();

    assert_eq!(result.project.name, "Demo");
    assert_eq!(result.project.messages.len(), 1);
    assert!(result.warnings.is_empty());
}

#[test]
fn rejects_invalid_json_project_file() {
    let temp_dir = tempfile::tempdir().unwrap();
    let project_path = temp_dir.path().join("broken.alita");
    fs::write(&project_path, "{ invalid json").unwrap();

    let error = load_project_from_path(&project_path).unwrap_err();

    assert!(matches!(error, ProjectFileError::InvalidJson { .. }));
}

#[test]
fn rejects_unsupported_schema_version() {
    let temp_dir = tempfile::tempdir().unwrap();
    let project_path = temp_dir.path().join("future.alita");
    fs::write(
        &project_path,
        r#"{"schemaVersion":99,"projectId":"x","name":"Future","createdAt":"2026-05-09T12:00:00.000Z","updatedAt":"2026-05-09T12:00:00.000Z","messages":[],"graph":null,"attachments":[],"modelRef":null,"toolSnapshot":[],"runHistory":[]}"#,
    )
    .unwrap();

    let error = load_project_from_path(&project_path).unwrap_err();

    assert!(matches!(error, ProjectFileError::UnsupportedSchema { version: 99 }));
}
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
cd src-tauri
cargo test --test project_tests
cd ..
```

Expected: FAIL，原因是 `project` module 和函数不存在。

- [ ] **Step 3: 实现 `project.rs`**

Create `src-tauri/src/project.rs`:

```rust
use chrono::Utc;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{fs, io, path::Path};
use uuid::Uuid;

const PROJECT_SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct AlitaProject {
    pub schema_version: u32,
    pub project_id: String,
    pub name: String,
    pub path: String,
    pub created_at: String,
    pub updated_at: String,
    pub messages: Vec<Value>,
    pub graph: Option<Value>,
    pub attachments: Vec<ProjectAttachmentRef>,
    pub model_ref: Option<String>,
    pub tool_snapshot: Vec<ToolSnapshotEntry>,
    pub run_history: Vec<RunHistoryEntry>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ProjectAttachmentRef {
    pub attachment_id: String,
    pub name: String,
    pub path: String,
    pub original_path: String,
    pub size_bytes: u64,
    pub mime_type: String,
    pub file_exists: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ToolSnapshotEntry {
    pub tool_id: String,
    pub name: String,
    pub version: String,
    pub enabled: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct RunHistoryEntry {
    pub run_id: String,
    pub started_at: String,
    pub completed_at: Option<String>,
    pub status: String,
    pub summary: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ProjectOpenWarning {
    pub code: String,
    pub message: String,
    pub path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ProjectOpenResult {
    pub project: AlitaProject,
    pub warnings: Vec<ProjectOpenWarning>,
}

#[derive(Debug)]
pub enum ProjectFileError {
    Io { message: String },
    InvalidJson { message: String },
    UnsupportedSchema { version: u32 },
}

impl std::fmt::Display for ProjectFileError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io { message } => write!(formatter, "{message}"),
            Self::InvalidJson { message } => write!(formatter, "{message}"),
            Self::UnsupportedSchema { version } => {
                write!(formatter, "unsupported .alita schema version: {version}")
            }
        }
    }
}

impl std::error::Error for ProjectFileError {}

pub fn new_project(name: &str, path: &str) -> AlitaProject {
    let now = Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true);

    AlitaProject {
        schema_version: PROJECT_SCHEMA_VERSION,
        project_id: Uuid::new_v4().to_string(),
        name: name.trim().to_string(),
        path: path.to_string(),
        created_at: now.clone(),
        updated_at: now,
        messages: Vec::new(),
        graph: None,
        attachments: Vec::new(),
        model_ref: None,
        tool_snapshot: Vec::new(),
        run_history: Vec::new(),
    }
}

pub fn load_project_from_path(path: impl AsRef<Path>) -> Result<ProjectOpenResult, ProjectFileError> {
    let path = path.as_ref();
    let contents = fs::read_to_string(path).map_err(io_error)?;
    let mut project: AlitaProject =
        serde_json::from_str(&contents).map_err(|error| ProjectFileError::InvalidJson {
            message: format!("failed to parse .alita file '{}': {error}", path.display()),
        })?;

    if project.schema_version != PROJECT_SCHEMA_VERSION {
        return Err(ProjectFileError::UnsupportedSchema {
            version: project.schema_version,
        });
    }

    project.path = path.to_string_lossy().into_owned();
    let warnings = collect_missing_attachment_warnings(&mut project);

    Ok(ProjectOpenResult { project, warnings })
}

pub fn save_project_to_path(
    path: impl AsRef<Path>,
    project: &AlitaProject,
) -> Result<(), ProjectFileError> {
    let path = path.as_ref();
    let mut project_to_save = project.clone();
    project_to_save.path = path.to_string_lossy().into_owned();
    project_to_save.updated_at = Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true);

    let serialized = serde_json::to_string_pretty(&project_to_save).map_err(|error| {
        ProjectFileError::InvalidJson {
            message: format!("failed to serialize project '{}': {error}", project_to_save.name),
        }
    })?;

    let temp_path = path.with_extension("alita.tmp");
    fs::write(&temp_path, serialized).map_err(io_error)?;
    fs::rename(&temp_path, path).map_err(io_error)?;
    Ok(())
}

fn collect_missing_attachment_warnings(project: &mut AlitaProject) -> Vec<ProjectOpenWarning> {
    let mut warnings = Vec::new();
    for attachment in &mut project.attachments {
        let exists = Path::new(&attachment.path).exists();
        attachment.file_exists = exists;
        if !exists {
            warnings.push(ProjectOpenWarning {
                code: "missing_attachment".to_string(),
                message: format!("引用文件不存在：{}", attachment.path),
                path: attachment.path.clone(),
            });
        }
    }
    warnings
}

fn io_error(error: io::Error) -> ProjectFileError {
    ProjectFileError::Io {
        message: error.to_string(),
    }
}
```

- [ ] **Step 4: 注册 module**

在 `src-tauri/src/lib.rs` 顶部加入：

```rust
pub mod project;
```

- [ ] **Step 5: 运行测试确认通过**

Run:

```powershell
cd src-tauri
cargo test --test project_tests
cd ..
```

Expected: PASS。

---

## Task 3: Rust 首选项、模型扫描和工具摘要

**Files:**
- Create: `src-tauri/src/preferences.rs`
- Create: `src-tauri/tests/preferences_tests.rs`
- Modify: `src-tauri/src/lib.rs`

- [ ] **Step 1: 写失败测试**

Create `src-tauri/tests/preferences_tests.rs`:

```rust
use alita_lib::preferences::{
    add_manual_model, load_preferences_from_path, record_recent_project, save_preferences_to_path,
    scan_model_directory, summarize_tool_manifests, tool_enabled, AppPreferences,
};
use std::fs;

#[test]
fn default_preferences_have_schema_version_one() {
    let preferences = AppPreferences::default();

    assert_eq!(preferences.schema_version, 1);
    assert!(preferences.recent_projects.is_empty());
    assert!(preferences.models.is_empty());
    assert!(preferences.model_directories.is_empty());
    assert!(preferences.default_model_id.is_none());
}

#[test]
fn saves_and_loads_preferences() {
    let temp_dir = tempfile::tempdir().unwrap();
    let preferences_path = temp_dir.path().join("preferences.json");
    let mut preferences = AppPreferences::default();
    preferences.model_directories.push("D:\\Models".to_string());

    save_preferences_to_path(&preferences_path, &preferences).unwrap();
    let loaded = load_preferences_from_path(&preferences_path).unwrap();

    assert_eq!(loaded.model_directories, vec!["D:\\Models"]);
}

#[test]
fn adding_manual_model_deduplicates_by_path() {
    let temp_dir = tempfile::tempdir().unwrap();
    let model_path = temp_dir.path().join("qwen.gguf");
    fs::write(&model_path, "model").unwrap();
    let mut preferences = AppPreferences::default();

    add_manual_model(&mut preferences, &model_path).unwrap();
    add_manual_model(&mut preferences, &model_path).unwrap();

    assert_eq!(preferences.models.len(), 1);
    assert_eq!(preferences.models[0].source, "manual");
    assert!(preferences.models[0].file_exists);
}

#[test]
fn scan_model_directory_adds_gguf_files_only() {
    let temp_dir = tempfile::tempdir().unwrap();
    fs::write(temp_dir.path().join("qwen.gguf"), "model").unwrap();
    fs::write(temp_dir.path().join("notes.txt"), "ignored").unwrap();
    let mut preferences = AppPreferences::default();

    let added = scan_model_directory(&mut preferences, temp_dir.path()).unwrap();

    assert_eq!(added, 1);
    assert_eq!(preferences.models.len(), 1);
    assert_eq!(preferences.models[0].source, "scan");
}

#[test]
fn builtin_manifest_tools_default_to_enabled() {
    let summaries = summarize_tool_manifests("../tool-packages", &AppPreferences::default());

    let document_tool = summaries
        .iter()
        .find(|tool| tool.tool_id == "document.read_write")
        .expect("document tool should be listed");

    assert!(document_tool.enabled);
    assert!(document_tool.valid);
}

#[test]
fn explicit_tool_enablement_overrides_default() {
    let mut preferences = AppPreferences::default();
    preferences
        .tool_enablement
        .insert("document.read_write".to_string(), false);

    assert!(!tool_enabled("document.read_write", &preferences));
}

#[test]
fn records_recent_projects_without_duplicates() {
    let mut preferences = AppPreferences::default();

    record_recent_project(&mut preferences, "D:\\Projects\\A.alita");
    record_recent_project(&mut preferences, "D:\\Projects\\B.alita");
    record_recent_project(&mut preferences, "D:\\Projects\\A.alita");

    assert_eq!(
        preferences.recent_projects,
        vec![
            "D:\\Projects\\A.alita".to_string(),
            "D:\\Projects\\B.alita".to_string()
        ]
    );
}
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
cd src-tauri
cargo test --test preferences_tests
cd ..
```

Expected: FAIL，原因是 `preferences` module 不存在。

- [ ] **Step 3: 实现 `preferences.rs`**

Create `src-tauri/src/preferences.rs`:

```rust
use crate::tools::ToolManifest;
use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::{collections::HashMap, fs, path::Path};
use uuid::Uuid;

const PREFERENCES_SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct AppPreferences {
    pub schema_version: u32,
    pub recent_projects: Vec<String>,
    pub model_directories: Vec<String>,
    pub models: Vec<ModelEntry>,
    pub default_model_id: Option<String>,
    pub tool_enablement: HashMap<String, bool>,
}

impl Default for AppPreferences {
    fn default() -> Self {
        Self {
            schema_version: PREFERENCES_SCHEMA_VERSION,
            recent_projects: Vec::new(),
            model_directories: Vec::new(),
            models: Vec::new(),
            default_model_id: None,
            tool_enablement: HashMap::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ModelEntry {
    pub model_id: String,
    pub name: String,
    pub path: String,
    pub source: String,
    pub runtime: String,
    pub file_exists: bool,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ToolSummary {
    pub tool_id: String,
    pub name: String,
    pub description: String,
    pub version: String,
    pub source_type: String,
    pub license: String,
    pub permissions: Vec<String>,
    pub enabled: bool,
    pub valid: bool,
    pub error: Option<String>,
}

pub fn load_preferences_from_path(path: impl AsRef<Path>) -> Result<AppPreferences, String> {
    let path = path.as_ref();
    if !path.exists() {
        return Ok(AppPreferences::default());
    }

    let contents = fs::read_to_string(path)
        .map_err(|error| format!("failed to read preferences '{}': {error}", path.display()))?;
    let preferences: AppPreferences = serde_json::from_str(&contents)
        .map_err(|error| format!("failed to parse preferences '{}': {error}", path.display()))?;

    if preferences.schema_version != PREFERENCES_SCHEMA_VERSION {
        return Err(format!(
            "unsupported preferences schema version: {}",
            preferences.schema_version
        ));
    }

    Ok(preferences)
}

pub fn save_preferences_to_path(
    path: impl AsRef<Path>,
    preferences: &AppPreferences,
) -> Result<(), String> {
    let path = path.as_ref();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| {
            format!("failed to create preferences directory '{}': {error}", parent.display())
        })?;
    }

    let serialized = serde_json::to_string_pretty(preferences)
        .map_err(|error| format!("failed to serialize preferences: {error}"))?;
    let temp_path = path.with_extension("json.tmp");
    fs::write(&temp_path, serialized)
        .map_err(|error| format!("failed to write preferences temp file: {error}"))?;
    fs::rename(&temp_path, path)
        .map_err(|error| format!("failed to replace preferences file: {error}"))?;
    Ok(())
}

pub fn add_manual_model(
    preferences: &mut AppPreferences,
    path: impl AsRef<Path>,
) -> Result<ModelEntry, String> {
    add_or_update_model(preferences, path.as_ref(), "manual")
}

pub fn scan_model_directory(
    preferences: &mut AppPreferences,
    directory: impl AsRef<Path>,
) -> Result<usize, String> {
    let directory = directory.as_ref();
    if !directory.is_dir() {
        return Err(format!("model directory is not accessible: {}", directory.display()));
    }

    let directory_text = directory.to_string_lossy().into_owned();
    if !preferences.model_directories.contains(&directory_text) {
        preferences.model_directories.push(directory_text);
    }

    let mut count = 0;
    for entry in fs::read_dir(directory)
        .map_err(|error| format!("failed to scan model directory '{}': {error}", directory.display()))?
    {
        let entry = entry.map_err(|error| format!("failed to read model directory entry: {error}"))?;
        let path = entry.path();
        let is_gguf = path
            .extension()
            .and_then(|extension| extension.to_str())
            .is_some_and(|extension| extension.eq_ignore_ascii_case("gguf"));
        if is_gguf {
            add_or_update_model(preferences, &path, "scan")?;
            count += 1;
        }
    }
    Ok(count)
}

pub fn summarize_tool_manifests(
    packages_root: impl AsRef<Path>,
    preferences: &AppPreferences,
) -> Vec<ToolSummary> {
    let packages_root = packages_root.as_ref();
    let mut summaries = Vec::new();
    let Ok(entries) = fs::read_dir(packages_root) else {
        return summaries;
    };

    for entry in entries.flatten() {
        let manifest_path = entry.path().join("manifest.json");
        if !manifest_path.exists() {
            continue;
        }

        match ToolManifest::from_path(&manifest_path) {
            Ok(manifest) => summaries.push(ToolSummary {
                enabled: tool_enabled(&manifest.tool_id, preferences),
                tool_id: manifest.tool_id,
                name: manifest.name,
                description: manifest.description,
                version: manifest.version,
                source_type: manifest.source_type,
                license: manifest.license,
                permissions: manifest.permissions,
                valid: true,
                error: None,
            }),
            Err(error) => summaries.push(ToolSummary {
                tool_id: manifest_path.to_string_lossy().into_owned(),
                name: "无效工具 manifest".to_string(),
                description: "该工具 manifest 无法被解析。".to_string(),
                version: "".to_string(),
                source_type: "".to_string(),
                license: "".to_string(),
                permissions: Vec::new(),
                enabled: false,
                valid: false,
                error: Some(error),
            }),
        }
    }

    summaries.sort_by(|left, right| left.name.cmp(&right.name));
    summaries
}

pub fn tool_enabled(tool_id: &str, preferences: &AppPreferences) -> bool {
    preferences.tool_enablement.get(tool_id).copied().unwrap_or(true)
}

pub fn record_recent_project(preferences: &mut AppPreferences, project_path: &str) {
    preferences
        .recent_projects
        .retain(|existing| existing != project_path);
    preferences.recent_projects.insert(0, project_path.to_string());
    preferences.recent_projects.truncate(8);
}

fn add_or_update_model(
    preferences: &mut AppPreferences,
    path: &Path,
    source: &str,
) -> Result<ModelEntry, String> {
    let path_text = path.to_string_lossy().into_owned();
    let now = Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true);
    let name = path
        .file_stem()
        .and_then(|name| name.to_str())
        .unwrap_or("未命名模型")
        .to_string();
    let file_exists = path.exists();

    if let Some(existing) = preferences.models.iter_mut().find(|model| model.path == path_text) {
        existing.name = name;
        existing.source = source.to_string();
        existing.file_exists = file_exists;
        existing.updated_at = now;
        return Ok(existing.clone());
    }

    let entry = ModelEntry {
        model_id: Uuid::new_v4().to_string(),
        name,
        path: path_text,
        source: source.to_string(),
        runtime: "llama_cpp".to_string(),
        file_exists,
        created_at: now.clone(),
        updated_at: now,
    };
    preferences.models.push(entry.clone());
    Ok(entry)
}
```

- [ ] **Step 4: 注册 module**

在 `src-tauri/src/lib.rs` 顶部加入：

```rust
pub mod preferences;
```

- [ ] **Step 5: 运行测试确认通过**

Run:

```powershell
cd src-tauri
cargo test --test preferences_tests
cd ..
```

Expected: PASS。

---

## Task 4: 暴露 Tauri commands 和 dialog 插件

**Files:**
- Modify: `src-tauri/src/commands.rs`
- Modify: `src-tauri/src/lib.rs`
- Create: `src-tauri/capabilities/default.json`

- [ ] **Step 1: 扩展 commands**

在 `src-tauri/src/commands.rs` 追加以下 payload 和 command。保留现有 `submit_user_message`。

```rust
use crate::{
    preferences::{
        add_manual_model, load_preferences_from_path, record_recent_project,
        save_preferences_to_path, scan_model_directory, summarize_tool_manifests, AppPreferences,
        ModelEntry, ToolSummary,
    },
    project::{
        load_project_from_path, new_project, save_project_to_path, AlitaProject, ProjectOpenResult,
    },
};
use std::path::PathBuf;
use tauri::{AppHandle, Manager};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CreateProjectPayload {
    pub path: String,
    pub name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SaveProjectPayload {
    pub path: String,
    pub project: AlitaProject,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AddModelPayload {
    pub path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ScanModelDirectoryPayload {
    pub path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SetToolEnabledPayload {
    pub tool_id: String,
    pub enabled: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PreferencesView {
    pub preferences: AppPreferences,
    pub tools: Vec<ToolSummary>,
}

#[tauri::command]
pub async fn create_project(
    app: AppHandle,
    payload: CreateProjectPayload,
) -> Result<ProjectOpenResult, String> {
    let project = new_project(&payload.name, &payload.path);
    save_project_to_path(&payload.path, &project).map_err(|error| error.to_string())?;
    record_recent_project_for_app(&app, &payload.path)?;
    load_project_from_path(&payload.path).map_err(|error| error.to_string())
}

#[tauri::command]
pub async fn open_project(app: AppHandle, path: String) -> Result<ProjectOpenResult, String> {
    record_recent_project_for_app(&app, &path)?;
    load_project_from_path(path).map_err(|error| error.to_string())
}

#[tauri::command]
pub async fn save_project(
    app: AppHandle,
    payload: SaveProjectPayload,
) -> Result<ProjectOpenResult, String> {
    save_project_to_path(&payload.path, &payload.project).map_err(|error| error.to_string())?;
    record_recent_project_for_app(&app, &payload.path)?;
    load_project_from_path(&payload.path).map_err(|error| error.to_string())
}

#[tauri::command]
pub async fn get_preferences(app: AppHandle) -> Result<PreferencesView, String> {
    let path = preferences_path(&app)?;
    let preferences = load_preferences_from_path(&path)?;
    let tools = summarize_tool_manifests(packages_root()?, &preferences);
    Ok(PreferencesView { preferences, tools })
}

#[tauri::command]
pub async fn add_model_file(app: AppHandle, payload: AddModelPayload) -> Result<PreferencesView, String> {
    let path = preferences_path(&app)?;
    let mut preferences = load_preferences_from_path(&path)?;
    add_manual_model(&mut preferences, PathBuf::from(payload.path))?;
    save_preferences_to_path(&path, &preferences)?;
    let tools = summarize_tool_manifests(packages_root()?, &preferences);
    Ok(PreferencesView { preferences, tools })
}

#[tauri::command]
pub async fn scan_model_directory_command(
    app: AppHandle,
    payload: ScanModelDirectoryPayload,
) -> Result<PreferencesView, String> {
    let path = preferences_path(&app)?;
    let mut preferences = load_preferences_from_path(&path)?;
    scan_model_directory(&mut preferences, PathBuf::from(payload.path))?;
    save_preferences_to_path(&path, &preferences)?;
    let tools = summarize_tool_manifests(packages_root()?, &preferences);
    Ok(PreferencesView { preferences, tools })
}

#[tauri::command]
pub async fn set_tool_enabled(
    app: AppHandle,
    payload: SetToolEnabledPayload,
) -> Result<PreferencesView, String> {
    let path = preferences_path(&app)?;
    let mut preferences = load_preferences_from_path(&path)?;
    preferences.tool_enablement.insert(payload.tool_id, payload.enabled);
    save_preferences_to_path(&path, &preferences)?;
    let tools = summarize_tool_manifests(packages_root()?, &preferences);
    Ok(PreferencesView { preferences, tools })
}

fn preferences_path(app: &AppHandle) -> Result<PathBuf, String> {
    let config_dir = app
        .path()
        .app_config_dir()
        .map_err(|error| format!("failed to resolve app config dir: {error}"))?;
    Ok(config_dir.join("preferences.json"))
}

fn packages_root() -> Result<PathBuf, String> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    Ok(manifest_dir.join("..").join("tool-packages"))
}

fn record_recent_project_for_app(app: &AppHandle, project_path: &str) -> Result<(), String> {
    let path = preferences_path(app)?;
    let mut preferences = load_preferences_from_path(&path)?;
    record_recent_project(&mut preferences, project_path);
    save_preferences_to_path(&path, &preferences)
}
```

如果 `commands.rs` 因重复 import 产生冲突，整理文件顶部 import，保持每个类型只 import 一次。

- [ ] **Step 2: 注册插件和 commands**

在 `src-tauri/src/lib.rs` 的 builder 中加入 dialog 插件：

```rust
.plugin(tauri_plugin_dialog::init())
```

把 invoke handler 改成：

```rust
.invoke_handler(tauri::generate_handler![
    commands::submit_user_message,
    commands::create_project,
    commands::open_project,
    commands::save_project,
    commands::get_preferences,
    commands::add_model_file,
    commands::scan_model_directory_command,
    commands::set_tool_enabled
])
```

- [ ] **Step 3: 增加 dialog 权限**

Create `src-tauri/capabilities/default.json`:

```json
{
  "$schema": "../gen/schemas/desktop-schema.json",
  "identifier": "default",
  "description": "Main window permissions",
  "windows": ["main"],
  "permissions": [
    "core:default",
    "dialog:default",
    "dialog:allow-open",
    "dialog:allow-save"
  ]
}
```

- [ ] **Step 4: 运行 Rust 测试**

Run:

```powershell
cd src-tauri
cargo test
cd ..
```

Expected: PASS。

---

## Task 5: 前端工程 API 和工程主页

**Files:**
- Create: `src/features/project/projectApi.ts`
- Create: `src/features/project/ProjectHome.tsx`
- Create: `src/features/project/ProjectHome.test.tsx`

- [ ] **Step 1: 新建工程 API**

Create `src/features/project/projectApi.ts`:

```ts
import { invoke } from "@tauri-apps/api/core";
import { open, save } from "@tauri-apps/plugin-dialog";

import type { AlitaProject, ProjectOpenResult } from "../../shared/types";

export async function pickCreateProjectPath(): Promise<string | null> {
  if (!isTauriRuntime()) {
    return window.prompt("输入要创建的 .alita 文件路径");
  }

  const selected = await save({
    defaultPath: "未命名工程.alita",
    filters: [{ name: "Alita 工程", extensions: ["alita"] }],
  });
  return typeof selected === "string" ? selected : null;
}

export async function pickOpenProjectPath(): Promise<string | null> {
  if (!isTauriRuntime()) {
    return window.prompt("输入要打开的 .alita 文件路径");
  }

  const selected = await open({
    multiple: false,
    directory: false,
    filters: [{ name: "Alita 工程", extensions: ["alita"] }],
  });
  return typeof selected === "string" ? selected : null;
}

export async function pickSaveProjectAsPath(
  currentPath: string,
): Promise<string | null> {
  if (!isTauriRuntime()) {
    return window.prompt("输入另存为 .alita 文件路径", currentPath);
  }

  const selected = await save({
    defaultPath: currentPath,
    filters: [{ name: "Alita 工程", extensions: ["alita"] }],
  });
  return typeof selected === "string" ? selected : null;
}

export async function createProject(
  path: string,
  name: string,
): Promise<ProjectOpenResult> {
  return invoke<ProjectOpenResult>("create_project", {
    payload: { path, name },
  });
}

export async function openProject(path: string): Promise<ProjectOpenResult> {
  return invoke<ProjectOpenResult>("open_project", { path });
}

export async function saveProject(
  project: AlitaProject,
  path = project.path,
): Promise<ProjectOpenResult> {
  return invoke<ProjectOpenResult>("save_project", {
    payload: { path, project: { ...project, path } },
  });
}

function isTauriRuntime(): boolean {
  return "__TAURI_INTERNALS__" in window;
}
```

- [ ] **Step 2: 新建工程主页组件测试**

Create `src/features/project/ProjectHome.test.tsx`:

```tsx
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ProjectHome } from "./ProjectHome";

describe("ProjectHome", () => {
  it("renders project actions and preferences entry", () => {
    const markup = renderToStaticMarkup(
      <ProjectHome
        error={null}
        onCreateProject={() => undefined}
        onOpenProject={() => undefined}
        onOpenPreferences={() => undefined}
        recentProjects={["D:\\Projects\\文档整理测试.alita"]}
      />,
    );

    expect(markup).toContain("Alita");
    expect(markup).toContain("新建工程");
    expect(markup).toContain("打开工程");
    expect(markup).toContain("最近工程");
    expect(markup).toContain("首选项");
    expect(markup).toContain("文档整理测试.alita");
  });
});
```

- [ ] **Step 3: 实现 `ProjectHome.tsx`**

Create `src/features/project/ProjectHome.tsx`:

```tsx
type ProjectHomeProps = {
  recentProjects: string[];
  error: string | null;
  onCreateProject(): void;
  onOpenProject(): void;
  onOpenPreferences(): void;
};

export function ProjectHome({
  recentProjects,
  error,
  onCreateProject,
  onOpenProject,
  onOpenPreferences,
}: ProjectHomeProps) {
  return (
    <main className="projectHome" aria-labelledby="project-home-title">
      <header className="projectHomeHeader">
        <div>
          <h1 id="project-home-title">Alita</h1>
          <p>创建或打开工程后进入 Agent 节点工作台。</p>
        </div>
        <button className="secondaryButton" onClick={onOpenPreferences} type="button">
          首选项
        </button>
      </header>

      <section className="projectHomeGrid">
        <div className="projectStartPanel">
          <h2>开始</h2>
          <button className="primaryButton" onClick={onCreateProject} type="button">
            新建工程
          </button>
          <button className="secondaryButton" onClick={onOpenProject} type="button">
            打开工程
          </button>
          {error ? <p className="errorText">{error}</p> : null}
        </div>

        <div className="recentProjectsPanel">
          <h2>最近工程</h2>
          {recentProjects.length > 0 ? (
            <ul>
              {recentProjects.map((projectPath) => (
                <li key={projectPath}>{projectPath}</li>
              ))}
            </ul>
          ) : (
            <p>还没有最近工程。</p>
          )}
        </div>
      </section>
    </main>
  );
}
```

- [ ] **Step 4: 运行前端测试**

Run:

```powershell
npm run frontend:test -- ProjectHome
```

Expected: PASS。

---

## Task 6: 工作台顶部栏和保存状态

**Files:**
- Create: `src/features/workbench/WorkbenchTopBar.tsx`
- Create: `src/features/workbench/WorkbenchTopBar.test.tsx`

- [ ] **Step 1: 写顶部栏测试**

Create `src/features/workbench/WorkbenchTopBar.test.tsx`:

```tsx
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { WorkbenchTopBar } from "./WorkbenchTopBar";

describe("WorkbenchTopBar", () => {
  it("renders project name, dirty state, and actions", () => {
    const markup = renderToStaticMarkup(
      <WorkbenchTopBar
        projectName="文档整理测试"
        dirty
        saving={false}
        onSave={() => undefined}
        onSaveAs={() => undefined}
        onOpenPreferences={() => undefined}
      />,
    );

    expect(markup).toContain("文档整理测试");
    expect(markup).toContain("未保存");
    expect(markup).toContain("保存");
    expect(markup).toContain("另存为");
    expect(markup).toContain("首选项");
  });
});
```

- [ ] **Step 2: 实现顶部栏组件**

Create `src/features/workbench/WorkbenchTopBar.tsx`:

```tsx
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
        <button className="secondaryButton" disabled={saving} onClick={onSave} type="button">
          保存
        </button>
        <button className="secondaryButton" disabled={saving} onClick={onSaveAs} type="button">
          另存为
        </button>
        <button className="secondaryButton" onClick={onOpenPreferences} type="button">
          首选项
        </button>
      </div>
    </header>
  );
}
```

- [ ] **Step 3: 运行测试**

Run:

```powershell
npm run frontend:test -- WorkbenchTopBar
```

Expected: PASS。

---

## Task 7: 首选项 API 和首选项界面

**Files:**
- Create: `src/features/preferences/preferencesApi.ts`
- Create: `src/features/preferences/PreferencesDialog.tsx`
- Create: `src/features/preferences/PreferencesDialog.test.tsx`

- [ ] **Step 1: 新建首选项 API**

Create `src/features/preferences/preferencesApi.ts`:

```ts
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";

import type { AppPreferences, ToolSummary } from "../../shared/types";

export type PreferencesView = {
  preferences: AppPreferences;
  tools: ToolSummary[];
};

export async function getPreferences(): Promise<PreferencesView> {
  return invoke<PreferencesView>("get_preferences");
}

export async function pickModelFile(): Promise<string | null> {
  if (!isTauriRuntime()) {
    return window.prompt("输入 GGUF 模型文件路径");
  }

  const selected = await open({
    multiple: false,
    directory: false,
    filters: [{ name: "GGUF 模型", extensions: ["gguf"] }],
  });
  return typeof selected === "string" ? selected : null;
}

export async function pickModelDirectory(): Promise<string | null> {
  if (!isTauriRuntime()) {
    return window.prompt("输入模型目录路径");
  }

  const selected = await open({
    multiple: false,
    directory: true,
  });
  return typeof selected === "string" ? selected : null;
}

export async function addModelFile(path: string): Promise<PreferencesView> {
  return invoke<PreferencesView>("add_model_file", { payload: { path } });
}

export async function scanModelDirectory(path: string): Promise<PreferencesView> {
  return invoke<PreferencesView>("scan_model_directory_command", {
    payload: { path },
  });
}

export async function setToolEnabled(
  toolId: string,
  enabled: boolean,
): Promise<PreferencesView> {
  return invoke<PreferencesView>("set_tool_enabled", {
    payload: { toolId, enabled },
  });
}

function isTauriRuntime(): boolean {
  return "__TAURI_INTERNALS__" in window;
}
```

- [ ] **Step 2: 写首选项界面测试**

Create `src/features/preferences/PreferencesDialog.test.tsx`:

```tsx
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PreferencesDialog } from "./PreferencesDialog";
import type { PreferencesView } from "./preferencesApi";

const view: PreferencesView = {
  preferences: {
    schemaVersion: 1,
    recentProjects: [],
    modelDirectories: ["D:\\Models"],
    defaultModelId: null,
    models: [
      {
        modelId: "model-1",
        name: "qwen3-8b",
        path: "D:\\Models\\qwen3-8b.gguf",
        source: "manual",
        runtime: "llama_cpp",
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
      permissions: ["read_project_files"],
      enabled: true,
      valid: true,
    },
  ],
};

describe("PreferencesDialog", () => {
  it("renders model and tool management sections", () => {
    const markup = renderToStaticMarkup(
      <PreferencesDialog
        open
        loading={false}
        error={null}
        view={view}
        onClose={() => undefined}
        onAddModel={() => undefined}
        onScanModelDirectory={() => undefined}
        onSetToolEnabled={() => undefined}
      />,
    );

    expect(markup).toContain("首选项");
    expect(markup).toContain("模型");
    expect(markup).toContain("添加 GGUF 模型");
    expect(markup).toContain("扫描模型目录");
    expect(markup).toContain("qwen3-8b");
    expect(markup).toContain("工具节点");
    expect(markup).toContain("文档处理工具包");
    expect(markup).toContain("启用");
  });
});
```

- [ ] **Step 3: 实现首选项组件**

Create `src/features/preferences/PreferencesDialog.tsx`:

```tsx
import type { ToolSummary } from "../../shared/types";
import type { PreferencesView } from "./preferencesApi";

type PreferencesDialogProps = {
  open: boolean;
  loading: boolean;
  error: string | null;
  view: PreferencesView | null;
  onClose(): void;
  onAddModel(): void;
  onScanModelDirectory(): void;
  onSetToolEnabled(toolId: string, enabled: boolean): void;
};

export function PreferencesDialog({
  open,
  loading,
  error,
  view,
  onClose,
  onAddModel,
  onScanModelDirectory,
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
                  <div>
                    <button className="secondaryButton" onClick={onAddModel} type="button">
                      添加 GGUF 模型
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
                {view.preferences.models.length > 0 ? (
                  <ul className="modelList">
                    {view.preferences.models.map((model) => (
                      <li key={model.modelId}>
                        <strong>{model.name}</strong>
                        <span>{model.runtime}</span>
                        <span>{model.fileExists ? model.path : `文件缺失：${model.path}`}</span>
                      </li>
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
                      tool={tool}
                      onSetToolEnabled={onSetToolEnabled}
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
      </div>
      <label className="toolToggle">
        <input
          checked={tool.enabled}
          disabled={!tool.valid}
          onChange={(event) => onSetToolEnabled(tool.toolId, event.target.checked)}
          type="checkbox"
        />
        {tool.enabled ? "启用" : "禁用"}
      </label>
    </li>
  );
}
```

- [ ] **Step 4: 运行前端测试**

Run:

```powershell
npm run frontend:test -- PreferencesDialog
```

Expected: PASS。

---

## Task 8: 接入 App 状态、工程保存和首选项流程

**Files:**
- Modify: `src/app/App.tsx`
- Modify: `src/app/app.css`

- [ ] **Step 1: 重构 App 状态**

在 `src/app/App.tsx` 中引入新组件和 API：

```tsx
import {
  createProject,
  openProject,
  pickCreateProjectPath,
  pickOpenProjectPath,
  pickSaveProjectAsPath,
  saveProject,
} from "../features/project/projectApi";
import { ProjectHome } from "../features/project/ProjectHome";
import {
  addModelFile,
  getPreferences,
  pickModelDirectory,
  pickModelFile,
  scanModelDirectory,
  setToolEnabled,
  type PreferencesView,
} from "../features/preferences/preferencesApi";
import { PreferencesDialog } from "../features/preferences/PreferencesDialog";
import { WorkbenchTopBar } from "../features/workbench/WorkbenchTopBar";
import type { AlitaProject, ProjectOpenResult, ProjectOpenWarning } from "../shared/types";
```

新增状态：

```tsx
const [activeProject, setActiveProject] = useState<AlitaProject | null>(null);
const [projectWarnings, setProjectWarnings] = useState<ProjectOpenWarning[]>([]);
const [projectError, setProjectError] = useState<string | null>(null);
const [dirty, setDirty] = useState(false);
const [saving, setSaving] = useState(false);
const [preferencesOpen, setPreferencesOpen] = useState(false);
const [preferencesView, setPreferencesView] = useState<PreferencesView | null>(null);
const [preferencesLoading, setPreferencesLoading] = useState(false);
const [preferencesError, setPreferencesError] = useState<string | null>(null);
const [recentProjects, setRecentProjects] = useState<string[]>([]);
```

App 需要从 React 引入 `useEffect`：

```tsx
import { useEffect, useState } from "react";
```

- [ ] **Step 2: 新建和打开工程处理**

在 `App.tsx` 中加入：

```tsx
const applyProjectOpenResult = (result: ProjectOpenResult) => {
  setActiveProject(result.project);
  setMessages(result.project.messages.length > 0 ? result.project.messages : initialMessages);
  setGraph(result.project.graph);
  setProjectWarnings(result.warnings);
  setDirty(false);
  setRecentProjects((current) =>
    [
      result.project.path,
      ...current.filter((path) => path !== result.project.path),
    ].slice(0, 8),
  );
};

useEffect(() => {
  getPreferences()
    .then((view) => setRecentProjects(view.preferences.recentProjects))
    .catch(() => setRecentProjects([]));
}, []);

const handleCreateProject = async () => {
  const path = await pickCreateProjectPath();
  if (!path) return;

  const fileName = path.split(/[\\/]/).pop() ?? "未命名工程.alita";
  const name = fileName.replace(/\.alita$/i, "");

  try {
    setProjectError(null);
    const result = await createProject(path, name);
    applyProjectOpenResult(result);
  } catch (error) {
    setProjectError(String(error));
  }
};

const handleOpenProject = async () => {
  const path = await pickOpenProjectPath();
  if (!path) return;

  try {
    setProjectError(null);
    const result = await openProject(path);
    applyProjectOpenResult(result);
  } catch (error) {
    setProjectError(String(error));
  }
};
```

`ProjectOpenResult` 从 `shared/types.ts` import。

- [ ] **Step 3: 保存工程处理**

在 `App.tsx` 中加入：

```tsx
const buildCurrentProject = (): AlitaProject | null => {
  if (!activeProject) return null;

  return {
    ...activeProject,
    messages,
    graph,
    attachments: activeProject.attachments,
    toolSnapshot: activeProject.toolSnapshot,
  };
};

const handleSaveProject = async () => {
  const project = buildCurrentProject();
  if (!project) return;

  try {
    setSaving(true);
    const result = await saveProject(project);
    applyProjectOpenResult(result);
  } catch (error) {
    setProjectError(String(error));
  } finally {
    setSaving(false);
  }
};

const handleSaveProjectAs = async () => {
  const project = buildCurrentProject();
  if (!project) return;

  const path = await pickSaveProjectAsPath(project.path);
  if (!path) return;

  try {
    setSaving(true);
    const result = await saveProject(project, path);
    applyProjectOpenResult(result);
  } catch (error) {
    setProjectError(String(error));
  } finally {
    setSaving(false);
  }
};
```

在 `handleSend` 中，当消息或图变化时调用 `setDirty(true)`。在 `setMessages` 和 `setGraph` 的任务处理分支后保留现有行为。

- [ ] **Step 4: 首选项处理**

在 `App.tsx` 中加入：

```tsx
const handleOpenPreferences = async () => {
  setPreferencesOpen(true);
  setPreferencesLoading(true);
  setPreferencesError(null);
  try {
    setPreferencesView(await getPreferences());
  } catch (error) {
    setPreferencesError(String(error));
  } finally {
    setPreferencesLoading(false);
  }
};

const handleAddModel = async () => {
  const path = await pickModelFile();
  if (!path) return;
  setPreferencesView(await addModelFile(path));
};

const handleScanModelDirectory = async () => {
  const path = await pickModelDirectory();
  if (!path) return;
  setPreferencesView(await scanModelDirectory(path));
};

const handleSetToolEnabled = async (toolId: string, enabled: boolean) => {
  setPreferencesView(await setToolEnabled(toolId, enabled));
};
```

- [ ] **Step 5: 调整 render 分支**

`App.tsx` return 改为：

```tsx
if (!activeProject) {
  return (
    <>
      <ProjectHome
        error={projectError}
        onCreateProject={handleCreateProject}
        onOpenProject={handleOpenProject}
        onOpenPreferences={handleOpenPreferences}
        recentProjects={recentProjects}
      />
      <PreferencesDialog
        open={preferencesOpen}
        loading={preferencesLoading}
        error={preferencesError}
        view={preferencesView}
        onClose={() => setPreferencesOpen(false)}
        onAddModel={handleAddModel}
        onScanModelDirectory={handleScanModelDirectory}
        onSetToolEnabled={handleSetToolEnabled}
      />
    </>
  );
}

return (
  <main className="appShell">
    <WorkbenchTopBar
      projectName={activeProject.name}
      dirty={dirty}
      saving={saving}
      onSave={handleSaveProject}
      onSaveAs={handleSaveProjectAs}
      onOpenPreferences={handleOpenPreferences}
    />
    {projectWarnings.length > 0 ? (
      <div className="projectWarningBar">
        {projectWarnings.map((warning) => warning.message).join("；")}
      </div>
    ) : null}
    <section className="chatColumn" aria-label="对话区域">
      <ChatPanel
        messages={messages}
        pendingAttachments={pendingAttachments}
        draft={draft}
        onDraftChange={setDraft}
        onSend={handleSend}
        onAddFile={handleAddFile}
      />
    </section>
    <section className="canvasColumn" aria-label="节点画布区域">
      <NodeCanvas graph={graph} />
    </section>
    <PreferencesDialog
      open={preferencesOpen}
      loading={preferencesLoading}
      error={preferencesError}
      view={preferencesView}
      onClose={() => setPreferencesOpen(false)}
      onAddModel={handleAddModel}
      onScanModelDirectory={handleScanModelDirectory}
      onSetToolEnabled={handleSetToolEnabled}
    />
  </main>
);
```

为了保持布局，`.appShell` 后续要从两列 grid 改成顶部栏 + 主体两列 grid。

- [ ] **Step 6: 增加 CSS**

在 `src/app/app.css` 中增加：

```css
.projectHome {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  width: 100vw;
  height: 100vh;
  padding: 18px;
  overflow: hidden;
  background: #eef2f5;
}

.projectHomeHeader,
.workbenchTopBar,
.preferencesHeader,
.preferencesSectionHeader {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.projectHomeHeader {
  padding: 12px 0 18px;
}

.projectHomeHeader h1 {
  margin: 0;
  color: #111827;
  font-size: 26px;
  line-height: 1.2;
}

.projectHomeHeader p {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 14px;
}

.projectHomeGrid {
  display: grid;
  grid-template-columns: minmax(280px, 0.8fr) minmax(0, 1.2fr);
  gap: 14px;
  min-height: 0;
}

.projectStartPanel,
.recentProjectsPanel,
.preferencesDialog {
  min-width: 0;
  border: 1px solid #cbd5df;
  border-radius: 8px;
  background: #ffffff;
}

.projectStartPanel,
.recentProjectsPanel {
  padding: 16px;
}

.projectStartPanel {
  display: grid;
  align-content: start;
  gap: 10px;
}

.workbenchTopBar {
  grid-column: 1 / -1;
  min-height: 44px;
  padding: 8px 12px;
  border: 1px solid #cbd5df;
  border-radius: 8px;
  background: #ffffff;
}

.projectWarningBar {
  grid-column: 1 / -1;
  padding: 8px 12px;
  border: 1px solid #fde68a;
  border-radius: 8px;
  color: #92400e;
  background: #fffbeb;
  font-size: 13px;
}

.projectIdentity,
.workbenchActions {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.saveState {
  color: #0f766e;
  font-size: 12px;
  font-weight: 700;
}

.saveStateDirty,
.errorText {
  color: #b91c1c;
}

.preferencesBackdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: center;
  padding: 18px;
  background: rgb(15 23 42 / 34%);
}

.preferencesDialog {
  width: min(960px, 100%);
  max-height: min(720px, calc(100vh - 36px));
  overflow: auto;
}

.preferencesHeader {
  padding: 14px;
  border-bottom: 1px solid #d9e2ea;
  background: #f8fafc;
}

.preferencesGrid {
  display: grid;
  grid-template-columns: 172px minmax(0, 1fr);
  gap: 14px;
  padding: 14px;
}

.preferencesSidebar {
  display: grid;
  align-content: start;
  gap: 10px;
  color: #334155;
  font-size: 13px;
}

.preferencesContent {
  display: grid;
  gap: 14px;
  min-width: 0;
}

.preferencesSection {
  min-width: 0;
  padding: 12px;
  border: 1px solid #d9e2ea;
  border-radius: 8px;
}

.modelList,
.toolList {
  display: grid;
  gap: 8px;
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
}

.modelList li,
.toolItem {
  display: grid;
  gap: 5px;
  padding: 10px;
  border: 1px solid #d9e2ea;
  border-radius: 8px;
}

.toolItem {
  grid-template-columns: minmax(0, 1fr) auto;
}

.toolItemInvalid {
  opacity: 0.72;
}

.toolToggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 700;
}
```

修改 `.appShell`：

```css
.appShell {
  display: grid;
  grid-template-columns: 40fr 60fr;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 10px;
  width: 100vw;
  height: 100vh;
  padding: 10px;
  overflow: hidden;
}
```

- [ ] **Step 7: 运行前端检查**

Run:

```powershell
npm run frontend:lint
npm run frontend:test
```

Expected: PASS。

---

## Task 9: 文档、MVP 验证和桌面冒烟测试

**Files:**
- Modify: `docs/mvp-verification.md`

- [ ] **Step 1: 更新 MVP 验证文档**

在 `docs/mvp-verification.md` 中增加工程系统验证：

```markdown
## 工程系统验证

启动桌面程序后，预期首先进入工程主页，而不是直接进入工作台。

1. 点击 `新建工程`，选择一个 `.alita` 文件路径。
2. 预期进入工作台，顶部栏显示工程名和 `已保存`。
3. 发送一条带附件的任务，预期顶部栏变为 `未保存`。
4. 点击 `保存`，预期顶部栏回到 `已保存`。
5. 关闭程序后重新启动，点击 `打开工程` 选择刚才的 `.alita` 文件。
6. 预期聊天记录和节点图恢复。

## 首选项验证

1. 在工程主页点击 `首选项`。
2. 预期看到 `模型` 和 `工具节点`。
3. 点击 `添加 GGUF 模型` 选择本地模型文件。
4. 预期模型出现在列表中。
5. 点击 `扫描模型目录` 选择模型目录。
6. 预期目录中的 `.gguf` 文件出现在模型列表中。
7. 在 `工具节点` 中切换文档处理工具启用状态。
8. 关闭再打开首选项，预期启用状态保持。
```

- [ ] **Step 2: 运行完整验证**

Run:

```powershell
.\scripts\verify-mvp.ps1
```

Expected: PASS。

- [ ] **Step 3: 启动桌面开发版做手动冒烟测试**

Run:

```powershell
Get-Process alita, alita-agent-sidecar, llama-server -ErrorAction SilentlyContinue | Stop-Process -Force
npm run desktop:dev
```

Expected:

- Windows 独立窗口打开。
- 首屏是工程主页。
- `首选项` 能打开。
- 新建 `.alita` 后进入工作台。
- 工作台顶部栏显示工程名。

- [ ] **Step 4: 构建 release 包**

Run:

```powershell
npm run desktop:build
```

Expected: `src-tauri\target\release\bundle\nsis\Alita_0.1.0_x64-setup.exe` 生成。

---

## 自检清单

- [ ] 没有激活工程时不能进入聊天和节点工作台。
- [ ] `.alita` 文件可以新建、保存、打开。
- [ ] 工程保存后能恢复聊天记录和节点图。
- [ ] 首选项可以从工程主页和工作台进入。
- [ ] 手动添加 `.gguf` 模型后能持久化。
- [ ] 扫描模型目录后能持久化发现的模型。
- [ ] 工具 manifest 能显示在工具节点列表中。
- [ ] 工具启用/禁用状态能持久化。
- [ ] 未配置模型路径时，`llama-server` 仍然不会启动。
- [ ] CUDA 版 `llama.cpp` 资源仍然包含在 release 包中。


