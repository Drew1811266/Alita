use std::{
    net::{SocketAddr, TcpStream},
    sync::Mutex,
    time::Duration,
};

use tauri::{AppHandle, Manager, Runtime};
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};
use uuid::Uuid;

const AGENT_BASE_URL: &str = "http://127.0.0.1:8765";
const AGENT_HEALTH_URL: &str = "http://127.0.0.1:8765/health";
const AGENT_PORT: u16 = 8765;
const PACKAGED_SIDECAR_NAME: &str = "alita-agent-sidecar";
const SIDECAR_AUTH_TOKEN_ENV: &str = "ALITA_SIDECAR_TOKEN";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SidecarCommand {
    pub program: &'static str,
    pub args: Vec<&'static str>,
}

#[derive(Debug)]
pub struct AgentSidecarState {
    child: Mutex<Option<CommandChild>>,
    auth_token: String,
}

impl Default for AgentSidecarState {
    fn default() -> Self {
        Self {
            child: Mutex::new(None),
            auth_token: new_sidecar_auth_token(),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AgentSidecarStartup {
    AlreadyRunning,
    Spawned { pid: u32 },
}

pub fn agent_base_url() -> &'static str {
    AGENT_BASE_URL
}

pub fn agent_health_url() -> &'static str {
    AGENT_HEALTH_URL
}

pub fn packaged_sidecar_name() -> &'static str {
    PACKAGED_SIDECAR_NAME
}

pub fn packaged_sidecar_args(parent_pid: u32) -> Vec<String> {
    vec!["--parent-pid".to_string(), parent_pid.to_string()]
}

pub fn new_sidecar_auth_token() -> String {
    Uuid::new_v4().to_string()
}

pub fn sidecar_auth_env(token: impl Into<String>) -> (&'static str, String) {
    (SIDECAR_AUTH_TOKEN_ENV, token.into())
}

pub fn sidecar_auth_token<R: Runtime>(app: &AppHandle<R>) -> Result<String, String> {
    Ok(app.state::<AgentSidecarState>().auth_token.clone())
}

pub fn dev_sidecar_command() -> SidecarCommand {
    SidecarCommand {
        program: "python",
        args: vec![
            "-m",
            "uvicorn",
            "agent_service.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
        ],
    }
}

pub fn start_agent_sidecar<R: Runtime>(app: &AppHandle<R>) -> Result<AgentSidecarStartup, String> {
    if is_agent_port_open(Duration::from_millis(250)) {
        return Ok(AgentSidecarStartup::AlreadyRunning);
    }

    let mut command = app
        .shell()
        .sidecar(packaged_sidecar_name())
        .map_err(|error| format!("failed to create agent sidecar command: {error}"))?
        .args(packaged_sidecar_args(std::process::id()));
    let (auth_key, auth_value) = sidecar_auth_env(sidecar_auth_token(app)?);
    command = command.env(auth_key, auth_value);

    match crate::llama_runtime::config_for_app(app) {
        Ok(config) => {
            for (key, value) in crate::llama_runtime::sidecar_model_env(&config) {
                command = command.env(key, value);
            }
        }
        Err(error) => {
            eprintln!("[agent-sidecar] failed to resolve local model config: {error}");
        }
    }

    let (mut receiver, child) = command
        .spawn()
        .map_err(|error| format!("failed to spawn agent sidecar: {error}"))?;
    let pid = child.pid();

    let state = app.state::<AgentSidecarState>();
    let mut guard = state
        .child
        .lock()
        .map_err(|error| format!("agent sidecar state lock poisoned: {error}"))?;
    if let Some(previous_child) = guard.take() {
        let _ = previous_child.kill();
    }
    *guard = Some(child);
    drop(guard);

    tauri::async_runtime::spawn(async move {
        while let Some(event) = receiver.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    println!("[agent-sidecar] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Stderr(line) => {
                    eprintln!("[agent-sidecar] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Error(error) => {
                    eprintln!("[agent-sidecar] {error}");
                }
                CommandEvent::Terminated(payload) => {
                    eprintln!("[agent-sidecar] terminated with code {:?}", payload.code);
                    break;
                }
                _ => {}
            }
        }
    });

    Ok(AgentSidecarStartup::Spawned { pid })
}

pub fn stop_agent_sidecar<R: Runtime>(app: &AppHandle<R>) {
    let state = app.state::<AgentSidecarState>();
    let Ok(mut guard) = state.child.lock() else {
        eprintln!("[agent-sidecar] failed to lock sidecar state during shutdown");
        return;
    };

    if let Some(child) = guard.take() {
        let _ = child.kill();
    }
}

fn is_agent_port_open(timeout: Duration) -> bool {
    let address = SocketAddr::from(([127, 0, 0, 1], AGENT_PORT));
    TcpStream::connect_timeout(&address, timeout).is_ok()
}
