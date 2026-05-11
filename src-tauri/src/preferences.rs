use crate::tools::ToolManifest;
use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    fs,
    path::{Component, Path, PathBuf},
};
use uuid::Uuid;

const PREFERENCES_SCHEMA_VERSION: u32 = 1;

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
    let Some(model_id) = model_id else {
        preferences.default_model_id = None;
        return Ok(());
    };

    let exists = preferences
        .models
        .iter()
        .any(|model| model.model_id == model_id);
    if !exists {
        return Err(format!("unknown model id: {model_id}"));
    }

    preferences.default_model_id = Some(model_id.to_string());
    Ok(())
}

pub fn default_model_path(preferences: &AppPreferences) -> Option<PathBuf> {
    let default_model_id = preferences.default_model_id.as_ref()?;
    preferences
        .models
        .iter()
        .find(|model| &model.model_id == default_model_id)
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

    if let Some(existing) = preferences
        .models
        .iter_mut()
        .find(|model| model.path == path_text)
    {
        existing.name = name;
        existing.source = source.to_string();
        existing.file_exists = file_exists;
        existing.updated_at = now;
        let entry = existing.clone();
        if preferences.default_model_id.is_none() {
            preferences.default_model_id = Some(entry.model_id.clone());
        }
        return Ok(entry);
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
    if preferences.default_model_id.is_none() {
        preferences.default_model_id = Some(entry.model_id.clone());
    }
    preferences.models.push(entry.clone());
    Ok(entry)
}
