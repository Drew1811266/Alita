pub mod agent_client;
pub mod api_credentials;
pub mod asr;
pub mod commands;
pub mod domain;
pub mod llama_runtime;
pub mod model;
pub mod preferences;
pub mod project;
pub mod sidecar;
pub mod tools;
pub mod workspace;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .manage(sidecar::AgentSidecarState::default())
        .manage(llama_runtime::LlamaRuntimeState::default())
        .setup(|app| {
            match llama_runtime::start_llama_runtime(app.handle()) {
                Ok(llama_runtime::LlamaRuntimeStartup::DisabledNoModel) => {
                    println!("[llama.cpp] model path is not configured; runtime is disabled");
                }
                Ok(llama_runtime::LlamaRuntimeStartup::AlreadyRunning) => {
                    println!("[llama.cpp] existing service detected on port 8766");
                }
                Ok(llama_runtime::LlamaRuntimeStartup::MissingRuntime { path }) => {
                    eprintln!(
                        "[llama.cpp] runtime executable not found at {}",
                        path.display()
                    );
                }
                Ok(llama_runtime::LlamaRuntimeStartup::MissingModelFile { path }) => {
                    eprintln!(
                        "[llama.cpp] configured model file not found at {}",
                        path.display()
                    );
                }
                Ok(llama_runtime::LlamaRuntimeStartup::Spawned { pid }) => {
                    println!("[llama.cpp] started local runtime with pid {pid}");
                }
                Err(error) => {
                    eprintln!("[llama.cpp] startup failed: {error}");
                }
            }

            match sidecar::start_agent_sidecar(app.handle()) {
                Ok(sidecar::AgentSidecarStartup::AlreadyRunning) => {
                    println!("[agent-sidecar] existing service detected on port 8765");
                }
                Ok(sidecar::AgentSidecarStartup::Spawned { pid }) => {
                    println!("[agent-sidecar] started packaged sidecar with pid {pid}");
                }
                Err(error) => {
                    eprintln!("[agent-sidecar] startup failed: {error}");
                }
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::submit_user_message,
            commands::get_asr_status,
            commands::transcribe_voice_audio,
            commands::get_sidecar_auth_token,
            commands::get_attachment_metadata,
            commands::create_project,
            commands::open_project,
            commands::save_project,
            commands::open_artifact,
            commands::reveal_artifact,
            commands::read_artifact_text,
            commands::get_preferences,
            commands::add_model_file,
            commands::add_speech_to_text_model_directory,
            commands::import_model_file,
            commands::scan_model_directory_command,
            commands::set_model_storage_directory,
            commands::set_default_model_command,
            commands::set_model_assignment_command,
            commands::set_tool_enabled
        ])
        .build(tauri::generate_context!())
        .expect("error while running tauri application");

    app.run(|app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            llama_runtime::stop_llama_runtime(app_handle);
            sidecar::stop_agent_sidecar(app_handle);
        }
    });
}
