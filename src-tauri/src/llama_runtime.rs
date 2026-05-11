use std::{
    env,
    net::{SocketAddr, TcpStream},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::Mutex,
    time::Duration,
};

use tauri::{AppHandle, Manager, Runtime};

use crate::preferences::{
    default_model_path, load_preferences_with_model_recovery, model_recovery_candidate_dirs,
    previous_preferences_path_for_current_path, save_preferences_to_path,
};

pub const LLAMA_RESOURCE_DIR: &str = "llama-cpp";
pub const LLAMA_SERVER_EXE: &str = "llama-server.exe";
const DEFAULT_HOST: &str = "127.0.0.1";
const DEFAULT_PORT: u16 = 8766;
const DEFAULT_CONTEXT_SIZE: u32 = 16384;
const DEFAULT_GPU_LAYERS: &str = "all";
pub const MODEL_PATH_ENV: &str = "ALITA_LLAMA_MODEL_PATH";
pub const BASE_URL_ENV: &str = "ALITA_LLAMA_BASE_URL";
pub const MODEL_NAME_ENV: &str = "ALITA_LLAMA_MODEL_NAME";
const GPU_LAYERS_ENV: &str = "ALITA_LLAMA_GPU_LAYERS";

#[derive(Debug)]
pub struct LlamaRuntimeState {
    child: Mutex<Option<Child>>,
}

impl Default for LlamaRuntimeState {
    fn default() -> Self {
        Self {
            child: Mutex::new(None),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LlamaRuntimeConfig {
    pub model_path: Option<PathBuf>,
    pub host: String,
    pub port: u16,
    pub context_size: u32,
    pub gpu_layers: String,
}

impl Default for LlamaRuntimeConfig {
    fn default() -> Self {
        Self {
            model_path: None,
            host: DEFAULT_HOST.to_string(),
            port: DEFAULT_PORT,
            context_size: DEFAULT_CONTEXT_SIZE,
            gpu_layers: DEFAULT_GPU_LAYERS.to_string(),
        }
    }
}

impl LlamaRuntimeConfig {
    pub fn from_env() -> Self {
        Self::from_env_with_preference(None)
    }

    pub fn from_env_with_preference(preference_model_path: Option<PathBuf>) -> Self {
        Self::from_sources(
            env::var(MODEL_PATH_ENV).ok(),
            env::var(GPU_LAYERS_ENV).ok(),
            preference_model_path,
        )
    }

    pub fn from_sources(
        env_model_path: Option<String>,
        env_gpu_layers: Option<String>,
        preference_model_path: Option<PathBuf>,
    ) -> Self {
        let mut config = Self::default();
        config.model_path = env_model_path
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty())
            .map(PathBuf::from)
            .or(preference_model_path);
        config.gpu_layers = env_gpu_layers
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty())
            .unwrap_or_else(|| DEFAULT_GPU_LAYERS.to_string());
        config
    }

    pub fn with_model_path(model_path: PathBuf) -> Self {
        Self {
            model_path: Some(model_path),
            ..Self::default()
        }
    }

    pub fn is_enabled(&self) -> bool {
        self.model_path.is_some()
    }

    pub fn base_url(&self) -> String {
        format!("http://{}:{}", self.host, self.port)
    }

    pub fn health_url(&self) -> String {
        format!("{}/health", self.base_url())
    }

    pub fn server_args(&self) -> Vec<String> {
        let model_path = self
            .model_path
            .as_ref()
            .map(|path| path.to_string_lossy().into_owned())
            .unwrap_or_default();

        vec![
            "--host".to_string(),
            self.host.clone(),
            "--port".to_string(),
            self.port.to_string(),
            "--model".to_string(),
            model_path,
            "--ctx-size".to_string(),
            self.context_size.to_string(),
            "--gpu-layers".to_string(),
            self.gpu_layers.clone(),
        ]
    }
}

pub fn sidecar_model_env(config: &LlamaRuntimeConfig) -> Vec<(String, String)> {
    let Some(model_path) = config.model_path.as_ref() else {
        return Vec::new();
    };

    let model_name = model_path
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("local-llama-cpp")
        .to_string();

    vec![
        (
            MODEL_PATH_ENV.to_string(),
            model_path.to_string_lossy().into_owned(),
        ),
        (BASE_URL_ENV.to_string(), config.base_url()),
        (MODEL_NAME_ENV.to_string(), model_name),
    ]
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LlamaRuntimeStartupDecision {
    DisabledNoModel,
    AlreadyRunning,
    MissingRuntime,
    MissingModelFile,
    Spawn,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LlamaRuntimeStartup {
    DisabledNoModel,
    AlreadyRunning,
    MissingRuntime { path: PathBuf },
    MissingModelFile { path: PathBuf },
    Spawned { pid: u32 },
}

pub fn startup_decision(
    config: &LlamaRuntimeConfig,
    port_is_open: bool,
    runtime_exists: bool,
    model_file_exists: bool,
) -> LlamaRuntimeStartupDecision {
    if !config.is_enabled() {
        return LlamaRuntimeStartupDecision::DisabledNoModel;
    }

    if port_is_open {
        return LlamaRuntimeStartupDecision::AlreadyRunning;
    }

    if !runtime_exists {
        return LlamaRuntimeStartupDecision::MissingRuntime;
    }

    if !model_file_exists {
        return LlamaRuntimeStartupDecision::MissingModelFile;
    }

    LlamaRuntimeStartupDecision::Spawn
}

pub fn start_llama_runtime<R: Runtime>(app: &AppHandle<R>) -> Result<LlamaRuntimeStartup, String> {
    let config = config_for_app(app)?;
    let runtime_dir = llama_runtime_dir(app);
    let server_path = runtime_dir.join(LLAMA_SERVER_EXE);
    let model_path = config.model_path.clone();
    let model_file_exists = model_path.as_ref().is_some_and(|path| path.exists());
    let port_is_open = is_port_open(config.port, Duration::from_millis(250));

    match startup_decision(
        &config,
        port_is_open,
        server_path.exists(),
        model_file_exists,
    ) {
        LlamaRuntimeStartupDecision::DisabledNoModel => {
            return Ok(LlamaRuntimeStartup::DisabledNoModel);
        }
        LlamaRuntimeStartupDecision::AlreadyRunning => {
            return Ok(LlamaRuntimeStartup::AlreadyRunning);
        }
        LlamaRuntimeStartupDecision::MissingRuntime => {
            return Ok(LlamaRuntimeStartup::MissingRuntime { path: server_path });
        }
        LlamaRuntimeStartupDecision::MissingModelFile => {
            let path = model_path.unwrap_or_default();
            return Ok(LlamaRuntimeStartup::MissingModelFile { path });
        }
        LlamaRuntimeStartupDecision::Spawn => {}
    }

    let mut command = Command::new(&server_path);
    command
        .args(config.server_args())
        .current_dir(&runtime_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000);
    }

    let child = command
        .spawn()
        .map_err(|error| format!("failed to spawn llama.cpp runtime: {error}"))?;
    let pid = child.id();

    let state = app.state::<LlamaRuntimeState>();
    let mut guard = state
        .child
        .lock()
        .map_err(|error| format!("llama.cpp runtime state lock poisoned: {error}"))?;
    if let Some(mut previous_child) = guard.take() {
        let _ = previous_child.kill();
    }
    *guard = Some(child);

    Ok(LlamaRuntimeStartup::Spawned { pid })
}

pub fn config_for_app<R: Runtime>(app: &AppHandle<R>) -> Result<LlamaRuntimeConfig, String> {
    Ok(LlamaRuntimeConfig::from_env_with_preference(
        default_model_path_for_app(app)?,
    ))
}

pub fn default_model_path_for_app<R: Runtime>(
    app: &AppHandle<R>,
) -> Result<Option<PathBuf>, String> {
    let preferences_path = app
        .path()
        .app_config_dir()
        .map_err(|error| format!("failed to resolve app config dir: {error}"))?
        .join("preferences.json");
    let default_storage_dir = app
        .path()
        .app_local_data_dir()
        .map_err(|error| format!("failed to resolve app local data dir: {error}"))?
        .join("models");
    let previous_path = previous_preferences_path_for_current_path(&preferences_path);
    let executable_path = env::current_exe().ok();
    let candidate_model_dirs =
        model_recovery_candidate_dirs(&default_storage_dir, executable_path.as_deref());
    let (preferences, changed) = load_preferences_with_model_recovery(
        &preferences_path,
        &default_storage_dir,
        previous_path.as_deref(),
        &candidate_model_dirs,
    )?;
    if changed {
        save_preferences_to_path(&preferences_path, &preferences)?;
    }
    Ok(default_model_path(&preferences))
}

pub fn stop_llama_runtime<R: Runtime>(app: &AppHandle<R>) {
    let state = app.state::<LlamaRuntimeState>();
    let Ok(mut guard) = state.child.lock() else {
        eprintln!("[llama.cpp] failed to lock runtime state during shutdown");
        return;
    };

    if let Some(mut child) = guard.take() {
        let _ = child.kill();
    }
}

fn llama_runtime_dir<R: Runtime>(app: &AppHandle<R>) -> PathBuf {
    if let Ok(resource_dir) = app.path().resource_dir() {
        let bundled_dir = resource_dir.join(LLAMA_RESOURCE_DIR);
        if bundled_dir.exists() {
            return bundled_dir;
        }
    }

    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("resources")
        .join(LLAMA_RESOURCE_DIR)
}

fn is_port_open(port: u16, timeout: Duration) -> bool {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    TcpStream::connect_timeout(&address, timeout).is_ok()
}
