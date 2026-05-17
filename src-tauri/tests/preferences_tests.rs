use alita_lib::commands::model_assignment_role_from_payload;
use alita_lib::preferences::{
    add_manual_model, add_speech_to_text_model, agent_model_path, default_model_path,
    ensure_model_storage_dir, import_model_to_storage, load_preferences_from_path,
    record_recent_project, recover_model_preferences, save_preferences_to_path,
    scan_model_directory, set_default_model, set_model_assignment, set_model_storage_dir,
    speech_to_text_model_path, summarize_tool_manifests, tool_enabled, AppPreferences,
    ModelAssignmentRole, ModelEntry,
};
use std::fs;

#[test]
fn default_preferences_have_schema_version_two() {
    let preferences = AppPreferences::default();

    assert_eq!(preferences.schema_version, 2);
    assert!(preferences.recent_projects.is_empty());
    assert!(preferences.models.is_empty());
    assert!(preferences.model_directories.is_empty());
    assert!(preferences.model_storage_dir.is_empty());
    assert!(preferences.default_model_id.is_none());
    assert!(preferences.model_assignments.agent_chat_model_id.is_none());
    assert!(preferences
        .model_assignments
        .speech_to_text_model_id
        .is_none());
}

#[test]
fn saves_and_loads_preferences() {
    let temp_dir = tempfile::tempdir().unwrap();
    let preferences_path = temp_dir.path().join("preferences.json");
    let mut preferences = AppPreferences::default();
    preferences.model_directories.push("D:\\Models".to_string());

    save_preferences_to_path(&preferences_path, &preferences).unwrap();
    let loaded = load_preferences_from_path(&preferences_path).unwrap();

    assert_eq!(loaded.model_directories, vec!["D:\\Models"]);
}

#[test]
fn loads_version_one_preferences_as_version_two_model_library() {
    let temp_dir = tempfile::tempdir().unwrap();
    let preferences_path = temp_dir.path().join("preferences.json");
    let model_path = temp_dir.path().join("agent.gguf");
    fs::write(&model_path, "model").unwrap();
    fs::write(
        &preferences_path,
        format!(
            r#"{{
              "schemaVersion": 1,
              "recentProjects": [],
              "modelDirectories": [],
              "modelStorageDir": "",
              "models": [{{
                "modelId": "model-1",
                "name": "agent",
                "path": "{}",
                "source": "manual",
                "runtime": "llama_cpp",
                "fileExists": true,
                "createdAt": "2026-05-17T00:00:00.000Z",
                "updatedAt": "2026-05-17T00:00:00.000Z"
              }}],
              "defaultModelId": "model-1",
              "toolEnablement": {{}}
            }}"#,
            model_path.to_string_lossy().replace('\\', "\\\\")
        ),
    )
    .unwrap();

    let preferences = load_preferences_from_path(&preferences_path).unwrap();

    assert_eq!(preferences.schema_version, 2);
    assert_eq!(preferences.models[0].model_kind, "agent_llm");
    assert_eq!(preferences.models[0].path_kind, "file");
    assert_eq!(
        preferences.model_assignments.agent_chat_model_id.as_deref(),
        Some("model-1")
    );
    assert_eq!(agent_model_path(&preferences), Some(model_path));
}

#[test]
fn adds_speech_to_text_model_directory_and_assigns_it() {
    let temp_dir = tempfile::tempdir().unwrap();
    let asr_dir = temp_dir.path().join("Qwen3-ASR-1.7B");
    fs::create_dir_all(&asr_dir).unwrap();
    let mut preferences = AppPreferences::default();

    let model = add_speech_to_text_model(&mut preferences, &asr_dir).unwrap();
    set_model_assignment(
        &mut preferences,
        ModelAssignmentRole::SpeechToText,
        Some(&model.model_id),
    )
    .unwrap();

    assert_eq!(model.model_kind, "speech_to_text");
    assert_eq!(model.runtime, "qwen_asr");
    assert_eq!(model.path_kind, "directory");
    assert_eq!(speech_to_text_model_path(&preferences), Some(asr_dir));
}

#[test]
fn rejects_assignment_to_wrong_model_kind() {
    let temp_dir = tempfile::tempdir().unwrap();
    let model_path = temp_dir.path().join("agent.gguf");
    fs::write(&model_path, "model").unwrap();
    let mut preferences = AppPreferences::default();
    let model = add_manual_model(&mut preferences, &model_path).unwrap();

    let error = set_model_assignment(
        &mut preferences,
        ModelAssignmentRole::SpeechToText,
        Some(&model.model_id),
    )
    .unwrap_err();

    assert!(error.contains("speech_to_text"));
}

#[test]
fn set_model_assignment_clears_agent_and_speech_to_text_roles() {
    let temp_dir = tempfile::tempdir().unwrap();
    let agent_path = temp_dir.path().join("agent.gguf");
    let asr_dir = temp_dir.path().join("Qwen3-ASR-1.7B");
    fs::write(&agent_path, "model").unwrap();
    fs::create_dir_all(&asr_dir).unwrap();
    let mut preferences = AppPreferences::default();
    let agent_model = add_manual_model(&mut preferences, &agent_path).unwrap();
    let asr_model = add_speech_to_text_model(&mut preferences, &asr_dir).unwrap();
    set_model_assignment(
        &mut preferences,
        ModelAssignmentRole::AgentChat,
        Some(&agent_model.model_id),
    )
    .unwrap();
    set_model_assignment(
        &mut preferences,
        ModelAssignmentRole::SpeechToText,
        Some(&asr_model.model_id),
    )
    .unwrap();

    set_model_assignment(&mut preferences, ModelAssignmentRole::AgentChat, None).unwrap();
    set_model_assignment(&mut preferences, ModelAssignmentRole::SpeechToText, None).unwrap();

    assert!(preferences.default_model_id.is_none());
    assert!(preferences.model_assignments.agent_chat_model_id.is_none());
    assert!(preferences
        .model_assignments
        .speech_to_text_model_id
        .is_none());
    assert!(agent_model_path(&preferences).is_none());
    assert!(speech_to_text_model_path(&preferences).is_none());
}

#[test]
fn model_assignment_command_role_parser_rejects_unknown_roles() {
    assert_eq!(
        model_assignment_role_from_payload("agentChat").unwrap(),
        ModelAssignmentRole::AgentChat
    );
    assert_eq!(
        model_assignment_role_from_payload("speechToText").unwrap(),
        ModelAssignmentRole::SpeechToText
    );

    let error = model_assignment_role_from_payload("voiceInput").unwrap_err();

    assert!(error.contains("unknown model assignment role"));
    assert!(error.contains("voiceInput"));
}

#[test]
fn missing_preferences_path_returns_default_preferences() {
    let temp_dir = tempfile::tempdir().unwrap();
    let preferences_path = temp_dir.path().join("Alita").join("preferences.json");

    let loaded = load_preferences_from_path(&preferences_path).unwrap();

    assert_eq!(loaded, AppPreferences::default());
}

#[test]
fn recovers_default_model_from_previous_project_directory() {
    let temp_dir = tempfile::tempdir().unwrap();
    let previous_project_name = ["Boo", "ook"].concat();
    let previous_model_path = temp_dir
        .path()
        .join(previous_project_name)
        .join("models")
        .join("qwen.gguf");
    let current_model_path = temp_dir
        .path()
        .join("Alita")
        .join("models")
        .join("qwen.gguf");
    fs::create_dir_all(current_model_path.parent().unwrap()).unwrap();
    fs::write(&current_model_path, "model").unwrap();
    let previous_preferences = AppPreferences {
        models: vec![ModelEntry {
            model_id: "previous-default".to_string(),
            name: "qwen".to_string(),
            path: previous_model_path.to_string_lossy().into_owned(),
            source: "imported".to_string(),
            runtime: "llama_cpp".to_string(),
            model_kind: "agent_llm".to_string(),
            path_kind: "file".to_string(),
            file_exists: true,
            created_at: "2026-05-10T00:00:00.000Z".to_string(),
            updated_at: "2026-05-10T00:00:00.000Z".to_string(),
        }],
        default_model_id: Some("previous-default".to_string()),
        ..AppPreferences::default()
    };
    let mut preferences = AppPreferences::default();

    let changed = recover_model_preferences(&mut preferences, &previous_preferences, &[]).unwrap();

    assert!(changed);
    assert_eq!(preferences.models.len(), 1);
    assert_eq!(preferences.models[0].name, "qwen");
    assert_eq!(default_model_path(&preferences), Some(current_model_path));
}

#[test]
fn ensure_model_storage_dir_sets_default_and_creates_directory() {
    let temp_dir = tempfile::tempdir().unwrap();
    let default_storage_dir = temp_dir.path().join("Alita").join("models");
    let mut preferences = AppPreferences::default();

    let changed = ensure_model_storage_dir(&mut preferences, &default_storage_dir).unwrap();

    assert!(changed);
    assert_eq!(
        preferences.model_storage_dir,
        default_storage_dir.to_string_lossy()
    );
    assert!(default_storage_dir.is_dir());
}

#[test]
fn set_model_storage_dir_records_custom_directory() {
    let temp_dir = tempfile::tempdir().unwrap();
    let custom_storage_dir = temp_dir.path().join("AI Models");
    let mut preferences = AppPreferences::default();

    set_model_storage_dir(&mut preferences, &custom_storage_dir).unwrap();

    assert_eq!(
        preferences.model_storage_dir,
        custom_storage_dir.to_string_lossy()
    );
    assert!(custom_storage_dir.is_dir());
}

#[test]
fn import_model_to_storage_copies_gguf_and_registers_imported_model() {
    let temp_dir = tempfile::tempdir().unwrap();
    let source_path = temp_dir.path().join("qwen.gguf");
    let storage_dir = temp_dir.path().join("models");
    fs::write(&source_path, "model bytes").unwrap();
    let mut preferences = AppPreferences::default();

    let model = import_model_to_storage(&mut preferences, &source_path, &storage_dir).unwrap();

    let stored_path = storage_dir.join("qwen.gguf");
    assert_eq!(model.source, "imported");
    assert_eq!(model.path, stored_path.to_string_lossy());
    assert!(stored_path.exists());
    assert_eq!(preferences.models.len(), 1);
}

#[test]
fn import_model_to_storage_rejects_non_gguf_files() {
    let temp_dir = tempfile::tempdir().unwrap();
    let source_path = temp_dir.path().join("notes.txt");
    fs::write(&source_path, "not a model").unwrap();
    let mut preferences = AppPreferences::default();

    let error =
        import_model_to_storage(&mut preferences, &source_path, temp_dir.path()).unwrap_err();

    assert!(error.contains("GGUF"));
    assert!(preferences.models.is_empty());
}

#[test]
fn adding_manual_model_deduplicates_by_path() {
    let temp_dir = tempfile::tempdir().unwrap();
    let model_path = temp_dir.path().join("qwen.gguf");
    fs::write(&model_path, "model").unwrap();
    let mut preferences = AppPreferences::default();

    add_manual_model(&mut preferences, &model_path).unwrap();
    add_manual_model(&mut preferences, &model_path).unwrap();

    assert_eq!(preferences.models.len(), 1);
    assert_eq!(preferences.models[0].source, "manual");
    assert!(preferences.models[0].file_exists);
}

#[test]
fn first_registered_model_becomes_default_model() {
    let temp_dir = tempfile::tempdir().unwrap();
    let model_path = temp_dir.path().join("qwen.gguf");
    fs::write(&model_path, "model").unwrap();
    let mut preferences = AppPreferences::default();

    let model = add_manual_model(&mut preferences, &model_path).unwrap();

    assert_eq!(preferences.default_model_id, Some(model.model_id));
    assert_eq!(default_model_path(&preferences), Some(model_path));
}

#[test]
fn set_default_model_accepts_registered_model_id() {
    let temp_dir = tempfile::tempdir().unwrap();
    let first_path = temp_dir.path().join("first.gguf");
    let second_path = temp_dir.path().join("second.gguf");
    fs::write(&first_path, "first").unwrap();
    fs::write(&second_path, "second").unwrap();
    let mut preferences = AppPreferences::default();
    add_manual_model(&mut preferences, &first_path).unwrap();
    let second = add_manual_model(&mut preferences, &second_path).unwrap();

    set_default_model(&mut preferences, Some(&second.model_id)).unwrap();

    assert_eq!(preferences.default_model_id, Some(second.model_id));
    assert_eq!(default_model_path(&preferences), Some(second_path));
}

#[test]
fn set_default_model_rejects_unknown_model_id() {
    let mut preferences = AppPreferences::default();

    let error = set_default_model(&mut preferences, Some("missing-model")).unwrap_err();

    assert!(error.contains("unknown model"));
    assert!(preferences.default_model_id.is_none());
}

#[test]
fn scan_model_directory_adds_gguf_files_only() {
    let temp_dir = tempfile::tempdir().unwrap();
    fs::write(temp_dir.path().join("qwen.gguf"), "model").unwrap();
    fs::write(temp_dir.path().join("notes.txt"), "ignored").unwrap();
    let mut preferences = AppPreferences::default();

    let added = scan_model_directory(&mut preferences, temp_dir.path()).unwrap();

    assert_eq!(added, 1);
    assert_eq!(preferences.models.len(), 1);
    assert_eq!(preferences.models[0].source, "scan");
}

#[test]
fn builtin_manifest_tools_default_to_enabled() {
    let summaries = summarize_tool_manifests("../tool-packages", &AppPreferences::default());

    let document_tool = summaries
        .iter()
        .find(|tool| tool.tool_id == "document.read_write")
        .expect("document tool should be listed");

    assert!(document_tool.enabled);
    assert!(document_tool.valid);
}

#[test]
fn tool_summary_includes_markitdown_metadata() {
    let summaries = summarize_tool_manifests("../tool-packages", &AppPreferences::default());

    let markitdown_tool = summaries
        .iter()
        .find(|tool| tool.tool_id == "document.markitdown_convert")
        .expect("MarkItDown tool should be listed");

    assert_eq!(markitdown_tool.runtime.as_deref(), Some("python_sidecar"));
    assert_eq!(markitdown_tool.package_name.as_deref(), Some("markitdown"));
    assert!(markitdown_tool
        .capabilities
        .contains(&"document.convert.markdown".to_string()));
}

#[test]
fn explicit_tool_enablement_overrides_default() {
    let mut preferences = AppPreferences::default();
    preferences
        .tool_enablement
        .insert("document.read_write".to_string(), false);

    assert!(!tool_enabled("document.read_write", &preferences));
}

#[test]
fn records_recent_projects_without_duplicates() {
    let mut preferences = AppPreferences::default();

    record_recent_project(&mut preferences, "D:\\Projects\\A.alita");
    record_recent_project(&mut preferences, "D:\\Projects\\B.alita");
    record_recent_project(&mut preferences, "D:\\Projects\\A.alita");

    assert_eq!(
        preferences.recent_projects,
        vec![
            "D:\\Projects\\A.alita".to_string(),
            "D:\\Projects\\B.alita".to_string()
        ]
    );
}
