use alita_lib::sidecar;

#[test]
fn dev_sidecar_command_uses_python_uvicorn() {
    let command = sidecar::dev_sidecar_command();

    assert_eq!(command.program, "python");
    assert_eq!(
        command.args,
        vec![
            "-m",
            "uvicorn",
            "agent_service.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8765"
        ]
    );
}

#[test]
fn health_url_targets_local_agent_port() {
    assert_eq!(sidecar::agent_health_url(), "http://127.0.0.1:8765/health");
}

#[test]
fn agent_base_url_targets_local_agent_port() {
    assert_eq!(sidecar::agent_base_url(), "http://127.0.0.1:8765");
}

#[test]
fn packaged_sidecar_name_matches_tauri_external_binary() {
    assert_eq!(sidecar::packaged_sidecar_name(), "alita-agent-sidecar");
}

#[test]
fn packaged_sidecar_args_include_parent_pid() {
    assert_eq!(
        sidecar::packaged_sidecar_args(1234),
        vec!["--parent-pid".to_string(), "1234".to_string()]
    );
}

#[test]
fn sidecar_auth_token_is_unique_and_nonempty() {
    let first = sidecar::new_sidecar_auth_token();
    let second = sidecar::new_sidecar_auth_token();

    assert!(!first.is_empty());
    assert_ne!(first, second);
}

#[test]
fn sidecar_auth_env_exports_token() {
    assert_eq!(
        sidecar::sidecar_auth_env("token-1"),
        ("ALITA_SIDECAR_TOKEN", "token-1".to_string())
    );
}
