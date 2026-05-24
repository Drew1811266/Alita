use crate::{
    agent_client::{
        AgentAttachment, AgentClient, AgentEvent, AgentMessageRequest, AsrStatusResponse,
        AsrTranscriptionRequest, AsrTranscriptionResponse,
    },
    api_credentials::{ApiCredentialStore, SystemApiCredentialStore},
    asr::{
        decode_wav_base64, remove_temp_audio_file, write_temp_audio_file,
        TranscribeVoiceAudioPayload,
    },
    preferences::{
        add_manual_model, add_speech_to_text_model, delete_api_provider_config,
        import_model_to_storage, load_preferences_with_model_recovery,
        model_recovery_candidate_dirs, previous_preferences_path_for_current_path,
        record_recent_project, save_preferences_to_path, scan_model_directory,
        set_active_api_provider, set_agent_model_mode, set_default_model, set_model_assignment,
        set_model_storage_dir, speech_to_text_model_path, summarize_tool_manifests,
        upsert_api_provider_config, ApiProviderInput, AppPreferences, ModelAssignmentRole,
        ToolSummary,
    },
    project::{
        load_project_from_path, new_project, save_project_to_path, AlitaProject, ProjectOpenResult,
    },
};
use serde::{Deserialize, Serialize};
use std::{
    fs::File,
    io::Read,
    path::{Path, PathBuf},
    process::Command,
};
use tauri::{AppHandle, Manager};
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SubmitAttachmentPayload {
    pub attachment_id: String,
    pub name: String,
    pub path: String,
    pub size_bytes: u64,
    pub mime_type: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SubmitMessagePayload {
    pub task_id: String,
    pub content: String,
    pub attachments: Vec<SubmitAttachmentPayload>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AttachmentMetadataPayload {
    pub paths: Vec<String>,
}

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
pub struct AddSpeechToTextModelPayload {
    pub path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ImportModelPayload {
    pub path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ScanModelDirectoryPayload {
    pub path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SetModelStorageDirectoryPayload {
    pub path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SetDefaultModelPayload {
    pub model_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SetModelAssignmentPayload {
    pub role: String,
    pub model_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SetAgentModelModePayload {
    pub mode: String,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SaveApiProviderPayload {
    pub provider_id: Option<String>,
    pub provider_type: String,
    pub display_name: String,
    pub base_url: String,
    pub model: String,
    pub enabled: bool,
    pub api_key: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ApiProviderIdPayload {
    pub provider_id: String,
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

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ArtifactTextPreview {
    pub path: String,
    pub file_name: String,
    pub size_bytes: u64,
    pub content: String,
    pub truncated: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArtifactLaunchCommand {
    pub program: String,
    pub args: Vec<String>,
}

const MAX_ARTIFACT_PREVIEW_BYTES: u64 = 256 * 1024;

pub fn open_artifact_command(path: &str) -> ArtifactLaunchCommand {
    #[cfg(windows)]
    {
        return ArtifactLaunchCommand {
            program: "cmd".to_string(),
            args: vec![
                "/C".to_string(),
                "start".to_string(),
                "".to_string(),
                path.to_string(),
            ],
        };
    }

    #[cfg(target_os = "macos")]
    {
        return ArtifactLaunchCommand {
            program: "open".to_string(),
            args: vec![path.to_string()],
        };
    }

    #[cfg(all(unix, not(target_os = "macos")))]
    {
        ArtifactLaunchCommand {
            program: "xdg-open".to_string(),
            args: vec![path.to_string()],
        }
    }
}

pub fn reveal_artifact_command(path: &str) -> ArtifactLaunchCommand {
    #[cfg(windows)]
    {
        return ArtifactLaunchCommand {
            program: "explorer".to_string(),
            args: vec![format!("/select,{path}")],
        };
    }

    #[cfg(target_os = "macos")]
    {
        return ArtifactLaunchCommand {
            program: "open".to_string(),
            args: vec!["-R".to_string(), path.to_string()],
        };
    }

    #[cfg(all(unix, not(target_os = "macos")))]
    {
        let parent = Path::new(path)
            .parent()
            .map(|value| value.to_string_lossy().to_string())
            .unwrap_or_else(|| path.to_string());
        ArtifactLaunchCommand {
            program: "xdg-open".to_string(),
            args: vec![parent],
        }
    }
}

#[tauri::command]
pub fn open_artifact(path: String) -> Result<(), String> {
    ensure_artifact_path_exists(&path)?;
    spawn_artifact_command(open_artifact_command(&path))
}

#[tauri::command]
pub fn reveal_artifact(path: String) -> Result<(), String> {
    ensure_artifact_path_exists(&path)?;
    spawn_artifact_command(reveal_artifact_command(&path))
}

#[tauri::command]
pub fn read_artifact_text(path: String) -> Result<ArtifactTextPreview, String> {
    read_artifact_preview_from_path(path, MAX_ARTIFACT_PREVIEW_BYTES)
}

pub fn read_artifact_preview_from_path(
    path: impl AsRef<Path>,
    max_bytes: u64,
) -> Result<ArtifactTextPreview, String> {
    let path = path.as_ref();
    let metadata = path
        .metadata()
        .map_err(|error| format!("failed to read artifact metadata: {error}"))?;
    if !metadata.is_file() {
        return Err(format!("artifact path is not a file: {}", path.display()));
    }

    let size_bytes = metadata.len();
    let truncated = size_bytes > max_bytes;
    let read_limit = if truncated { max_bytes } else { size_bytes };
    let mut bytes = Vec::with_capacity(read_limit as usize);
    File::open(path)
        .map_err(|error| format!("failed to open artifact: {error}"))?
        .take(read_limit)
        .read_to_end(&mut bytes)
        .map_err(|error| format!("failed to read artifact: {error}"))?;

    let content = decode_artifact_preview(&bytes)?;
    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("artifact")
        .to_string();

    Ok(ArtifactTextPreview {
        path: path.to_string_lossy().to_string(),
        file_name,
        size_bytes,
        content,
        truncated,
    })
}

fn decode_artifact_preview(bytes: &[u8]) -> Result<String, String> {
    match std::str::from_utf8(bytes) {
        Ok(content) => Ok(content.to_string()),
        Err(error) if error.error_len().is_none() => {
            Ok(std::str::from_utf8(&bytes[..error.valid_up_to()])
                .unwrap_or_default()
                .to_string())
        }
        Err(_) => Err("artifact preview only supports UTF-8 text files".to_string()),
    }
}

fn ensure_artifact_path_exists(path: &str) -> Result<(), String> {
    let artifact_path = Path::new(path);
    if artifact_path.exists() {
        Ok(())
    } else {
        Err(format!("artifact path does not exist: {path}"))
    }
}

fn spawn_artifact_command(command: ArtifactLaunchCommand) -> Result<(), String> {
    Command::new(&command.program)
        .args(&command.args)
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("failed to open artifact: {error}"))
}

#[tauri::command]
pub async fn submit_user_message(
    app: AppHandle,
    payload: SubmitMessagePayload,
) -> Result<Vec<AgentEvent>, String> {
    let client = AgentClient::new(crate::sidecar::agent_base_url())
        .with_auth_token(crate::sidecar::sidecar_auth_token(&app)?);
    let request = AgentMessageRequest {
        task_id: payload.task_id,
        content: payload.content,
        attachments: payload
            .attachments
            .into_iter()
            .map(|attachment| AgentAttachment {
                attachment_id: attachment.attachment_id,
                name: attachment.name,
                path: attachment.path,
                size_bytes: attachment.size_bytes,
                mime_type: attachment.mime_type,
            })
            .collect(),
    };

    client.send_message(&request).await
}

#[tauri::command]
pub async fn get_asr_status(app: AppHandle) -> Result<AsrStatusResponse, String> {
    let model_path = match configured_asr_model_path(&app)? {
        Some(path) => path,
        None => {
            return Ok(AsrStatusResponse {
                available: false,
                configured: false,
                model_path: None,
                message: "voice model is not configured".to_string(),
                error_code: Some("asr_not_configured".to_string()),
            });
        }
    };
    let model_path_text = model_path.to_string_lossy().to_string();
    let client = AgentClient::new(crate::sidecar::agent_base_url())
        .with_auth_token(crate::sidecar::sidecar_auth_token(&app)?);

    client
        .get_asr_status_for_model(Some(model_path_text.as_str()))
        .await
}

#[tauri::command]
pub async fn transcribe_voice_audio(
    app: AppHandle,
    payload: TranscribeVoiceAudioPayload,
) -> Result<AsrTranscriptionResponse, String> {
    let model_path = configured_asr_model_path(&app)?
        .ok_or_else(|| "voice model is not configured".to_string())?;
    let client = AgentClient::new(crate::sidecar::agent_base_url())
        .with_auth_token(crate::sidecar::sidecar_auth_token(&app)?);
    let audio_bytes = decode_wav_base64(&payload.wav_base64)?;
    let temp_audio_path = write_temp_audio_file(std::env::temp_dir(), &audio_bytes)?;
    let request = AsrTranscriptionRequest {
        audio_path: temp_audio_path.to_string_lossy().to_string(),
        language: "zh".to_string(),
        model_path: Some(model_path.to_string_lossy().to_string()),
    };

    let result = client.transcribe_asr_audio(&request).await;
    remove_temp_audio_file(&temp_audio_path);

    result
}

#[tauri::command]
pub fn get_sidecar_auth_token(app: AppHandle) -> Result<String, String> {
    crate::sidecar::sidecar_auth_token(&app)
}

#[tauri::command]
pub async fn get_attachment_metadata(
    payload: AttachmentMetadataPayload,
) -> Result<Vec<SubmitAttachmentPayload>, String> {
    payload
        .paths
        .iter()
        .map(attachment_metadata_for_path)
        .collect()
}

pub fn attachment_metadata_for_path(
    path: impl AsRef<Path>,
) -> Result<SubmitAttachmentPayload, String> {
    let path = path.as_ref();
    let metadata = path
        .metadata()
        .map_err(|error| format!("failed to read attachment metadata: {error}"))?;
    if !metadata.is_file() {
        return Err(format!("attachment path is not a file: {}", path.display()));
    }

    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| format!("attachment path has no valid file name: {}", path.display()))?
        .to_string();

    Ok(SubmitAttachmentPayload {
        attachment_id: format!("attachment-{}", Uuid::new_v4()),
        name,
        path: path.to_string_lossy().to_string(),
        size_bytes: metadata.len(),
        mime_type: infer_mime_type(path).to_string(),
    })
}

fn infer_mime_type(path: &Path) -> &'static str {
    let extension = path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();

    match extension.as_str() {
        "docx" => "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc" => "application/msword",
        "pdf" => "application/pdf",
        "txt" => "text/plain",
        "md" => "text/markdown",
        "rtf" => "application/rtf",
        "xlsx" => "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls" => "application/vnd.ms-excel",
        "pptx" => "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "ppt" => "application/vnd.ms-powerpoint",
        "csv" => "text/csv",
        "json" => "application/json",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "webp" => "image/webp",
        "gif" => "image/gif",
        "svg" => "image/svg+xml",
        "mp3" => "audio/mpeg",
        "wav" => "audio/wav",
        "m4a" => "audio/mp4",
        "mp4" => "video/mp4",
        "mov" => "video/quicktime",
        "webm" => "video/webm",
        _ => "application/octet-stream",
    }
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
    let result = load_project_from_path(&path).map_err(|error| error.to_string())?;
    record_recent_project_for_app(&app, &path)?;
    Ok(result)
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
    let (_, preferences) = load_preferences_for_app(&app)?;
    let tools = summarize_tool_manifests(packages_root(), &preferences);
    Ok(PreferencesView { preferences, tools })
}

#[tauri::command]
pub async fn set_agent_model_mode_command(
    app: AppHandle,
    payload: SetAgentModelModePayload,
) -> Result<PreferencesView, String> {
    let (path, mut preferences) = load_preferences_for_app(&app)?;
    set_agent_model_mode(&mut preferences, &payload.mode)?;
    save_preferences_to_path(&path, &preferences)?;
    let tools = summarize_tool_manifests(packages_root(), &preferences);
    Ok(PreferencesView { preferences, tools })
}

#[tauri::command]
pub async fn save_api_provider_config(
    app: AppHandle,
    payload: SaveApiProviderPayload,
) -> Result<PreferencesView, String> {
    let (path, mut preferences) = load_preferences_for_app(&app)?;
    save_api_provider_config_core(
        &mut preferences,
        payload,
        &SystemApiCredentialStore,
        |prefs| save_preferences_to_path(&path, prefs),
    )?;
    let tools = summarize_tool_manifests(packages_root(), &preferences);
    Ok(PreferencesView { preferences, tools })
}

pub fn save_api_provider_config_core<F>(
    preferences: &mut AppPreferences,
    payload: SaveApiProviderPayload,
    credential_store: &dyn ApiCredentialStore,
    save_preferences: F,
) -> Result<(), String>
where
    F: FnOnce(&AppPreferences) -> Result<(), String>,
{
    let SaveApiProviderPayload {
        provider_id,
        provider_type,
        display_name,
        base_url,
        model,
        enabled,
        api_key,
    } = payload;
    let provider = upsert_api_provider_config(
        preferences,
        ApiProviderInput {
            provider_id,
            provider_type,
            display_name,
            base_url,
            model,
            enabled,
        },
    )?;
    save_preferences(preferences)?;
    if let Some(api_key) = api_key.as_deref().filter(|value| !value.trim().is_empty()) {
        credential_store.set_api_key(&provider.credential_ref, api_key)?;
    }
    Ok(())
}

#[tauri::command]
pub async fn delete_api_provider_config_command(
    app: AppHandle,
    payload: ApiProviderIdPayload,
) -> Result<PreferencesView, String> {
    let (path, mut preferences) = load_preferences_for_app(&app)?;
    delete_api_provider_config_core(
        &mut preferences,
        &payload.provider_id,
        &SystemApiCredentialStore,
        |prefs| save_preferences_to_path(&path, prefs),
    )?;
    let tools = summarize_tool_manifests(packages_root(), &preferences);
    Ok(PreferencesView { preferences, tools })
}

pub fn delete_api_provider_config_core<F>(
    preferences: &mut AppPreferences,
    provider_id: &str,
    credential_store: &dyn ApiCredentialStore,
    save_preferences: F,
) -> Result<(), String>
where
    F: FnOnce(&AppPreferences) -> Result<(), String>,
{
    let removed = delete_api_provider_config(preferences, provider_id)?;
    save_preferences(preferences)?;
    credential_store.delete_api_key(&removed.credential_ref)?;
    Ok(())
}

#[tauri::command]
pub async fn set_active_api_provider_command(
    app: AppHandle,
    payload: ApiProviderIdPayload,
) -> Result<PreferencesView, String> {
    let (path, mut preferences) = load_preferences_for_app(&app)?;
    set_active_api_provider(&mut preferences, Some(&payload.provider_id))?;
    save_preferences_to_path(&path, &preferences)?;
    let tools = summarize_tool_manifests(packages_root(), &preferences);
    Ok(PreferencesView { preferences, tools })
}

#[tauri::command]
pub async fn add_model_file(
    app: AppHandle,
    payload: AddModelPayload,
) -> Result<PreferencesView, String> {
    let (path, mut preferences) = load_preferences_for_app(&app)?;
    add_manual_model(&mut preferences, PathBuf::from(payload.path))?;
    save_preferences_to_path(&path, &preferences)?;
    let tools = summarize_tool_manifests(packages_root(), &preferences);
    Ok(PreferencesView { preferences, tools })
}

#[tauri::command]
pub async fn add_speech_to_text_model_directory(
    app: AppHandle,
    payload: AddSpeechToTextModelPayload,
) -> Result<PreferencesView, String> {
    let (path, mut preferences) = load_preferences_for_app(&app)?;
    add_speech_to_text_model(&mut preferences, PathBuf::from(payload.path))?;
    save_preferences_to_path(&path, &preferences)?;
    let tools = summarize_tool_manifests(packages_root(), &preferences);
    Ok(PreferencesView { preferences, tools })
}

#[tauri::command]
pub async fn import_model_file(
    app: AppHandle,
    payload: ImportModelPayload,
) -> Result<PreferencesView, String> {
    let (path, mut preferences) = load_preferences_for_app(&app)?;
    let storage_dir = PathBuf::from(&preferences.model_storage_dir);
    import_model_to_storage(&mut preferences, PathBuf::from(payload.path), storage_dir)?;
    save_preferences_to_path(&path, &preferences)?;
    let tools = summarize_tool_manifests(packages_root(), &preferences);
    Ok(PreferencesView { preferences, tools })
}

#[tauri::command]
pub async fn scan_model_directory_command(
    app: AppHandle,
    payload: ScanModelDirectoryPayload,
) -> Result<PreferencesView, String> {
    let (path, mut preferences) = load_preferences_for_app(&app)?;
    scan_model_directory(&mut preferences, PathBuf::from(payload.path))?;
    save_preferences_to_path(&path, &preferences)?;
    let tools = summarize_tool_manifests(packages_root(), &preferences);
    Ok(PreferencesView { preferences, tools })
}

#[tauri::command]
pub async fn set_model_storage_directory(
    app: AppHandle,
    payload: SetModelStorageDirectoryPayload,
) -> Result<PreferencesView, String> {
    let (path, mut preferences) = load_preferences_for_app(&app)?;
    set_model_storage_dir(&mut preferences, PathBuf::from(payload.path))?;
    save_preferences_to_path(&path, &preferences)?;
    let tools = summarize_tool_manifests(packages_root(), &preferences);
    Ok(PreferencesView { preferences, tools })
}

#[tauri::command]
pub async fn set_default_model_command(
    app: AppHandle,
    payload: SetDefaultModelPayload,
) -> Result<PreferencesView, String> {
    let (path, mut preferences) = load_preferences_for_app(&app)?;
    set_default_model(&mut preferences, payload.model_id.as_deref())?;
    save_preferences_to_path(&path, &preferences)?;
    let tools = summarize_tool_manifests(packages_root(), &preferences);
    Ok(PreferencesView { preferences, tools })
}

#[tauri::command]
pub async fn set_model_assignment_command(
    app: AppHandle,
    payload: SetModelAssignmentPayload,
) -> Result<PreferencesView, String> {
    let role = model_assignment_role_from_payload(&payload.role)?;
    let (path, mut preferences) = load_preferences_for_app(&app)?;
    set_model_assignment(&mut preferences, role, payload.model_id.as_deref())?;
    save_preferences_to_path(&path, &preferences)?;
    let tools = summarize_tool_manifests(packages_root(), &preferences);
    Ok(PreferencesView { preferences, tools })
}

pub fn model_assignment_role_from_payload(role: &str) -> Result<ModelAssignmentRole, String> {
    match role {
        "agentChat" => Ok(ModelAssignmentRole::AgentChat),
        "speechToText" => Ok(ModelAssignmentRole::SpeechToText),
        unknown => Err(format!("unknown model assignment role: {unknown}")),
    }
}

#[tauri::command]
pub async fn set_tool_enabled(
    app: AppHandle,
    payload: SetToolEnabledPayload,
) -> Result<PreferencesView, String> {
    let (path, mut preferences) = load_preferences_for_app(&app)?;
    preferences
        .tool_enablement
        .insert(payload.tool_id, payload.enabled);
    save_preferences_to_path(&path, &preferences)?;
    let tools = summarize_tool_manifests(packages_root(), &preferences);
    Ok(PreferencesView { preferences, tools })
}

fn preferences_path(app: &AppHandle) -> Result<PathBuf, String> {
    let config_dir = app
        .path()
        .app_config_dir()
        .map_err(|error| format!("failed to resolve app config dir: {error}"))?;
    Ok(config_dir.join("preferences.json"))
}

fn default_model_storage_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let local_data_dir = app
        .path()
        .app_local_data_dir()
        .map_err(|error| format!("failed to resolve app local data dir: {error}"))?;
    Ok(local_data_dir.join("models"))
}

fn load_preferences_for_app(app: &AppHandle) -> Result<(PathBuf, AppPreferences), String> {
    let path = preferences_path(app)?;
    let default_storage_dir = default_model_storage_dir(app)?;
    let previous_path = previous_preferences_path_for_current_path(&path);
    let executable_path = std::env::current_exe().ok();
    let candidate_model_dirs =
        model_recovery_candidate_dirs(&default_storage_dir, executable_path.as_deref());
    let (preferences, changed) = load_preferences_with_model_recovery(
        &path,
        &default_storage_dir,
        previous_path.as_deref(),
        &candidate_model_dirs,
    )?;
    if changed {
        save_preferences_to_path(&path, &preferences)?;
    }
    Ok((path, preferences))
}

fn configured_asr_model_path(app: &AppHandle) -> Result<Option<PathBuf>, String> {
    if let Ok(value) = std::env::var("ALITA_ASR_MODEL_PATH") {
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            return Ok(Some(PathBuf::from(trimmed)));
        }
    }
    let (_, preferences) = load_preferences_for_app(app)?;
    Ok(speech_to_text_model_path(&preferences))
}

fn packages_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("tool-packages")
}

fn record_recent_project_for_app(app: &AppHandle, project_path: &str) -> Result<(), String> {
    let (path, mut preferences) = load_preferences_for_app(app)?;
    record_recent_project(&mut preferences, project_path);
    save_preferences_to_path(&path, &preferences)
}
