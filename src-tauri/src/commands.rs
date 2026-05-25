use crate::{
    agent_client::{
        AgentAttachment, AgentClient, AgentEvent, AgentMessageRequest, AsrStatusResponse,
        AsrTranscriptionRequest, AsrTranscriptionResponse, InquiryChoice,
        RegisterModelSessionRequest,
    },
    agent_model_config::{resolve_agent_model_config, AgentModelConfig},
    api_credentials::{ApiCredentialStore, ApiCredentialTarget, SystemApiCredentialStore},
    asr::{
        decode_wav_base64, remove_temp_audio_file, write_temp_audio_file,
        TranscribeVoiceAudioPayload,
    },
    preferences::{
        add_manual_model, add_speech_to_text_model, delete_api_provider_config,
        import_model_to_storage, load_preferences_with_model_recovery,
        model_recovery_candidate_dirs, normalize_api_provider_api_key,
        normalize_api_provider_base_url, normalize_api_provider_display_name,
        normalize_api_provider_model, normalize_api_provider_type,
        previous_preferences_path_for_current_path, record_recent_project,
        save_preferences_to_path, scan_model_directory, set_active_api_provider,
        set_agent_model_mode, set_default_model, set_model_assignment, set_model_storage_dir,
        speech_to_text_model_path, summarize_tool_manifests, upsert_api_provider_config,
        ApiProviderInput, AppPreferences, ModelAssignmentRole, ToolSummary,
    },
    project::{
        load_project_from_path, new_project, save_project_to_path, AlitaProject, ProjectOpenResult,
    },
};
use serde::{Deserialize, Serialize};
use std::{
    fmt,
    fs::File,
    io::Read,
    path::{Path, PathBuf},
    process::Command,
    time::Duration,
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
    #[serde(skip_serializing_if = "Option::is_none")]
    pub inquiry_choice: Option<InquiryChoice>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub current_graph: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub has_run_history: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub artifact_refs: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pending_choice: Option<serde_json::Value>,
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

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct PrepareAgentModelSessionResponse {
    pub model_session_id: String,
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

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TestApiProviderPayload {
    pub provider_id: Option<String>,
    pub provider_type: String,
    pub display_name: String,
    pub base_url: String,
    pub model: String,
    pub api_key: Option<String>,
}

impl fmt::Debug for TestApiProviderPayload {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("TestApiProviderPayload")
            .field("provider_id", &self.provider_id)
            .field("provider_type", &self.provider_type)
            .field("display_name", &self.display_name)
            .field("base_url", &self.base_url)
            .field("model", &self.model)
            .field("api_key", &self.api_key.as_ref().map(|_| "<redacted>"))
            .finish()
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ApiProviderConnectionResult {
    pub ok: bool,
    pub message: String,
    pub models: Vec<String>,
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

pub fn preferences_view_with_api_key_status(
    mut preferences: AppPreferences,
    tools: Vec<ToolSummary>,
    credential_store: &dyn ApiCredentialStore,
) -> PreferencesView {
    for provider in &mut preferences.api_provider_configs {
        let key_result = match api_credential_target_for_provider(provider) {
            Ok(target) => credential_store.get_api_key(&provider.credential_ref, &target),
            Err(error) => Err(error),
        };
        match key_result {
            Ok(Some(api_key)) if !api_key.trim().is_empty() => {
                provider.has_api_key = Some(true);
                provider.api_key_status = Some("configured".to_string());
            }
            Ok(_) => {
                provider.has_api_key = Some(false);
                provider.api_key_status = Some("missing".to_string());
            }
            Err(_) => {
                provider.has_api_key = Some(false);
                provider.api_key_status = Some("unknown".to_string());
            }
        }
    }

    PreferencesView { preferences, tools }
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
const API_PROVIDER_TEST_TIMEOUT: Duration = Duration::from_secs(10);
const API_PROVIDER_SUCCESS_BODY_READ_LIMIT: usize = 256 * 1024;
const API_PROVIDER_ERROR_BODY_READ_LIMIT: usize = 4096;
const API_PROVIDER_ERROR_BODY_LIMIT: usize = 512;
const API_PROVIDER_KEY_PREFIX_REDACTION_MIN_BYTES: usize = 8;

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
    let request = agent_message_request_from_payload(payload);

    client.send_message(&request).await
}

pub fn agent_message_request_from_payload(payload: SubmitMessagePayload) -> AgentMessageRequest {
    AgentMessageRequest {
        task_id: payload.task_id,
        content: payload.content,
        inquiry_choice: payload.inquiry_choice,
        current_graph: payload.current_graph,
        has_run_history: payload.has_run_history,
        artifact_refs: payload.artifact_refs,
        pending_choice: payload.pending_choice,
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
    }
}

#[tauri::command]
pub async fn prepare_agent_model_session(
    app: AppHandle,
) -> Result<PrepareAgentModelSessionResponse, String> {
    let (_, preferences) = load_preferences_for_app(&app)?;
    let config = validate_agent_model_session_config(resolve_agent_model_config(
        &preferences,
        &SystemApiCredentialStore,
    )?)?;
    let request = RegisterModelSessionRequest {
        model_config: serde_json::to_value(config)
            .map_err(|error| format!("failed to serialize model config: {error}"))?,
    };
    let client = AgentClient::new(crate::sidecar::agent_base_url())
        .with_auth_token(crate::sidecar::sidecar_auth_token(&app)?);
    let response = client.register_model_session(&request).await?;
    Ok(PrepareAgentModelSessionResponse {
        model_session_id: response.model_session_id,
    })
}

fn validate_agent_model_session_config(
    config: AgentModelConfig,
) -> Result<AgentModelConfig, String> {
    match config {
        AgentModelConfig::Api {
            provider_id,
            provider_type,
            display_name,
            base_url,
            model,
            api_key,
        } => Ok(AgentModelConfig::Api {
            provider_id,
            provider_type,
            display_name,
            base_url: normalize_api_provider_base_url(&base_url)?,
            model,
            api_key,
        }),
        local => Ok(local),
    }
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

#[tauri::command]
pub async fn test_api_provider_connection(
    app: AppHandle,
    payload: TestApiProviderPayload,
) -> Result<ApiProviderConnectionResult, String> {
    let payload = api_provider_test_payload_for_app(&app, payload, &SystemApiCredentialStore)?;
    Ok(test_api_provider_connection_core(payload).await)
}

#[tauri::command]
pub async fn fetch_api_provider_models(
    app: AppHandle,
    payload: TestApiProviderPayload,
) -> Result<ApiProviderConnectionResult, String> {
    let payload = api_provider_test_payload_for_app(&app, payload, &SystemApiCredentialStore)?;
    Ok(fetch_api_provider_models_core(payload).await)
}

fn api_provider_test_payload_for_app(
    app: &AppHandle,
    payload: TestApiProviderPayload,
    credential_store: &dyn ApiCredentialStore,
) -> Result<TestApiProviderPayload, String> {
    if payload.api_key.is_some() {
        return Ok(payload);
    }
    if payload.provider_id.is_none() {
        return Ok(payload);
    }
    let (_, preferences) = load_preferences_for_app(app)?;
    api_provider_test_payload_with_stored_key(&preferences, payload, credential_store)
}

pub fn api_provider_test_payload_with_stored_key(
    preferences: &AppPreferences,
    mut payload: TestApiProviderPayload,
    credential_store: &dyn ApiCredentialStore,
) -> Result<TestApiProviderPayload, String> {
    if payload.api_key.is_some() {
        return Ok(payload);
    }
    let Some(provider_id) = payload.provider_id.as_deref() else {
        return Ok(payload);
    };
    let provider = preferences
        .api_provider_configs
        .iter()
        .find(|candidate| candidate.provider_id == provider_id)
        .ok_or_else(|| format!("unknown API provider id: {provider_id}"))?;
    validate_api_provider_stored_key_target(provider, &payload)?;
    let credential_target = api_credential_target_for_provider(provider)?;
    payload.api_key = credential_store.get_api_key(&provider.credential_ref, &credential_target)?;
    Ok(payload)
}

fn validate_api_provider_stored_key_target(
    provider: &crate::preferences::ApiProviderConfig,
    payload: &TestApiProviderPayload,
) -> Result<(), String> {
    let payload_provider_type = normalize_api_provider_type(&payload.provider_type)?;
    let payload_base_url = normalize_api_provider_base_url(&payload.base_url)?;
    if payload_provider_type == provider.provider_type && payload_base_url == provider.base_url {
        return Ok(());
    }

    Err("API key is required when provider connection settings are changed".to_string())
}

fn api_credential_target_for_provider(
    provider: &crate::preferences::ApiProviderConfig,
) -> Result<ApiCredentialTarget, String> {
    let provider_type = normalize_api_provider_type(&provider.provider_type)?;
    let base_url = normalize_api_provider_base_url(&provider.base_url)?;
    ApiCredentialTarget::new(&provider_type, &base_url)
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
    Ok(preferences_view_with_api_key_status(
        preferences,
        tools,
        &SystemApiCredentialStore,
    ))
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
    Ok(preferences_view_with_api_key_status(
        preferences,
        tools,
        &SystemApiCredentialStore,
    ))
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
    Ok(preferences_view_with_api_key_status(
        preferences,
        tools,
        &SystemApiCredentialStore,
    ))
}

pub fn save_api_provider_config_core<F>(
    preferences: &mut AppPreferences,
    payload: SaveApiProviderPayload,
    credential_store: &dyn ApiCredentialStore,
    mut save_preferences: F,
) -> Result<(), String>
where
    F: FnMut(&AppPreferences) -> Result<(), String>,
{
    let original_preferences = preferences.clone();
    let SaveApiProviderPayload {
        provider_id,
        provider_type,
        display_name,
        base_url,
        model,
        enabled,
        api_key,
    } = payload;
    let is_existing_provider = provider_id.as_deref().is_some_and(|provider_id| {
        preferences
            .api_provider_configs
            .iter()
            .any(|provider| provider.provider_id == provider_id)
    });
    let api_key = match api_key.as_deref() {
        Some(api_key) => Some(normalize_api_provider_api_key(api_key)?),
        None if is_existing_provider => {
            validate_saved_api_provider_update_target(
                preferences,
                provider_id.as_deref(),
                &provider_type,
                &base_url,
            )?;
            None
        }
        None => return Err("API provider API key is required".to_string()),
    };
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
    if let Some(api_key) = api_key.as_deref() {
        let credential_target = api_credential_target_for_provider(&provider)?;
        if let Err(error) =
            credential_store.set_api_key(&provider.credential_ref, &credential_target, api_key)
        {
            return rollback_preferences_after_credential_error(
                preferences,
                original_preferences,
                &mut save_preferences,
                error,
            );
        }
    }
    Ok(())
}

fn validate_saved_api_provider_update_target(
    preferences: &AppPreferences,
    provider_id: Option<&str>,
    provider_type: &str,
    base_url: &str,
) -> Result<(), String> {
    let Some(provider_id) = provider_id else {
        return Ok(());
    };
    let provider = preferences
        .api_provider_configs
        .iter()
        .find(|candidate| candidate.provider_id == provider_id)
        .ok_or_else(|| format!("unknown API provider id: {provider_id}"))?;
    let provider_type = normalize_api_provider_type(provider_type)?;
    let base_url = normalize_api_provider_base_url(base_url)?;
    if provider.provider_type == provider_type && provider.base_url == base_url {
        return Ok(());
    }

    Err("API key is required when provider connection settings are changed".to_string())
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
    Ok(preferences_view_with_api_key_status(
        preferences,
        tools,
        &SystemApiCredentialStore,
    ))
}

pub fn delete_api_provider_config_core<F>(
    preferences: &mut AppPreferences,
    provider_id: &str,
    credential_store: &dyn ApiCredentialStore,
    mut save_preferences: F,
) -> Result<(), String>
where
    F: FnMut(&AppPreferences) -> Result<(), String>,
{
    let original_preferences = preferences.clone();
    let removed = delete_api_provider_config(preferences, provider_id)?;
    save_preferences(preferences)?;
    if let Err(error) = credential_store.delete_api_key(&removed.credential_ref) {
        return rollback_preferences_after_credential_error(
            preferences,
            original_preferences,
            &mut save_preferences,
            error,
        );
    }
    Ok(())
}

fn rollback_preferences_after_credential_error<F>(
    preferences: &mut AppPreferences,
    original_preferences: AppPreferences,
    save_preferences: &mut F,
    credential_error: String,
) -> Result<(), String>
where
    F: FnMut(&AppPreferences) -> Result<(), String>,
{
    *preferences = original_preferences;
    match save_preferences(preferences) {
        Ok(()) => Err(credential_error),
        Err(rollback_error) => Err(format!(
            "API credential operation failed after preferences were saved: {credential_error}; \
             failed to roll back preferences: {rollback_error}"
        )),
    }
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
    Ok(preferences_view_with_api_key_status(
        preferences,
        tools,
        &SystemApiCredentialStore,
    ))
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
    Ok(preferences_view_with_api_key_status(
        preferences,
        tools,
        &SystemApiCredentialStore,
    ))
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
    Ok(preferences_view_with_api_key_status(
        preferences,
        tools,
        &SystemApiCredentialStore,
    ))
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
    Ok(preferences_view_with_api_key_status(
        preferences,
        tools,
        &SystemApiCredentialStore,
    ))
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
    Ok(preferences_view_with_api_key_status(
        preferences,
        tools,
        &SystemApiCredentialStore,
    ))
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
    Ok(preferences_view_with_api_key_status(
        preferences,
        tools,
        &SystemApiCredentialStore,
    ))
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
    Ok(preferences_view_with_api_key_status(
        preferences,
        tools,
        &SystemApiCredentialStore,
    ))
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
    Ok(preferences_view_with_api_key_status(
        preferences,
        tools,
        &SystemApiCredentialStore,
    ))
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
    Ok(preferences_view_with_api_key_status(
        preferences,
        tools,
        &SystemApiCredentialStore,
    ))
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

struct PreparedApiProviderTest {
    base_url: reqwest::Url,
    model: String,
    api_key: String,
}

async fn test_api_provider_connection_core(
    payload: TestApiProviderPayload,
) -> ApiProviderConnectionResult {
    let prepared = match prepare_api_provider_test_payload(payload) {
        Ok(prepared) => prepared,
        Err(message) => return api_provider_connection_failure(message),
    };
    let http = match reqwest::Client::builder()
        .timeout(API_PROVIDER_TEST_TIMEOUT)
        .redirect(reqwest::redirect::Policy::none())
        .build()
    {
        Ok(http) => http,
        Err(error) => {
            return api_provider_connection_failure(redact_api_provider_secret(
                format!("failed to create provider test client: {error}"),
                Some(&prepared.api_key),
            ));
        }
    };

    match fetch_openai_models(&http, &prepared).await {
        Ok(models) => api_provider_model_list_result(&prepared.model, models),
        Err(model_list_error) => match probe_openai_chat_completion(&http, &prepared).await {
            Ok(()) => ApiProviderConnectionResult {
                ok: true,
                message: "Connection successful; model listing is unavailable".to_string(),
                models: vec![prepared.model],
            },
            Err(probe_error) => {
                let message = format!(
                    "Provider test failed. Model listing: {model_list_error}; chat completion probe: {probe_error}"
                );
                api_provider_connection_failure(redact_api_provider_secret(
                    message,
                    Some(&prepared.api_key),
                ))
            }
        },
    }
}

async fn fetch_api_provider_models_core(
    payload: TestApiProviderPayload,
) -> ApiProviderConnectionResult {
    let prepared = match prepare_api_provider_fetch_models_payload(payload) {
        Ok(prepared) => prepared,
        Err(message) => return api_provider_connection_failure(message),
    };
    let http = match reqwest::Client::builder()
        .timeout(API_PROVIDER_TEST_TIMEOUT)
        .redirect(reqwest::redirect::Policy::none())
        .build()
    {
        Ok(http) => http,
        Err(error) => {
            return api_provider_connection_failure(redact_api_provider_secret(
                format!("failed to create provider model client: {error}"),
                Some(&prepared.api_key),
            ));
        }
    };

    match fetch_openai_models(&http, &prepared).await {
        Ok(models) => ApiProviderConnectionResult {
            ok: true,
            message: "Model list fetched successfully".to_string(),
            models,
        },
        Err(error) => api_provider_connection_failure(redact_api_provider_secret(
            format!("Model list fetch failed: {error}"),
            Some(&prepared.api_key),
        )),
    }
}

fn prepare_api_provider_test_payload(
    payload: TestApiProviderPayload,
) -> Result<PreparedApiProviderTest, String> {
    prepare_api_provider_payload(payload, false)
}

fn prepare_api_provider_fetch_models_payload(
    payload: TestApiProviderPayload,
) -> Result<PreparedApiProviderTest, String> {
    prepare_api_provider_payload(payload, true)
}

fn prepare_api_provider_payload(
    payload: TestApiProviderPayload,
    allow_blank_model: bool,
) -> Result<PreparedApiProviderTest, String> {
    normalize_api_provider_type(&payload.provider_type)
        .map_err(|error| redact_api_provider_secret(error, payload.api_key.as_deref()))?;
    normalize_api_provider_display_name(&payload.display_name)?;

    let base_url = normalize_api_provider_base_url(&payload.base_url)?;
    let mut parsed_url = reqwest::Url::parse(&base_url)
        .map_err(|_| "API provider base URL is invalid".to_string())?;
    if !parsed_url.path().ends_with('/') {
        let mut path = parsed_url.path().to_string();
        path.push('/');
        parsed_url.set_path(&path);
    }

    let model = if allow_blank_model && payload.model.trim().is_empty() {
        String::new()
    } else {
        normalize_api_provider_model(&payload.model)?
    };
    let api_key = normalize_api_provider_api_key(payload.api_key.as_deref().unwrap_or_default())?;

    Ok(PreparedApiProviderTest {
        base_url: parsed_url,
        model,
        api_key,
    })
}

fn api_provider_model_list_result(
    selected_model: &str,
    models: Vec<String>,
) -> ApiProviderConnectionResult {
    if models.iter().any(|model| model == selected_model) {
        return ApiProviderConnectionResult {
            ok: true,
            message: "Connection successful".to_string(),
            models,
        };
    }

    api_provider_connection_failure("selected model was not found in the provider model list")
}

async fn fetch_openai_models(
    http: &reqwest::Client,
    prepared: &PreparedApiProviderTest,
) -> Result<Vec<String>, String> {
    let models_url = prepared
        .base_url
        .join("models")
        .map_err(|_| "model list request URL is invalid".to_string())?;
    let response = http
        .get(models_url)
        .bearer_auth(&prepared.api_key)
        .send()
        .await
        .map_err(|error| format!("model list request failed: {error}"))?;

    if !response.status().is_success() {
        return Err(api_provider_response_error(
            response,
            "model list request",
            Some(&prepared.api_key),
        )
        .await);
    }

    let (body, was_truncated) =
        read_api_provider_success_body(response, API_PROVIDER_SUCCESS_BODY_READ_LIMIT)
            .await
            .map_err(|error| format!("model list response read failed: {error}"))?;
    if was_truncated {
        return Err("model list response was too large".to_string());
    }

    let value = serde_json::from_slice::<serde_json::Value>(&body)
        .map_err(|error| format!("invalid model list response: {error}"))?;
    let models = parse_openai_model_ids(&value);
    if models.is_empty() {
        return Err("model list response did not include model ids".to_string());
    }
    Ok(models)
}

async fn probe_openai_chat_completion(
    http: &reqwest::Client,
    prepared: &PreparedApiProviderTest,
) -> Result<(), String> {
    let chat_url = prepared
        .base_url
        .join("chat/completions")
        .map_err(|_| "chat completion probe URL is invalid".to_string())?;
    let request = serde_json::json!({
        "model": prepared.model,
        "messages": [
            {
                "role": "user",
                "content": "ping"
            }
        ],
        "stream": false,
        "max_tokens": 1
    });
    let response = http
        .post(chat_url)
        .bearer_auth(&prepared.api_key)
        .json(&request)
        .send()
        .await
        .map_err(|error| format!("chat completion probe failed: {error}"))?;

    if !response.status().is_success() {
        return Err(api_provider_response_error(
            response,
            "chat completion probe",
            Some(&prepared.api_key),
        )
        .await);
    }

    let (body, was_truncated) =
        read_api_provider_success_body(response, API_PROVIDER_SUCCESS_BODY_READ_LIMIT)
            .await
            .map_err(|error| format!("chat completion probe response read failed: {error}"))?;
    if was_truncated {
        return Err("chat completion probe response was too large".to_string());
    }

    let value = serde_json::from_slice::<serde_json::Value>(&body)
        .map_err(|error| format!("invalid chat completion probe response: {error}"))?;
    if !is_valid_openai_chat_completion_response(&value) {
        return Err(
            "chat completion probe response did not include a valid completion choice".to_string(),
        );
    }

    Ok(())
}

async fn read_api_provider_success_body(
    mut response: reqwest::Response,
    limit: usize,
) -> Result<(Vec<u8>, bool), reqwest::Error> {
    if response
        .content_length()
        .is_some_and(|content_length| content_length > limit as u64)
    {
        return Ok((Vec::new(), true));
    }

    let mut bytes = Vec::new();
    loop {
        let Some(chunk) = response.chunk().await? else {
            return Ok((bytes, false));
        };
        let remaining = limit - bytes.len();
        if chunk.len() > remaining {
            bytes.extend_from_slice(&chunk[..remaining]);
            return Ok((bytes, true));
        }
        bytes.extend_from_slice(&chunk);
    }
}

async fn api_provider_response_error(
    response: reqwest::Response,
    label: &str,
    api_key: Option<&str>,
) -> String {
    let status = response.status();
    match read_api_provider_error_body(response).await {
        Ok((body, was_truncated)) => {
            api_provider_error_message(label, status, Some(&body), api_key, was_truncated)
        }
        _ => format!("{label} returned {status}"),
    }
}

async fn read_api_provider_error_body(
    mut response: reqwest::Response,
) -> Result<(String, bool), reqwest::Error> {
    let mut bytes = Vec::new();
    while bytes.len() < API_PROVIDER_ERROR_BODY_READ_LIMIT {
        let Some(chunk) = response.chunk().await? else {
            return Ok((String::from_utf8_lossy(&bytes).to_string(), false));
        };
        let remaining = API_PROVIDER_ERROR_BODY_READ_LIMIT - bytes.len();
        if chunk.len() > remaining {
            bytes.extend_from_slice(&chunk[..remaining]);
            return Ok((String::from_utf8_lossy(&bytes).to_string(), true));
        }
        bytes.extend_from_slice(&chunk);
    }

    Ok((String::from_utf8_lossy(&bytes).to_string(), true))
}

fn api_provider_error_message(
    label: &str,
    status: reqwest::StatusCode,
    body: Option<&str>,
    api_key: Option<&str>,
    body_was_truncated: bool,
) -> String {
    let Some(body) = body.map(str::trim).filter(|body| !body.is_empty()) else {
        return format!("{label} returned {status}");
    };
    let redacted_body = redact_api_provider_secret(body.to_string(), api_key);
    let mut body = truncate_api_provider_error_body(&redacted_body);
    if body_was_truncated && !body.ends_with("...") {
        body.push_str("...");
    }
    format!("{label} returned {status}: {body}")
}

fn truncate_api_provider_error_body(body: &str) -> String {
    if body.len() <= API_PROVIDER_ERROR_BODY_LIMIT {
        return body.to_string();
    }

    let mut end = API_PROVIDER_ERROR_BODY_LIMIT;
    while !body.is_char_boundary(end) {
        end -= 1;
    }
    format!("{}...", &body[..end])
}

fn api_provider_connection_failure(message: impl Into<String>) -> ApiProviderConnectionResult {
    ApiProviderConnectionResult {
        ok: false,
        message: message.into(),
        models: Vec::new(),
    }
}

fn parse_openai_model_ids(response: &serde_json::Value) -> Vec<String> {
    response
        .get("data")
        .and_then(serde_json::Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|item| item.get("id")?.as_str())
        .map(str::trim)
        .filter(|id| !id.is_empty())
        .map(str::to_string)
        .collect()
}

fn is_valid_openai_chat_completion_response(response: &serde_json::Value) -> bool {
    response.as_object().is_some()
        && response
            .get("choices")
            .and_then(serde_json::Value::as_array)
            .is_some_and(|choices| {
                !choices.is_empty() && choices.iter().any(is_valid_openai_chat_completion_choice)
            })
}

fn is_valid_openai_chat_completion_choice(choice: &serde_json::Value) -> bool {
    choice
        .get("message")
        .and_then(serde_json::Value::as_object)
        .is_some_and(|message| {
            is_assistant_chat_message(message)
                && (message.get("content").is_some_and(has_non_empty_string)
                    || message
                        .get("tool_calls")
                        .and_then(serde_json::Value::as_array)
                        .is_some_and(|tool_calls| {
                            !tool_calls.is_empty()
                                && tool_calls.iter().all(is_valid_openai_tool_call)
                        }))
        })
}

fn is_assistant_chat_message(message: &serde_json::Map<String, serde_json::Value>) -> bool {
    message
        .get("role")
        .and_then(serde_json::Value::as_str)
        .is_some_and(|role| role == "assistant")
}

fn is_valid_openai_tool_call(tool_call: &serde_json::Value) -> bool {
    let Some(tool_call) = tool_call.as_object() else {
        return false;
    };
    let Some(function) = tool_call
        .get("function")
        .and_then(serde_json::Value::as_object)
    else {
        return false;
    };

    tool_call.get("id").is_some_and(has_non_empty_string)
        && tool_call
            .get("type")
            .and_then(serde_json::Value::as_str)
            .is_some_and(|tool_type| tool_type == "function")
        && function.get("name").is_some_and(has_non_empty_string)
        && function
            .get("arguments")
            .is_some_and(|arguments| arguments.as_str().is_some())
}

fn has_non_empty_string(value: &serde_json::Value) -> bool {
    value.as_str().is_some_and(|text| !text.trim().is_empty())
}

fn redact_api_provider_secret(message: String, api_key: Option<&str>) -> String {
    match api_key.map(str::trim).filter(|value| !value.is_empty()) {
        Some(api_key) => {
            redact_api_provider_secret_prefixes(message.replace(api_key, "<redacted>"), api_key)
        }
        None => message,
    }
}

fn redact_api_provider_secret_prefixes(mut message: String, api_key: &str) -> String {
    if api_key.len() <= API_PROVIDER_KEY_PREFIX_REDACTION_MIN_BYTES {
        return message;
    }

    for end in (API_PROVIDER_KEY_PREFIX_REDACTION_MIN_BYTES..api_key.len()).rev() {
        if api_key.is_char_boundary(end) {
            let prefix = &api_key[..end];
            if message.contains(prefix) {
                message = message.replace(prefix, "<redacted>");
            }
        }
    }
    message
}
