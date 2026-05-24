use crate::tools::ToolManifest;
use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    fs,
    path::{Component, Path, PathBuf},
};
use uuid::Uuid;

const PREFERENCES_SCHEMA_VERSION: u32 = 3;

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

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ApiProviderConfig {
    pub provider_id: String,
    pub provider_type: String,
    pub display_name: String,
    pub base_url: String,
    pub model: String,
    pub credential_ref: String,
    pub enabled: bool,
    pub capabilities: Vec<String>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ApiProviderPreset {
    pub provider_type: String,
    pub display_name: String,
    pub base_url: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ApiProviderInput {
    pub provider_id: Option<String>,
    pub provider_type: String,
    pub display_name: String,
    pub base_url: String,
    pub model: String,
    pub enabled: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ModelAssignmentRole {
    AgentChat,
    SpeechToText,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
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
    #[serde(default = "default_agent_model_mode")]
    pub agent_model_mode: String,
    #[serde(default)]
    pub active_api_provider_id: Option<String>,
    #[serde(default)]
    pub api_provider_configs: Vec<ApiProviderConfig>,
    pub tool_enablement: HashMap<String, bool>,
}

impl Default for AppPreferences {
    fn default() -> Self {
        Self {
            schema_version: PREFERENCES_SCHEMA_VERSION,
            recent_projects: Vec::new(),
            model_directories: Vec::new(),
            model_storage_dir: String::new(),
            models: Vec::new(),
            default_model_id: None,
            model_assignments: ModelAssignments::default(),
            agent_model_mode: default_agent_model_mode(),
            active_api_provider_id: None,
            api_provider_configs: Vec::new(),
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

pub fn default_agent_model_mode() -> String {
    "local".to_string()
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
    pub runtime: Option<String>,
    pub package_name: Option<String>,
    pub package_source: Option<String>,
    pub upstream_url: Option<String>,
    pub capabilities: Vec<String>,
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
    let value: serde_json::Value = serde_json::from_str(&contents)
        .map_err(|error| format!("failed to parse preferences '{}': {error}", path.display()))?;
    let schema_version = value
        .get("schemaVersion")
        .and_then(|value| value.as_u64())
        .unwrap_or(1) as u32;

    let mut preferences: AppPreferences = match schema_version {
        1 | 2 | 3 => serde_json::from_value(value).map_err(|error| {
            format!("failed to parse preferences '{}': {error}", path.display())
        })?,
        version => return Err(format!("unsupported preferences schema version: {version}")),
    };

    if preferences.schema_version == 1 {
        migrate_preferences_v1_to_v2(&mut preferences);
    }
    normalize_preferences(&mut preferences);
    Ok(preferences)
}

fn migrate_preferences_v1_to_v2(preferences: &mut AppPreferences) {
    preferences.schema_version = PREFERENCES_SCHEMA_VERSION;
    if preferences.model_assignments.agent_chat_model_id.is_none() {
        preferences.model_assignments.agent_chat_model_id = preferences.default_model_id.clone();
    }
    for model in &mut preferences.models {
        model.model_kind = "agent_llm".to_string();
        model.runtime = "llama_cpp".to_string();
        model.path_kind = "file".to_string();
    }
}

fn normalize_preferences(preferences: &mut AppPreferences) {
    preferences.schema_version = PREFERENCES_SCHEMA_VERSION;
    if preferences.model_assignments.agent_chat_model_id.is_none() {
        preferences.model_assignments.agent_chat_model_id = preferences.default_model_id.clone();
    }
    preferences.default_model_id = preferences.model_assignments.agent_chat_model_id.clone();
    if !matches!(preferences.agent_model_mode.as_str(), "local" | "api") {
        preferences.agent_model_mode = default_agent_model_mode();
    }
    if let Some(active_provider_id) = preferences.active_api_provider_id.as_deref() {
        if !preferences
            .api_provider_configs
            .iter()
            .any(|provider| provider.provider_id == active_provider_id)
        {
            preferences.active_api_provider_id = None;
        }
    }
}

pub fn api_provider_credential_ref(provider_id: &str) -> String {
    format!("alita.api-provider.{provider_id}")
}

pub fn api_provider_preset(provider_type: &str) -> Result<ApiProviderPreset, String> {
    let preset = match provider_type {
        "openai" => ("openai", "OpenAI", "https://api.openai.com/v1"),
        "deepseek" => ("deepseek", "DeepSeek", "https://api.deepseek.com"),
        "kimi" => ("kimi", "Kimi", "https://api.moonshot.ai/v1"),
        "glm" => ("glm", "GLM", "https://open.bigmodel.cn/api/paas/v4"),
        "minimax" => ("minimax", "MiniMax", "https://api.minimax.io/v1"),
        "custom" => ("custom", "Custom API", ""),
        other => return Err(format!("unknown API provider type: {other}")),
    };
    Ok(ApiProviderPreset {
        provider_type: preset.0.to_string(),
        display_name: preset.1.to_string(),
        base_url: preset.2.to_string(),
    })
}

pub fn provider_default_capabilities(provider_type: &str) -> Vec<String> {
    match provider_type {
        "custom" => vec!["chat_completions".to_string(), "streaming".to_string()],
        _ => vec![
            "chat_completions".to_string(),
            "streaming".to_string(),
            "model_list".to_string(),
        ],
    }
}

pub fn normalize_api_provider_type(provider_type: &str) -> Result<String, String> {
    let provider_type = provider_type.trim().to_ascii_lowercase();
    if !matches!(
        provider_type.as_str(),
        "openai" | "deepseek" | "kimi" | "glm" | "minimax" | "custom"
    ) {
        return Err(format!("unknown API provider type: {provider_type}"));
    }

    Ok(provider_type)
}

pub fn normalize_api_provider_display_name(display_name: &str) -> Result<String, String> {
    let display_name = display_name.trim().to_string();
    if display_name.is_empty() {
        return Err("API provider display name is required".to_string());
    }

    Ok(display_name)
}

pub fn normalize_api_provider_model(model: &str) -> Result<String, String> {
    let model = model.trim().to_string();
    if model.is_empty() {
        return Err("API provider model name is required".to_string());
    }

    Ok(model)
}

pub fn normalize_api_provider_api_key(api_key: &str) -> Result<String, String> {
    let api_key = api_key.trim().to_string();
    if api_key.is_empty() {
        return Err("API provider API key is required".to_string());
    }

    Ok(api_key)
}

pub fn set_agent_model_mode(preferences: &mut AppPreferences, mode: &str) -> Result<(), String> {
    match mode {
        "local" | "api" => {
            preferences.agent_model_mode = mode.to_string();
            Ok(())
        }
        other => Err(format!("unknown agent model mode: {other}")),
    }
}

pub fn normalize_api_provider_base_url(base_url: &str) -> Result<String, String> {
    let base_url = base_url.trim().trim_end_matches('/');
    if base_url.is_empty() {
        return Err("API provider base URL is required".to_string());
    }

    let parsed_url = reqwest::Url::parse(base_url)
        .map_err(|_| "API provider base URL is invalid".to_string())?;
    validate_api_provider_base_url(&parsed_url)?;

    Ok(parsed_url.as_str().trim_end_matches('/').to_string())
}

fn validate_api_provider_base_url(url: &reqwest::Url) -> Result<(), String> {
    if url.scheme() != "http" && url.scheme() != "https" {
        return Err("API provider base URL must start with http:// or https://".to_string());
    }
    if !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err(
            "API provider base URL must not include credentials, query, or fragment".to_string(),
        );
    }
    if url.scheme() == "http" && !is_local_api_provider_host(url) {
        return Err(
            "API provider base URL must use HTTPS unless it points to localhost".to_string(),
        );
    }
    Ok(())
}

fn is_local_api_provider_host(url: &reqwest::Url) -> bool {
    let Some(host) = url.host_str() else {
        return false;
    };
    let host = host.trim_start_matches('[').trim_end_matches(']');
    host.eq_ignore_ascii_case("localhost")
        || host.eq_ignore_ascii_case("127.0.0.1")
        || host == "::1"
        || host.to_ascii_lowercase().ends_with(".localhost")
}

pub fn upsert_api_provider_config(
    preferences: &mut AppPreferences,
    input: ApiProviderInput,
) -> Result<ApiProviderConfig, String> {
    let provider_type = normalize_api_provider_type(&input.provider_type)?;
    let display_name = normalize_api_provider_display_name(&input.display_name)?;
    let base_url = normalize_api_provider_base_url(&input.base_url)?;
    let model = normalize_api_provider_model(&input.model)?;

    let now = Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true);
    if let Some(provider_id) = input.provider_id.as_deref() {
        let existing = preferences
            .api_provider_configs
            .iter_mut()
            .find(|provider| provider.provider_id == provider_id)
            .ok_or_else(|| format!("unknown API provider id: {provider_id}"))?;
        existing.provider_type = provider_type;
        existing.display_name = display_name;
        existing.base_url = base_url;
        existing.model = model;
        existing.enabled = input.enabled;
        existing.capabilities = provider_default_capabilities(&existing.provider_type);
        existing.updated_at = now;
        preferences.agent_model_mode = "api".to_string();
        return Ok(existing.clone());
    }

    let provider_id = Uuid::new_v4().to_string();
    let capabilities = provider_default_capabilities(&provider_type);
    let config = ApiProviderConfig {
        credential_ref: api_provider_credential_ref(&provider_id),
        provider_id: provider_id.clone(),
        provider_type,
        display_name,
        base_url,
        model,
        enabled: input.enabled,
        capabilities,
        created_at: now.clone(),
        updated_at: now,
    };
    preferences.api_provider_configs.push(config.clone());
    preferences.agent_model_mode = "api".to_string();
    if preferences.active_api_provider_id.is_none() {
        preferences.active_api_provider_id = Some(provider_id);
    }
    Ok(config)
}

pub fn set_active_api_provider(
    preferences: &mut AppPreferences,
    provider_id: Option<&str>,
) -> Result<(), String> {
    let Some(provider_id) = provider_id else {
        preferences.active_api_provider_id = None;
        return Ok(());
    };
    if !preferences
        .api_provider_configs
        .iter()
        .any(|provider| provider.provider_id == provider_id)
    {
        return Err(format!("unknown API provider id: {provider_id}"));
    }
    preferences.active_api_provider_id = Some(provider_id.to_string());
    preferences.agent_model_mode = "api".to_string();
    Ok(())
}

pub fn delete_api_provider_config(
    preferences: &mut AppPreferences,
    provider_id: &str,
) -> Result<ApiProviderConfig, String> {
    let index = preferences
        .api_provider_configs
        .iter()
        .position(|provider| provider.provider_id == provider_id)
        .ok_or_else(|| format!("unknown API provider id: {provider_id}"))?;
    let removed = preferences.api_provider_configs.remove(index);
    if preferences.active_api_provider_id.as_deref() == Some(provider_id) {
        preferences.active_api_provider_id = None;
    }
    Ok(removed)
}

pub fn load_preferences_with_model_recovery(
    preferences_path: impl AsRef<Path>,
    default_model_storage_dir: impl AsRef<Path>,
    previous_preferences_path: Option<&Path>,
    candidate_model_dirs: &[PathBuf],
) -> Result<(AppPreferences, bool), String> {
    let mut preferences = load_preferences_from_path(&preferences_path)?;
    let mut changed = ensure_model_storage_dir(&mut preferences, default_model_storage_dir)?;

    if needs_model_recovery(&preferences) {
        if let Some(previous_preferences_path) =
            previous_preferences_path.filter(|path| path.exists())
        {
            let previous_preferences = load_preferences_from_path(previous_preferences_path)?;
            changed |= recover_model_preferences(
                &mut preferences,
                &previous_preferences,
                candidate_model_dirs,
            )?;
        }
    }

    Ok((preferences, changed))
}

pub fn previous_preferences_path_for_current_path(path: impl AsRef<Path>) -> Option<PathBuf> {
    let app_config_parent = path.as_ref().parent()?.parent()?;
    Some(
        app_config_parent
            .join(previous_app_config_dir_name())
            .join("preferences.json"),
    )
}

pub fn model_recovery_candidate_dirs(
    default_model_storage_dir: impl AsRef<Path>,
    executable_path: Option<&Path>,
) -> Vec<PathBuf> {
    let mut candidate_dirs = Vec::new();
    push_unique_path(
        &mut candidate_dirs,
        default_model_storage_dir.as_ref().to_path_buf(),
    );

    if let Some(executable_path) = executable_path {
        for ancestor in executable_path.ancestors().skip(1) {
            push_unique_path(&mut candidate_dirs, ancestor.join("models"));
        }
    }

    candidate_dirs
}

pub fn save_preferences_to_path(
    path: impl AsRef<Path>,
    preferences: &AppPreferences,
) -> Result<(), String> {
    let path = path.as_ref();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| {
            format!(
                "failed to create preferences directory '{}': {error}",
                parent.display()
            )
        })?;
    }

    let serialized = serde_json::to_string_pretty(preferences)
        .map_err(|error| format!("failed to serialize preferences: {error}"))?;
    let temp_path = path.with_extension("json.tmp");
    fs::write(&temp_path, serialized)
        .map_err(|error| format!("failed to write preferences temp file: {error}"))?;
    if path.exists() {
        fs::remove_file(path)
            .map_err(|error| format!("failed to replace preferences file: {error}"))?;
    }
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
    add_or_update_typed_model(
        preferences,
        path,
        "manual",
        "speech_to_text",
        "qwen_asr",
        "directory",
    )
}

pub fn recover_model_preferences(
    preferences: &mut AppPreferences,
    previous_preferences: &AppPreferences,
    candidate_model_dirs: &[PathBuf],
) -> Result<bool, String> {
    if !needs_model_recovery(preferences) {
        return Ok(false);
    }

    let ordered_models = previous_models_default_first(previous_preferences);
    let mut changed = false;
    let mut recovered_default_model_id = None;

    for model in ordered_models {
        let Some(model_path) = recoverable_model_path(model, candidate_model_dirs) else {
            continue;
        };
        let recovered = add_or_update_model(preferences, &model_path, "recovered")?;
        changed = true;
        if previous_preferences.default_model_id.as_deref() == Some(model.model_id.as_str()) {
            recovered_default_model_id = Some(recovered.model_id);
        }
    }

    if let Some(model_id) = recovered_default_model_id {
        preferences.model_assignments.agent_chat_model_id = Some(model_id.clone());
        preferences.default_model_id = Some(model_id);
    }

    Ok(changed)
}

pub fn ensure_model_storage_dir(
    preferences: &mut AppPreferences,
    default_storage_dir: impl AsRef<Path>,
) -> Result<bool, String> {
    if preferences.model_storage_dir.trim().is_empty() {
        set_model_storage_dir(preferences, default_storage_dir)?;
        return Ok(true);
    }

    fs::create_dir_all(&preferences.model_storage_dir).map_err(|error| {
        format!(
            "failed to create model storage directory '{}': {error}",
            preferences.model_storage_dir
        )
    })?;
    Ok(false)
}

pub fn set_model_storage_dir(
    preferences: &mut AppPreferences,
    directory: impl AsRef<Path>,
) -> Result<(), String> {
    let directory = directory.as_ref();
    fs::create_dir_all(directory).map_err(|error| {
        format!(
            "failed to create model storage directory '{}': {error}",
            directory.display()
        )
    })?;
    preferences.model_storage_dir = directory.to_string_lossy().into_owned();
    Ok(())
}

pub fn import_model_to_storage(
    preferences: &mut AppPreferences,
    source_path: impl AsRef<Path>,
    storage_dir: impl AsRef<Path>,
) -> Result<ModelEntry, String> {
    let source_path = source_path.as_ref();
    if !source_path.is_file() {
        return Err(format!(
            "model file is not accessible: {}",
            source_path.display()
        ));
    }

    let is_gguf = source_path
        .extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| extension.eq_ignore_ascii_case("gguf"));
    if !is_gguf {
        return Err("only GGUF model files can be imported".to_string());
    }

    let file_name = source_path
        .file_name()
        .ok_or_else(|| format!("model file name is invalid: {}", source_path.display()))?;
    let storage_dir = storage_dir.as_ref();
    fs::create_dir_all(storage_dir).map_err(|error| {
        format!(
            "failed to create model storage directory '{}': {error}",
            storage_dir.display()
        )
    })?;

    let destination = unique_model_destination(storage_dir.join(file_name));
    if source_path != destination.as_path() {
        fs::copy(source_path, &destination).map_err(|error| {
            format!(
                "failed to import model '{}' to '{}': {error}",
                source_path.display(),
                destination.display()
            )
        })?;
    }

    add_or_update_model(preferences, &destination, "imported")
}

pub fn scan_model_directory(
    preferences: &mut AppPreferences,
    directory: impl AsRef<Path>,
) -> Result<usize, String> {
    let directory = directory.as_ref();
    if !directory.is_dir() {
        return Err(format!(
            "model directory is not accessible: {}",
            directory.display()
        ));
    }

    let directory_text = directory.to_string_lossy().into_owned();
    if !preferences.model_directories.contains(&directory_text) {
        preferences.model_directories.push(directory_text);
    }

    let mut count = 0;
    for entry in fs::read_dir(directory).map_err(|error| {
        format!(
            "failed to scan model directory '{}': {error}",
            directory.display()
        )
    })? {
        let entry =
            entry.map_err(|error| format!("failed to read model directory entry: {error}"))?;
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

pub fn set_default_model(
    preferences: &mut AppPreferences,
    model_id: Option<&str>,
) -> Result<(), String> {
    set_model_assignment(preferences, ModelAssignmentRole::AgentChat, model_id)
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

pub fn default_model_path(preferences: &AppPreferences) -> Option<PathBuf> {
    agent_model_path(preferences)
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
        preferences
            .model_assignments
            .speech_to_text_model_id
            .as_deref(),
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
    let default_model_id = model_id?;
    preferences
        .models
        .iter()
        .find(|model| {
            model.model_id == default_model_id
                && model.model_kind == model_kind
                && model.path_kind == path_kind
        })
        .map(|model| PathBuf::from(&model.path))
}

fn unique_model_destination(destination: PathBuf) -> PathBuf {
    if !destination.exists() {
        return destination;
    }

    let parent = destination
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(PathBuf::new);
    let stem = destination
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("model");
    let extension = destination
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or("gguf");

    for index in 1.. {
        let candidate = parent.join(format!("{stem}-{index}.{extension}"));
        if !candidate.exists() {
            return candidate;
        }
    }

    destination
}

fn needs_model_recovery(preferences: &AppPreferences) -> bool {
    default_model_path(preferences).is_none_or(|path| !path.is_file())
}

fn previous_models_default_first(preferences: &AppPreferences) -> Vec<&ModelEntry> {
    let mut models: Vec<_> = preferences.models.iter().collect();
    if let Some(default_model_id) = preferences.default_model_id.as_deref() {
        models.sort_by_key(|model| {
            if model.model_id == default_model_id {
                0
            } else {
                1
            }
        });
    }
    models
}

fn recoverable_model_path(model: &ModelEntry, candidate_model_dirs: &[PathBuf]) -> Option<PathBuf> {
    let previous_path = PathBuf::from(&model.path);
    if is_gguf_file(&previous_path) {
        return Some(previous_path);
    }

    if let Some(remapped_path) = remap_previous_project_path(&previous_path) {
        if is_gguf_file(&remapped_path) {
            return Some(remapped_path);
        }
    }

    let file_name = previous_path.file_name()?;
    for directory in candidate_model_dirs {
        let candidate = directory.join(file_name);
        if is_gguf_file(&candidate) {
            return Some(candidate);
        }
    }

    None
}

fn is_gguf_file(path: &Path) -> bool {
    path.is_file()
        && path
            .extension()
            .and_then(|extension| extension.to_str())
            .is_some_and(|extension| extension.eq_ignore_ascii_case("gguf"))
}

fn remap_previous_project_path(path: &Path) -> Option<PathBuf> {
    let previous_name = previous_project_dir_name();
    let mut changed = false;
    let mut remapped = PathBuf::new();

    for component in path.components() {
        match component {
            Component::Normal(value) if value.to_string_lossy() == previous_name => {
                remapped.push("Alita");
                changed = true;
            }
            _ => remapped.push(component.as_os_str()),
        }
    }

    changed.then_some(remapped)
}

fn previous_project_dir_name() -> String {
    ["Boo", "ook"].concat()
}

fn previous_app_config_dir_name() -> String {
    ["com.", "boo", "ook", ".ai-workbench"].concat()
}

fn push_unique_path(paths: &mut Vec<PathBuf>, path: PathBuf) {
    if !paths.iter().any(|existing| existing == &path) {
        paths.push(path);
    }
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
                runtime: manifest.runtime,
                package_name: manifest
                    .package
                    .as_ref()
                    .map(|package| package.name.clone()),
                package_source: manifest
                    .package
                    .as_ref()
                    .map(|package| package.source.clone()),
                upstream_url: manifest
                    .package
                    .as_ref()
                    .and_then(|package| package.upstream_url.clone()),
                capabilities: manifest.capabilities,
                permissions: manifest.permissions,
                valid: true,
                error: None,
            }),
            Err(error) => summaries.push(ToolSummary {
                tool_id: manifest_path.to_string_lossy().into_owned(),
                name: "无效工具 manifest".to_string(),
                description: "该工具 manifest 无法被解析。".to_string(),
                version: String::new(),
                source_type: String::new(),
                license: String::new(),
                runtime: None,
                package_name: None,
                package_source: None,
                upstream_url: None,
                capabilities: Vec::new(),
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
    preferences
        .tool_enablement
        .get(tool_id)
        .copied()
        .unwrap_or(true)
}

pub fn record_recent_project(preferences: &mut AppPreferences, project_path: &str) {
    preferences
        .recent_projects
        .retain(|existing| existing != project_path);
    preferences
        .recent_projects
        .insert(0, project_path.to_string());
    preferences.recent_projects.truncate(8);
}

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
        assign_first_model_for_kind(preferences, &entry, model_kind);
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
    assign_first_model_for_kind(preferences, &entry, model_kind);
    preferences.models.push(entry.clone());
    Ok(entry)
}

fn assign_first_model_for_kind(
    preferences: &mut AppPreferences,
    entry: &ModelEntry,
    model_kind: &str,
) {
    match model_kind {
        "agent_llm" if preferences.model_assignments.agent_chat_model_id.is_none() => {
            preferences.model_assignments.agent_chat_model_id = Some(entry.model_id.clone());
            preferences.default_model_id = Some(entry.model_id.clone());
        }
        "speech_to_text"
            if preferences
                .model_assignments
                .speech_to_text_model_id
                .is_none() =>
        {
            preferences.model_assignments.speech_to_text_model_id = Some(entry.model_id.clone());
        }
        _ => {}
    }
}

fn add_or_update_model(
    preferences: &mut AppPreferences,
    path: &Path,
    source: &str,
) -> Result<ModelEntry, String> {
    add_or_update_typed_model(preferences, path, source, "agent_llm", "llama_cpp", "file")
}
