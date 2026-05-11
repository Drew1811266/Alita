use std::{env, path::PathBuf};

use alita_lib::llama_runtime;

#[test]
fn default_config_is_disabled_until_model_path_is_set() {
    let config = llama_runtime::LlamaRuntimeConfig::default();

    assert!(!config.is_enabled());
    assert_eq!(config.host, "127.0.0.1");
    assert_eq!(config.port, 8766);
    assert_eq!(config.context_size, 16384);
    assert_eq!(config.gpu_layers, "all");
    assert_eq!(config.health_url(), "http://127.0.0.1:8766/health");
}

#[test]
fn config_with_model_path_builds_llama_server_args() {
    let config =
        llama_runtime::LlamaRuntimeConfig::with_model_path(PathBuf::from("D:\\Models\\test.gguf"));

    assert!(config.is_enabled());
    assert_eq!(
        config.server_args(),
        vec![
            "--host",
            "127.0.0.1",
            "--port",
            "8766",
            "--model",
            "D:\\Models\\test.gguf",
            "--ctx-size",
            "16384",
            "--gpu-layers",
            "all",
        ]
    );
}

#[test]
fn config_uses_preference_model_path_when_env_model_path_is_missing() {
    let config = llama_runtime::LlamaRuntimeConfig::from_sources(
        None,
        None,
        Some(PathBuf::from("D:\\Models\\qwen.gguf")),
    );

    assert_eq!(
        config.model_path,
        Some(PathBuf::from("D:\\Models\\qwen.gguf"))
    );
    assert_eq!(config.gpu_layers, "all");
}

#[test]
fn env_model_path_overrides_preference_model_path() {
    let config = llama_runtime::LlamaRuntimeConfig::from_sources(
        Some("E:\\Override\\model.gguf".to_string()),
        Some("32".to_string()),
        Some(PathBuf::from("D:\\Models\\qwen.gguf")),
    );

    assert_eq!(
        config.model_path,
        Some(PathBuf::from("E:\\Override\\model.gguf"))
    );
    assert_eq!(config.gpu_layers, "32");
}

#[test]
fn env_config_uses_alita_vars() {
    env::remove_var("ALITA_LLAMA_MODEL_PATH");
    env::remove_var("ALITA_LLAMA_GPU_LAYERS");

    env::set_var("ALITA_LLAMA_MODEL_PATH", "D:\\Alita\\model.gguf");
    env::set_var("ALITA_LLAMA_GPU_LAYERS", "all");
    let alita_config = llama_runtime::LlamaRuntimeConfig::from_env();
    assert_eq!(
        alita_config.model_path,
        Some(PathBuf::from("D:\\Alita\\model.gguf"))
    );
    assert_eq!(alita_config.gpu_layers, "all");

    env::remove_var("ALITA_LLAMA_MODEL_PATH");
    env::remove_var("ALITA_LLAMA_GPU_LAYERS");
}

#[test]
fn env_config_ignores_non_alita_vars() {
    let legacy_model_path_env = ["BOO", "OOK_LLAMA_MODEL_PATH"].concat();
    let legacy_gpu_layers_env = ["BOO", "OOK_LLAMA_GPU_LAYERS"].concat();
    env::remove_var("ALITA_LLAMA_MODEL_PATH");
    env::remove_var("ALITA_LLAMA_GPU_LAYERS");
    env::set_var(&legacy_model_path_env, "D:\\Legacy\\model.gguf");
    env::set_var(&legacy_gpu_layers_env, "16");

    let config = llama_runtime::LlamaRuntimeConfig::from_env();

    assert_eq!(config.model_path, None);
    assert_eq!(config.gpu_layers, "all");

    env::remove_var(&legacy_model_path_env);
    env::remove_var(&legacy_gpu_layers_env);
}

#[test]
fn sidecar_model_env_is_empty_without_model_path() {
    let config = llama_runtime::LlamaRuntimeConfig::default();

    assert!(llama_runtime::sidecar_model_env(&config).is_empty());
}

#[test]
fn sidecar_model_env_includes_model_path_and_base_url() {
    let config =
        llama_runtime::LlamaRuntimeConfig::with_model_path(PathBuf::from("D:\\Models\\qwen.gguf"));

    assert_eq!(
        llama_runtime::sidecar_model_env(&config),
        vec![
            (
                "ALITA_LLAMA_MODEL_PATH".to_string(),
                "D:\\Models\\qwen.gguf".to_string()
            ),
            (
                "ALITA_LLAMA_BASE_URL".to_string(),
                "http://127.0.0.1:8766".to_string()
            ),
            ("ALITA_LLAMA_MODEL_NAME".to_string(), "qwen".to_string())
        ]
    );
}

#[test]
fn runtime_resource_dir_name_is_stable() {
    assert_eq!(llama_runtime::LLAMA_RESOURCE_DIR, "llama-cpp");
    assert_eq!(llama_runtime::LLAMA_SERVER_EXE, "llama-server.exe");
}

#[test]
fn startup_without_model_path_is_disabled() {
    let config = llama_runtime::LlamaRuntimeConfig::default();

    assert_eq!(
        llama_runtime::startup_decision(&config, false, true, false),
        llama_runtime::LlamaRuntimeStartupDecision::DisabledNoModel
    );
}

#[test]
fn startup_with_model_and_open_port_reuses_existing_runtime() {
    let config = llama_runtime::LlamaRuntimeConfig::with_model_path(PathBuf::from("model.gguf"));

    assert_eq!(
        llama_runtime::startup_decision(&config, true, true, true),
        llama_runtime::LlamaRuntimeStartupDecision::AlreadyRunning
    );
}

#[test]
fn startup_with_model_and_missing_runtime_reports_missing_runtime() {
    let config = llama_runtime::LlamaRuntimeConfig::with_model_path(PathBuf::from("model.gguf"));

    assert_eq!(
        llama_runtime::startup_decision(&config, false, false, true),
        llama_runtime::LlamaRuntimeStartupDecision::MissingRuntime
    );
}

#[test]
fn startup_with_missing_model_file_reports_missing_model_file() {
    let config = llama_runtime::LlamaRuntimeConfig::with_model_path(PathBuf::from("missing.gguf"));

    assert_eq!(
        llama_runtime::startup_decision(&config, false, true, false),
        llama_runtime::LlamaRuntimeStartupDecision::MissingModelFile
    );
}
