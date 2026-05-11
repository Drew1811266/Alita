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
    #[serde(default)]
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
    #[serde(default)]
    pub node_run_ids: Vec<String>,
    #[serde(default)]
    pub artifact_refs: Vec<String>,
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
    UnsupportedExtension { path: String },
}

impl std::fmt::Display for ProjectFileError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io { message } => write!(formatter, "{message}"),
            Self::InvalidJson { message } => write!(formatter, "{message}"),
            Self::UnsupportedSchema { version } => {
                write!(formatter, "unsupported .alita schema version: {version}")
            }
            Self::UnsupportedExtension { path } => {
                write!(formatter, "unsupported project extension: expected .alita for '{path}'")
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

pub fn load_project_from_path(
    path: impl AsRef<Path>,
) -> Result<ProjectOpenResult, ProjectFileError> {
    let path = path.as_ref();
    ensure_alita_extension(path)?;
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
    ensure_alita_extension(path)?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(io_error)?;
    }

    let mut project_to_save = project.clone();
    project_to_save.path = path.to_string_lossy().into_owned();
    project_to_save.updated_at = Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true);

    let serialized = serde_json::to_string_pretty(&project_to_save).map_err(|error| {
        ProjectFileError::InvalidJson {
            message: format!(
                "failed to serialize project '{}': {error}",
                project_to_save.name
            ),
        }
    })?;

    let temp_path = path.with_extension("alita.tmp");
    fs::write(&temp_path, serialized).map_err(io_error)?;
    if path.exists() {
        fs::remove_file(path).map_err(io_error)?;
    }
    fs::rename(&temp_path, path).map_err(io_error)?;
    Ok(())
}

fn ensure_alita_extension(path: &Path) -> Result<(), ProjectFileError> {
    let extension = path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default();
    if extension.eq_ignore_ascii_case("alita") {
        return Ok(());
    }

    Err(ProjectFileError::UnsupportedExtension {
        path: path.display().to_string(),
    })
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
