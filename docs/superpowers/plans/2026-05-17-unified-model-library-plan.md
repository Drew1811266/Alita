# Unified Model Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Preferences into a unified local model library where Agent GGUF models and Qwen ASR speech-to-text models are both registered, assigned, and resolved from one durable configuration.

**Architecture:** Preferences schema v2 adds explicit model metadata (`modelKind`, `runtime`, `pathKind`) and role assignments (`agentChatModelId`, `speechToTextModelId`). Rust owns persistence, migration, validation, and runtime resolution; React renders a single model library surface; Python ASR accepts an explicit model path from Tauri so Preferences can drive transcription without restarting the sidecar.

**Tech Stack:** Rust/Tauri, Serde preferences migration, React/TypeScript static-render tests, PowerShell development scripts, Python FastAPI ASR sidecar.

---

## File Structure

- Modify `src-tauri/src/preferences.rs`: schema v2, model metadata, assignments, migration, role validation, model path resolution.
- Modify `src-tauri/tests/preferences_tests.rs`: migration, ASR model registration, role assignment, path resolution.
- Modify `src/shared/types.ts`: TypeScript model kind/runtime/path-kind/assignment types.
- Modify `src-tauri/src/commands.rs`: new ASR model directory and assignment commands; ASR command preference resolution.
- Modify `src-tauri/src/lib.rs`: register new commands.
- Modify `src-tauri/src/agent_client.rs`: optional ASR model path in status/transcription requests.
- Modify `src-tauri/tests/agent_client_tests.rs`: ASR request/query includes model path and auth.
- Modify `src-tauri/tests/asr_tests.rs`: ASR command payload remains stable and preference path resolution is covered by command/client tests.
- Modify `python/agent_service/asr.py`: explicit `modelPath` support in status and transcription.
- Modify `python/agent_service/app.py`: accept explicit ASR model path from Tauri.
- Modify `python/tests/test_asr.py`: explicit model path status/transcription tests.
- Modify `src/features/preferences/preferencesApi.ts`: model-library commands and directory picker API.
- Modify `src/features/preferences/PreferencesDialog.tsx`: unified model library UI and assignments.
- Modify `src/features/preferences/PreferencesDialog.test.tsx`: model library and assignment markup tests.
- Modify `src/app/App.tsx`: handlers for adding speech-to-text model and setting assignments.
- Modify `scripts/dev-model-env.ps1`: read `modelAssignments.agentChatModelId` before `defaultModelId`.
- Modify `scripts/test-dev-model-env.ps1`: assignment-first script test.
- Modify `docs/windows-desktop-runbook.md`: unified model library note.

---

### Task 1: Preferences Schema V2 And Model Assignment Core

**Files:**
- Modify: `src-tauri/src/preferences.rs`
- Modify: `src-tauri/tests/preferences_tests.rs`

- [ ] **Step 1: Write failing migration and assignment tests**

Append these tests to `src-tauri/tests/preferences_tests.rs` and update imports to include the new functions/types:

```rust
use alita_lib::preferences::{
    add_speech_to_text_model, agent_model_path, set_model_assignment, speech_to_text_model_path,
    ModelAssignmentRole,
};

#[test]
fn loads_version_one_preferences_as_version_two_model_library() {
    let temp_dir = tempfile::tempdir().unwrap();
    let preferences_path = temp_dir.path().join("preferences.json");
    let model_path = temp_dir.path().join("agent.gguf");
    fs::write(&model_path, "model").unwrap();
    fs::write(
        &preferences_path,
        format!(
            r#"{{
              "schemaVersion": 1,
              "recentProjects": [],
              "modelDirectories": [],
              "modelStorageDir": "",
              "models": [{{
                "modelId": "model-1",
                "name": "agent",
                "path": "{}",
                "source": "manual",
                "runtime": "llama_cpp",
                "fileExists": true,
                "createdAt": "2026-05-17T00:00:00.000Z",
                "updatedAt": "2026-05-17T00:00:00.000Z"
              }}],
              "defaultModelId": "model-1",
              "toolEnablement": {{}}
            }}"#,
            model_path.to_string_lossy().replace('\\', "\\\\")
        ),
    )
    .unwrap();

    let preferences = load_preferences_from_path(&preferences_path).unwrap();

    assert_eq!(preferences.schema_version, 2);
    assert_eq!(preferences.models[0].model_kind, "agent_llm");
    assert_eq!(preferences.models[0].path_kind, "file");
    assert_eq!(
        preferences.model_assignments.agent_chat_model_id.as_deref(),
        Some("model-1")
    );
    assert_eq!(agent_model_path(&preferences), Some(model_path));
}

#[test]
fn adds_speech_to_text_model_directory_and_assigns_it() {
    let temp_dir = tempfile::tempdir().unwrap();
    let asr_dir = temp_dir.path().join("Qwen3-ASR-1.7B");
    fs::create_dir_all(&asr_dir).unwrap();
    let mut preferences = AppPreferences::default();

    let model = add_speech_to_text_model(&mut preferences, &asr_dir).unwrap();
    set_model_assignment(
        &mut preferences,
        ModelAssignmentRole::SpeechToText,
        Some(&model.model_id),
    )
    .unwrap();

    assert_eq!(model.model_kind, "speech_to_text");
    assert_eq!(model.runtime, "qwen_asr");
    assert_eq!(model.path_kind, "directory");
    assert_eq!(speech_to_text_model_path(&preferences), Some(asr_dir));
}

#[test]
fn rejects_assignment_to_wrong_model_kind() {
    let temp_dir = tempfile::tempdir().unwrap();
    let model_path = temp_dir.path().join("agent.gguf");
    fs::write(&model_path, "model").unwrap();
    let mut preferences = AppPreferences::default();
    let model = add_manual_model(&mut preferences, &model_path).unwrap();

    let error = set_model_assignment(
        &mut preferences,
        ModelAssignmentRole::SpeechToText,
        Some(&model.model_id),
    )
    .unwrap_err();

    assert!(error.contains("speech_to_text"));
}
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml preferences_tests
```

Expected: FAIL because `ModelAssignmentRole`, `model_assignments`, `model_kind`, `path_kind`, `add_speech_to_text_model`, `agent_model_path`, and `speech_to_text_model_path` do not exist.

- [ ] **Step 3: Implement schema v2 structs and migration**

In `src-tauri/src/preferences.rs`:

```rust
const PREFERENCES_SCHEMA_VERSION: u32 = 2;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ModelAssignments {
    pub agent_chat_model_id: Option<String>,
    pub speech_to_text_model_id: Option<String>,
}

impl Default for ModelAssignments {
    fn default() -> Self {
        Self {
            agent_chat_model_id: None,
            speech_to_text_model_id: None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ModelAssignmentRole {
    AgentChat,
    SpeechToText,
}
```

Extend `AppPreferences` and `ModelEntry`:

```rust
pub struct AppPreferences {
    pub schema_version: u32,
    pub recent_projects: Vec<String>,
    pub model_directories: Vec<String>,
    #[serde(default)]
    pub model_storage_dir: String,
    pub models: Vec<ModelEntry>,
    pub default_model_id: Option<String>,
    #[serde(default)]
    pub model_assignments: ModelAssignments,
    pub tool_enablement: HashMap<String, bool>,
}

pub struct ModelEntry {
    pub model_id: String,
    pub name: String,
    pub path: String,
    pub source: String,
    pub runtime: String,
    #[serde(default = "default_agent_model_kind")]
    pub model_kind: String,
    #[serde(default = "default_file_path_kind")]
    pub path_kind: String,
    pub file_exists: bool,
    pub created_at: String,
    pub updated_at: String,
}

fn default_agent_model_kind() -> String {
    "agent_llm".to_string()
}

fn default_file_path_kind() -> String {
    "file".to_string()
}
```

Replace `load_preferences_from_path` parsing with version-tolerant loading:

```rust
let value: serde_json::Value = serde_json::from_str(&contents)
    .map_err(|error| format!("failed to parse preferences '{}': {error}", path.display()))?;
let schema_version = value
    .get("schemaVersion")
    .and_then(|value| value.as_u64())
    .unwrap_or(1) as u32;

let mut preferences: AppPreferences = match schema_version {
    1 | 2 => serde_json::from_value(value).map_err(|error| {
        format!("failed to parse preferences '{}': {error}", path.display())
    })?,
    version => return Err(format!("unsupported preferences schema version: {version}")),
};

if preferences.schema_version == 1 {
    migrate_preferences_v1_to_v2(&mut preferences);
}
normalize_preferences(&mut preferences);
Ok(preferences)
```

Add helpers:

```rust
fn migrate_preferences_v1_to_v2(preferences: &mut AppPreferences) {
    preferences.schema_version = PREFERENCES_SCHEMA_VERSION;
    if preferences.model_assignments.agent_chat_model_id.is_none() {
        preferences.model_assignments.agent_chat_model_id = preferences.default_model_id.clone();
    }
    for model in &mut preferences.models {
        if model.model_kind.trim().is_empty() {
            model.model_kind = "agent_llm".to_string();
        }
        if model.path_kind.trim().is_empty() {
            model.path_kind = "file".to_string();
        }
        if model.runtime.trim().is_empty() {
            model.runtime = "llama_cpp".to_string();
        }
    }
}

fn normalize_preferences(preferences: &mut AppPreferences) {
    preferences.schema_version = PREFERENCES_SCHEMA_VERSION;
    if preferences.model_assignments.agent_chat_model_id.is_none() {
        preferences.model_assignments.agent_chat_model_id = preferences.default_model_id.clone();
    }
    preferences.default_model_id = preferences.model_assignments.agent_chat_model_id.clone();
}
```

- [ ] **Step 4: Implement ASR model registration and assignment helpers**

Add these functions in `src-tauri/src/preferences.rs` near the existing model helpers:

```rust
pub fn add_speech_to_text_model(
    preferences: &mut AppPreferences,
    path: impl AsRef<Path>,
) -> Result<ModelEntry, String> {
    let path = path.as_ref();
    if !path.is_dir() {
        return Err(format!(
            "speech-to-text model directory is not accessible: {}",
            path.display()
        ));
    }
    add_or_update_typed_model(preferences, path, "manual", "speech_to_text", "qwen_asr", "directory")
}

pub fn set_model_assignment(
    preferences: &mut AppPreferences,
    role: ModelAssignmentRole,
    model_id: Option<&str>,
) -> Result<(), String> {
    let Some(model_id) = model_id else {
        match role {
            ModelAssignmentRole::AgentChat => {
                preferences.model_assignments.agent_chat_model_id = None;
                preferences.default_model_id = None;
            }
            ModelAssignmentRole::SpeechToText => {
                preferences.model_assignments.speech_to_text_model_id = None;
            }
        }
        return Ok(());
    };

    let expected_kind = match role {
        ModelAssignmentRole::AgentChat => "agent_llm",
        ModelAssignmentRole::SpeechToText => "speech_to_text",
    };
    let model = preferences
        .models
        .iter()
        .find(|model| model.model_id == model_id)
        .ok_or_else(|| format!("unknown model id: {model_id}"))?;
    if model.model_kind != expected_kind {
        return Err(format!(
            "model '{model_id}' cannot be assigned to {expected_kind}"
        ));
    }

    match role {
        ModelAssignmentRole::AgentChat => {
            preferences.model_assignments.agent_chat_model_id = Some(model_id.to_string());
            preferences.default_model_id = Some(model_id.to_string());
        }
        ModelAssignmentRole::SpeechToText => {
            preferences.model_assignments.speech_to_text_model_id = Some(model_id.to_string());
        }
    }
    Ok(())
}

pub fn agent_model_path(preferences: &AppPreferences) -> Option<PathBuf> {
    assigned_model_path(
        preferences,
        preferences
            .model_assignments
            .agent_chat_model_id
            .as_deref()
            .or(preferences.default_model_id.as_deref()),
        "agent_llm",
        "file",
    )
}

pub fn speech_to_text_model_path(preferences: &AppPreferences) -> Option<PathBuf> {
    assigned_model_path(
        preferences,
        preferences.model_assignments.speech_to_text_model_id.as_deref(),
        "speech_to_text",
        "directory",
    )
}

fn assigned_model_path(
    preferences: &AppPreferences,
    model_id: Option<&str>,
    model_kind: &str,
    path_kind: &str,
) -> Option<PathBuf> {
    let model_id = model_id?;
    preferences
        .models
        .iter()
        .find(|model| {
            model.model_id == model_id
                && model.model_kind == model_kind
                && model.path_kind == path_kind
        })
        .map(|model| PathBuf::from(&model.path))
}
```

Change existing GGUF paths to call:

```rust
fn add_or_update_typed_model(
    preferences: &mut AppPreferences,
    path: &Path,
    source: &str,
    model_kind: &str,
    runtime: &str,
    path_kind: &str,
) -> Result<ModelEntry, String> {
    let path_text = path.to_string_lossy().into_owned();
    let now = Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true);
    let name = path
        .file_stem()
        .or_else(|| path.file_name())
        .and_then(|name| name.to_str())
        .unwrap_or("未命名模型")
        .to_string();
    let file_exists = match path_kind {
        "directory" => path.is_dir(),
        _ => path.is_file(),
    };

    if let Some(existing) = preferences.models.iter_mut().find(|model| {
        model.path == path_text && model.model_kind == model_kind && model.runtime == runtime
    }) {
        existing.name = name;
        existing.source = source.to_string();
        existing.runtime = runtime.to_string();
        existing.model_kind = model_kind.to_string();
        existing.path_kind = path_kind.to_string();
        existing.file_exists = file_exists;
        existing.updated_at = now;
        let entry = existing.clone();
        if model_kind == "agent_llm"
            && preferences.model_assignments.agent_chat_model_id.is_none()
        {
            preferences.model_assignments.agent_chat_model_id = Some(entry.model_id.clone());
            preferences.default_model_id = Some(entry.model_id.clone());
        }
        if model_kind == "speech_to_text"
            && preferences
                .model_assignments
                .speech_to_text_model_id
                .is_none()
        {
            preferences.model_assignments.speech_to_text_model_id = Some(entry.model_id.clone());
        }
        return Ok(entry);
    }

    let entry = ModelEntry {
        model_id: Uuid::new_v4().to_string(),
        name,
        path: path_text,
        source: source.to_string(),
        runtime: runtime.to_string(),
        model_kind: model_kind.to_string(),
        path_kind: path_kind.to_string(),
        file_exists,
        created_at: now.clone(),
        updated_at: now,
    };
    if model_kind == "agent_llm" && preferences.model_assignments.agent_chat_model_id.is_none() {
        preferences.model_assignments.agent_chat_model_id = Some(entry.model_id.clone());
        preferences.default_model_id = Some(entry.model_id.clone());
    }
    if model_kind == "speech_to_text"
        && preferences
            .model_assignments
            .speech_to_text_model_id
            .is_none()
    {
        preferences.model_assignments.speech_to_text_model_id = Some(entry.model_id.clone());
    }
    preferences.models.push(entry.clone());
    Ok(entry)
}
```

Then update `add_or_update_model` to call:

```rust
add_or_update_typed_model(preferences, path, source, "agent_llm", "llama_cpp", "file")
```

- [ ] **Step 5: Keep existing default model API compatible**

Update `set_default_model`:

```rust
pub fn set_default_model(
    preferences: &mut AppPreferences,
    model_id: Option<&str>,
) -> Result<(), String> {
    set_model_assignment(preferences, ModelAssignmentRole::AgentChat, model_id)
}
```

Update `default_model_path`:

```rust
pub fn default_model_path(preferences: &AppPreferences) -> Option<PathBuf> {
    agent_model_path(preferences)
}
```

- [ ] **Step 6: Run Rust preference tests**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml preferences_tests
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src-tauri/src/preferences.rs src-tauri/tests/preferences_tests.rs
git commit -m "feat: add unified model preference schema"
```

---

### Task 2: Tauri Commands And TypeScript API For Model Library

**Files:**
- Modify: `src/shared/types.ts`
- Modify: `src-tauri/src/commands.rs`
- Modify: `src-tauri/src/lib.rs`
- Modify: `src/features/preferences/preferencesApi.ts`
- Modify: `src-tauri/tests/preferences_tests.rs`

- [ ] **Step 1: Write failing command-level Rust tests**

Add tests to `src-tauri/tests/preferences_tests.rs` for the new assignment helper if not covered by Task 1:

```rust
#[test]
fn clearing_model_assignments_is_supported() {
    let temp_dir = tempfile::tempdir().unwrap();
    let model_path = temp_dir.path().join("agent.gguf");
    fs::write(&model_path, "model").unwrap();
    let mut preferences = AppPreferences::default();
    let model = add_manual_model(&mut preferences, &model_path).unwrap();
    set_model_assignment(
        &mut preferences,
        ModelAssignmentRole::AgentChat,
        Some(&model.model_id),
    )
    .unwrap();

    set_model_assignment(&mut preferences, ModelAssignmentRole::AgentChat, None).unwrap();

    assert_eq!(preferences.model_assignments.agent_chat_model_id, None);
    assert_eq!(preferences.default_model_id, None);
}
```

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml preferences_tests::clearing_model_assignments_is_supported
```

Expected: PASS after Task 1. This test protects command behavior before wiring commands.

- [ ] **Step 2: Update shared TypeScript types**

In `src/shared/types.ts`, replace the model types with:

```ts
export type ModelSource = "manual" | "scan" | "imported";
export type ModelKind = "agent_llm" | "speech_to_text";
export type ModelRuntime = "llama_cpp" | "qwen_asr";
export type ModelPathKind = "file" | "directory";

export type ModelEntry = {
  modelId: string;
  name: string;
  path: string;
  pathKind: ModelPathKind;
  modelKind: ModelKind;
  source: ModelSource;
  runtime: ModelRuntime;
  fileExists: boolean;
  createdAt: string;
  updatedAt: string;
};

export type ModelAssignments = {
  agentChatModelId: string | null;
  speechToTextModelId: string | null;
};

export type AppPreferences = {
  schemaVersion: 2;
  recentProjects: string[];
  modelDirectories: string[];
  modelStorageDir: string;
  models: ModelEntry[];
  defaultModelId: string | null;
  modelAssignments: ModelAssignments;
  toolEnablement: Record<string, boolean>;
};
```

- [ ] **Step 3: Add Tauri command payloads and commands**

In `src-tauri/src/commands.rs`, update imports:

```rust
use crate::preferences::{
    add_manual_model, add_speech_to_text_model, import_model_to_storage,
    load_preferences_with_model_recovery, model_recovery_candidate_dirs,
    previous_preferences_path_for_current_path, record_recent_project, save_preferences_to_path,
    scan_model_directory, set_default_model, set_model_assignment, set_model_storage_dir,
    summarize_tool_manifests, AppPreferences, ModelAssignmentRole, ToolSummary,
};
```

Add payloads:

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AddSpeechToTextModelPayload {
    pub path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SetModelAssignmentPayload {
    pub role: String,
    pub model_id: Option<String>,
}
```

Add commands:

```rust
#[tauri::command]
pub async fn add_speech_to_text_model_directory(
    app: AppHandle,
    payload: AddSpeechToTextModelPayload,
) -> Result<PreferencesView, String> {
    let (path, mut preferences) = load_preferences_for_app(&app)?;
    let model = add_speech_to_text_model(&mut preferences, PathBuf::from(payload.path))?;
    if preferences
        .model_assignments
        .speech_to_text_model_id
        .is_none()
    {
        set_model_assignment(
            &mut preferences,
            ModelAssignmentRole::SpeechToText,
            Some(&model.model_id),
        )?;
    }
    save_preferences_to_path(&path, &preferences)?;
    let tools = summarize_tool_manifests(packages_root(), &preferences);
    Ok(PreferencesView { preferences, tools })
}

#[tauri::command]
pub async fn set_model_assignment_command(
    app: AppHandle,
    payload: SetModelAssignmentPayload,
) -> Result<PreferencesView, String> {
    let role = match payload.role.as_str() {
        "agentChat" => ModelAssignmentRole::AgentChat,
        "speechToText" => ModelAssignmentRole::SpeechToText,
        other => return Err(format!("unknown model assignment role: {other}")),
    };
    let (path, mut preferences) = load_preferences_for_app(&app)?;
    set_model_assignment(&mut preferences, role, payload.model_id.as_deref())?;
    save_preferences_to_path(&path, &preferences)?;
    let tools = summarize_tool_manifests(packages_root(), &preferences);
    Ok(PreferencesView { preferences, tools })
}
```

- [ ] **Step 4: Register commands**

In `src-tauri/src/lib.rs`, add:

```rust
commands::add_speech_to_text_model_directory,
commands::set_model_assignment_command,
```

to the `tauri::generate_handler!` list.

- [ ] **Step 5: Update frontend preferences API**

In `src/features/preferences/preferencesApi.ts`, add:

```ts
export type ModelAssignmentRole = "agentChat" | "speechToText";

export async function pickSpeechToTextModelDirectory(): Promise<string | null> {
  if (!isTauriRuntime()) {
    return window.prompt("输入 Qwen3-ASR-1.7B 模型目录路径");
  }

  const selected = await open({
    multiple: false,
    directory: true,
  });
  return typeof selected === "string" ? selected : null;
}

export async function addSpeechToTextModelDirectory(
  path: string,
): Promise<PreferencesView> {
  return invoke<PreferencesView>("add_speech_to_text_model_directory", {
    payload: { path },
  });
}

export async function setModelAssignment(
  role: ModelAssignmentRole,
  modelId: string | null,
): Promise<PreferencesView> {
  return invoke<PreferencesView>("set_model_assignment_command", {
    payload: { role, modelId },
  });
}
```

- [ ] **Step 6: Run typecheck and Rust tests**

Run:

```powershell
npm run frontend:lint
cargo test --manifest-path src-tauri/Cargo.toml preferences_tests
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/shared/types.ts src-tauri/src/commands.rs src-tauri/src/lib.rs src/features/preferences/preferencesApi.ts src-tauri/tests/preferences_tests.rs
git commit -m "feat: expose model library commands"
```

---

### Task 3: Preferences UI For Unified Model Library

**Files:**
- Modify: `src/features/preferences/PreferencesDialog.tsx`
- Modify: `src/features/preferences/PreferencesDialog.test.tsx`
- Modify: `src/app/App.tsx`
- Modify: `src/app/app.css`

- [ ] **Step 1: Update failing Preferences dialog test data**

In `src/features/preferences/PreferencesDialog.test.tsx`, update `view.preferences` to schema v2:

```tsx
modelAssignments: {
  agentChatModelId: "model-1",
  speechToTextModelId: "asr-1",
},
models: [
  {
    modelId: "model-1",
    name: "qwen3-8b",
    path: "D:\\Models\\qwen3-8b.gguf",
    source: "manual",
    runtime: "llama_cpp",
    modelKind: "agent_llm",
    pathKind: "file",
    fileExists: true,
    createdAt: "2026-05-09T12:00:00.000Z",
    updatedAt: "2026-05-09T12:00:00.000Z",
  },
  {
    modelId: "asr-1",
    name: "Qwen3-ASR-1.7B",
    path: "D:\\Models\\Qwen3-ASR-1.7B",
    source: "manual",
    runtime: "qwen_asr",
    modelKind: "speech_to_text",
    pathKind: "directory",
    fileExists: true,
    createdAt: "2026-05-17T12:00:00.000Z",
    updatedAt: "2026-05-17T12:00:00.000Z",
  },
],
```

Update expectations:

```tsx
expect(markup).toContain("模型库");
expect(markup).toContain("当前模型分配");
expect(markup).toContain("Agent 模型");
expect(markup).toContain("语音转文字");
expect(markup).toContain("添加语音转文字模型");
expect(markup).toContain("Qwen3-ASR-1.7B");
expect(markup).toContain("Qwen ASR");
expect(markup).toContain("当前语音转文字模型");
expect(markup).toContain("当前 Agent 模型");
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```powershell
npm run frontend:test -- src/features/preferences/PreferencesDialog.test.tsx
```

Expected: FAIL because the UI does not render model assignments or ASR model controls.

- [ ] **Step 3: Extend Preferences dialog props**

In `src/features/preferences/PreferencesDialog.tsx`, update props:

```tsx
onAddSpeechToTextModel(): void;
onSetModelAssignment(role: "agentChat" | "speechToText", modelId: string): void;
```

Keep `onSetDefaultModel` during transition, but use `onSetModelAssignment("agentChat", id)` for new UI buttons.

- [ ] **Step 4: Render model assignments**

Add helpers:

```tsx
function assignedModelName(
  models: ModelEntry[],
  modelId: string | null,
): string {
  return models.find((model) => model.modelId === modelId)?.name ?? "未配置";
}

function modelKindLabel(model: ModelEntry): string {
  return model.modelKind === "speech_to_text" ? "语音转文字" : "Agent 模型";
}

function runtimeLabel(model: ModelEntry): string {
  return model.runtime === "qwen_asr" ? "Qwen ASR" : "llama.cpp";
}
```

In the model section, render:

```tsx
<div className="modelAssignments" aria-label="当前模型分配">
  <div>
    <span>Agent 模型</span>
    <strong>
      {assignedModelName(
        view.preferences.models,
        view.preferences.modelAssignments.agentChatModelId ??
          view.preferences.defaultModelId,
      )}
    </strong>
  </div>
  <div>
    <span>语音转文字</span>
    <strong>
      {assignedModelName(
        view.preferences.models,
        view.preferences.modelAssignments.speechToTextModelId,
      )}
    </strong>
  </div>
</div>
```

- [ ] **Step 5: Add ASR model action and assignment buttons**

Add a button next to existing model actions:

```tsx
<button
  className="secondaryButton"
  onClick={onAddSpeechToTextModel}
  type="button"
>
  添加语音转文字模型
</button>
```

Update `ModelItem` props:

```tsx
assignedRole: "agentChat" | "speechToText" | null;
onSetModelAssignment(role: "agentChat" | "speechToText", modelId: string): void;
```

Render assignment buttons:

```tsx
{model.modelKind === "agent_llm" ? (
  assignedRole === "agentChat" ? (
    <span className="modelDefaultBadge">当前 Agent 模型</span>
  ) : (
    <button
      className="secondaryButton compactButton"
      onClick={() => onSetModelAssignment("agentChat", model.modelId)}
      type="button"
    >
      设为 Agent 默认模型
    </button>
  )
) : assignedRole === "speechToText" ? (
  <span className="modelDefaultBadge">当前语音转文字模型</span>
) : (
  <button
    className="secondaryButton compactButton"
    onClick={() => onSetModelAssignment("speechToText", model.modelId)}
    type="button"
  >
    设为语音转文字模型
  </button>
)}
```

- [ ] **Step 6: Wire App handlers**

In `src/app/App.tsx`, import:

```ts
addSpeechToTextModelDirectory,
pickSpeechToTextModelDirectory,
setModelAssignment,
type ModelAssignmentRole,
```

Add handlers:

```tsx
const handleAddSpeechToTextModel = async () => {
  const path = await pickSpeechToTextModelDirectory();
  if (!path) {
    return;
  }
  try {
    setPreferencesError(null);
    setPreferencesView(await addSpeechToTextModelDirectory(path));
  } catch (error) {
    setPreferencesError(String(error));
  }
};

const handleSetModelAssignment = async (
  role: ModelAssignmentRole,
  modelId: string,
) => {
  try {
    setPreferencesError(null);
    const view = await setModelAssignment(role, modelId);
    setPreferencesView(view);
    setRecentProjects(view.preferences.recentProjects);
  } catch (error) {
    setPreferencesError(String(error));
  }
};
```

Pass to `PreferencesDialog`:

```tsx
onAddSpeechToTextModel={handleAddSpeechToTextModel}
onSetModelAssignment={handleSetModelAssignment}
```

- [ ] **Step 7: Add CSS**

In `src/app/app.css`, add:

```css
.modelAssignments {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin: 10px 0 12px;
}

.modelAssignments > div {
  min-width: 0;
  padding: 10px;
  border: 1px solid #d9e2ea;
  border-radius: 6px;
  background: #f8fafc;
}

.modelAssignments span,
.modelMetaLine {
  display: block;
  color: #64748b;
  font-size: 12px;
  line-height: 18px;
}

.modelAssignments strong {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  color: #111827;
  font-size: 14px;
  line-height: 20px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
```

Add a mobile rule inside the existing narrow viewport block:

```css
.modelAssignments {
  grid-template-columns: 1fr;
}
```

- [ ] **Step 8: Run frontend tests**

Run:

```powershell
npm run frontend:test -- src/features/preferences/PreferencesDialog.test.tsx
npm run frontend:lint
```

Expected: PASS.

- [ ] **Step 9: Commit**

```powershell
git add src/features/preferences/PreferencesDialog.tsx src/features/preferences/PreferencesDialog.test.tsx src/app/App.tsx src/app/app.css
git commit -m "feat: show unified model library in preferences"
```

---

### Task 4: ASR Runtime Resolution From Model Library

**Files:**
- Modify: `python/agent_service/asr.py`
- Modify: `python/agent_service/app.py`
- Modify: `python/tests/test_asr.py`
- Modify: `src-tauri/src/agent_client.rs`
- Modify: `src-tauri/tests/agent_client_tests.rs`
- Modify: `src-tauri/src/commands.rs`
- Modify: `src-tauri/tests/asr_tests.rs`

- [ ] **Step 1: Write failing Python tests for explicit model path**

Add to `python/tests/test_asr.py`:

```python
def test_status_accepts_explicit_model_path(monkeypatch, tmp_path):
    monkeypatch.delenv(ALITA_ASR_MODEL_PATH_ENV, raising=False)
    model_dir = tmp_path / "Qwen3-ASR-1.7B"
    model_dir.mkdir()

    status = get_asr_status(
        model_path=model_dir,
        dependency_available=lambda: True,
    )

    assert status.available is True
    assert status.modelPath == str(model_dir)


def test_transcribe_uses_request_model_path(tmp_path):
    model_dir = tmp_path / "Qwen3-ASR-1.7B"
    model_dir.mkdir()
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"RIFF....WAVEfmt ")
    provider = FakeProvider(text="hello")
    service = ASRService(provider_factory=lambda _model_path: provider)

    result = service.transcribe(
        TranscriptionRequest(audioPath=str(audio_path), modelPath=str(model_dir)),
    )

    assert result.text == "hello"
    assert provider.calls == [(audio_path, "zh")]
```

- [ ] **Step 2: Run Python test and verify it fails**

Run:

```powershell
python -m pytest python/tests/test_asr.py -q
```

Expected: FAIL because `model_path` and `modelPath` are not supported.

- [ ] **Step 3: Implement explicit ASR model path in Python**

In `python/agent_service/asr.py`:

```python
class TranscriptionRequest(BaseModel):
    audioPath: str
    language: str = Field(default="zh")
    modelPath: str | None = None


def get_asr_status(
    dependency_available: Callable[[], bool] = qwen_asr_dependency_available,
    model_path: Path | None = None,
) -> ASRStatus:
    resolved_model_path = model_path or configured_model_path()
    # use resolved_model_path for the existing checks
```

In `ASRService.transcribe`, resolve:

```python
request_model_path = (
    Path(request.modelPath).expanduser() if request.modelPath else None
)
resolved_model_path = model_path or request_model_path or configured_model_path()
```

In `python/agent_service/app.py`:

```python
@app.get("/asr/status", response_model=ASRStatus)
def asr_status(
    modelPath: str | None = None,
    _auth: None = Depends(require_sidecar_token),
) -> ASRStatus:
    path = Path(modelPath).expanduser() if modelPath else None
    return get_asr_status(model_path=path)
```

- [ ] **Step 4: Write failing Rust client tests**

In `src-tauri/tests/agent_client_tests.rs`, update ASR tests to expect `modelPath`:

```rust
#[test]
fn transcribe_asr_audio_sends_model_path_when_present() {
    let request = agent_client::AsrTranscriptionRequest {
        audio_path: "D:\\Temp\\input.wav".to_string(),
        language: "zh".to_string(),
        model_path: Some("D:\\Models\\Qwen3-ASR-1.7B".to_string()),
    };

    let json = serde_json::to_value(&request).unwrap();

    assert_eq!(json["modelPath"], "D:\\Models\\Qwen3-ASR-1.7B");
}
```

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml agent_client_tests
```

Expected: FAIL because `AsrTranscriptionRequest` has no `model_path`.

- [ ] **Step 5: Update Rust ASR client and command resolution**

In `src-tauri/src/agent_client.rs`, update request type:

```rust
pub struct AsrTranscriptionRequest {
    pub audio_path: String,
    pub language: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub model_path: Option<String>,
}
```

Add a status helper:

```rust
pub async fn get_asr_status_for_model(
    &self,
    model_path: Option<&str>,
) -> Result<AsrStatusResponse, String> {
    let mut request = self.client.get(format!("{}/asr/status", self.base_url.trim_end_matches('/')));
    if let Some(model_path) = model_path {
        request = request.query(&[("modelPath", model_path)]);
    }
    // keep existing auth and error handling
}
```

Keep `get_asr_status()` as a wrapper calling `get_asr_status_for_model(None)`.

In `src-tauri/src/commands.rs`, add helper:

```rust
fn configured_asr_model_path(app: &AppHandle) -> Result<Option<PathBuf>, String> {
    if let Ok(value) = std::env::var("ALITA_ASR_MODEL_PATH") {
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            return Ok(Some(PathBuf::from(trimmed)));
        }
    }
    let (_, preferences) = load_preferences_for_app(app)?;
    Ok(crate::preferences::speech_to_text_model_path(&preferences))
}
```

Update `get_asr_status`:

```rust
let model_path = configured_asr_model_path(&app)?;
if model_path.is_none() {
    return Ok(AsrStatusResponse {
        available: false,
        configured: false,
        model_path: None,
        message: "voice model is not configured".to_string(),
        error_code: Some("asr_not_configured".to_string()),
    });
}
let model_path_text = model_path.as_ref().map(|path| path.to_string_lossy().into_owned());
client.get_asr_status_for_model(model_path_text.as_deref()).await
```

Update `transcribe_voice_audio` request:

```rust
let model_path = configured_asr_model_path(&app)?
    .ok_or_else(|| "voice model is not configured".to_string())?;
let request = AsrTranscriptionRequest {
    audio_path: temp_audio_path.to_string_lossy().to_string(),
    language: "zh".to_string(),
    model_path: Some(model_path.to_string_lossy().to_string()),
};
```

- [ ] **Step 6: Run ASR tests**

Run:

```powershell
python -m pytest python/tests/test_asr.py -q
cargo test --manifest-path src-tauri/Cargo.toml agent_client_tests asr_tests
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add python/agent_service/asr.py python/agent_service/app.py python/tests/test_asr.py src-tauri/src/agent_client.rs src-tauri/tests/agent_client_tests.rs src-tauri/src/commands.rs src-tauri/tests/asr_tests.rs
git commit -m "feat: resolve ASR model from preferences"
```

---

### Task 5: Agent Runtime And Development Script Assignment Resolution

**Files:**
- Modify: `src-tauri/src/llama_runtime.rs`
- Modify: `src-tauri/tests/llama_runtime_tests.rs`
- Modify: `scripts/dev-model-env.ps1`
- Modify: `scripts/test-dev-model-env.ps1`
- Modify: `docs/windows-desktop-runbook.md`

- [ ] **Step 1: Write failing Rust runtime test**

In `src-tauri/tests/llama_runtime_tests.rs`, add a test that builds preferences with `model_assignments.agent_chat_model_id` set and `default_model_id` unset:

```rust
#[test]
fn config_uses_agent_assignment_model_path() {
    let temp_dir = tempfile::tempdir().unwrap();
    let model_path = temp_dir.path().join("assigned.gguf");
    std::fs::write(&model_path, "model").unwrap();
    let preferences = AppPreferences {
        models: vec![ModelEntry {
            model_id: "agent-assigned".to_string(),
            name: "assigned".to_string(),
            path: model_path.to_string_lossy().into_owned(),
            source: "manual".to_string(),
            runtime: "llama_cpp".to_string(),
            model_kind: "agent_llm".to_string(),
            path_kind: "file".to_string(),
            file_exists: true,
            created_at: "2026-05-17T00:00:00.000Z".to_string(),
            updated_at: "2026-05-17T00:00:00.000Z".to_string(),
        }],
        model_assignments: ModelAssignments {
            agent_chat_model_id: Some("agent-assigned".to_string()),
            speech_to_text_model_id: None,
        },
        default_model_id: None,
        ..AppPreferences::default()
    };

    assert_eq!(default_model_path(&preferences), Some(model_path));
}
```

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml llama_runtime_tests::config_uses_agent_assignment_model_path
```

Expected: PASS after Task 1. This protects the runtime path indirectly.

- [ ] **Step 2: Update runtime imports**

In `src-tauri/src/llama_runtime.rs`, update the import to use `agent_model_path`:

```rust
use crate::preferences::{
    agent_model_path, load_preferences_with_model_recovery, model_recovery_candidate_dirs,
    previous_preferences_path_for_current_path, save_preferences_to_path,
};
```

Update `config_for_app` so preference resolution uses:

```rust
let preference_model_path = agent_model_path(&preferences);
Ok(LlamaRuntimeConfig::from_env_with_preference(preference_model_path))
```

- [ ] **Step 3: Update PowerShell script test**

In `scripts/test-dev-model-env.ps1`, change the fake preferences object to include:

```powershell
modelAssignments = @{
    agentChatModelId = "model-1"
    speechToTextModelId = $null
}
defaultModelId = $null
```

Keep the existing assertion:

```powershell
if ($env:ALITA_LLAMA_MODEL_PATH -ne $modelPath) {
    throw "Expected ALITA_LLAMA_MODEL_PATH to be '$modelPath', got '$env:ALITA_LLAMA_MODEL_PATH'"
}
```

- [ ] **Step 4: Update development script assignment lookup**

In `scripts/dev-model-env.ps1`, replace:

```powershell
$defaultModelId = $preferences.defaultModelId
```

with:

```powershell
$defaultModelId = $preferences.modelAssignments.agentChatModelId
if ([string]::IsNullOrWhiteSpace($defaultModelId)) {
    $defaultModelId = $preferences.defaultModelId
}
```

- [ ] **Step 5: Update runbook**

In `docs/windows-desktop-runbook.md`, revise the ASR section to say:

```markdown
首选项中的“模型库”是本地模型的正常配置入口。Agent 模型使用 GGUF 文件，语音转文字模型使用 Qwen3-ASR-1.7B 模型目录。开发时仍可用 `ALITA_LLAMA_MODEL_PATH` 或 `ALITA_ASR_MODEL_PATH` 临时覆盖首选项配置。
```

- [ ] **Step 6: Run script and runtime tests**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test-dev-model-env.ps1
cargo test --manifest-path src-tauri/Cargo.toml llama_runtime_tests
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src-tauri/src/llama_runtime.rs src-tauri/tests/llama_runtime_tests.rs scripts/dev-model-env.ps1 scripts/test-dev-model-env.ps1 docs/windows-desktop-runbook.md
git commit -m "feat: resolve agent model assignment"
```

---

### Task 6: Final Verification And Compatibility Sweep

**Files:**
- No new production files.

- [ ] **Step 1: Run focused model library tests**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml preferences_tests agent_client_tests asr_tests llama_runtime_tests
npm run frontend:test -- src/features/preferences/PreferencesDialog.test.tsx src/features/voice/asrApi.test.ts src/features/voice/voiceSession.test.ts
python -m pytest python/tests/test_asr.py -q
powershell -ExecutionPolicy Bypass -File scripts/test-dev-model-env.ps1
```

Expected: all pass.

- [ ] **Step 2: Run full automated verification**

Run:

```powershell
npm run frontend:test
npm run frontend:lint
python -m pytest python/tests -q
cargo test --manifest-path src-tauri/Cargo.toml
```

Expected: all pass. If unrelated dirty workspace changes fail, capture the failing command and rerun the closest committed-scope tests from a clean tree or explain the unrelated failure explicitly.

- [ ] **Step 3: Manual smoke check**

Run:

```powershell
npm run desktop:dev
```

Manual checks:

- Open Preferences.
- Confirm “模型库” shows Agent and speech-to-text assignments.
- Add or reference a GGUF Agent model and assign it as Agent model.
- Add a Qwen3-ASR-1.7B directory and assign it as speech-to-text model.
- Restart the dev app and confirm the Agent model still resolves from the assignment.
- If a real Qwen ASR model is present, confirm the microphone enables and a short recording inserts transcript text into the draft.

- [ ] **Step 4: Final status check**

Run:

```powershell
git status --short
git log --oneline --decorate -10
```

Expected: committed model-library changes are present; unrelated pre-existing dirty files may still remain and must not be reverted.

---

## Final Verification

Before declaring implementation complete, run:

```powershell
npm run frontend:test
npm run frontend:lint
python -m pytest python/tests -q
cargo test --manifest-path src-tauri/Cargo.toml
```

Manual real-ASR verification requires a local Qwen3-ASR-1.7B directory selected in Preferences or supplied by `ALITA_ASR_MODEL_PATH`.
