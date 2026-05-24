use alita_lib::commands::model_assignment_role_from_payload;
use alita_lib::preferences::{
    add_manual_model, add_speech_to_text_model, agent_model_path, api_provider_preset,
    default_agent_model_mode, default_model_path, delete_api_provider_config,
    ensure_model_storage_dir, import_model_to_storage, load_preferences_from_path,
    record_recent_project, recover_model_preferences, save_preferences_to_path,
    scan_model_directory, set_active_api_provider, set_agent_model_mode, set_default_model,
    set_model_assignment, set_model_storage_dir, speech_to_text_model_path,
    summarize_tool_manifests, tool_enabled, upsert_api_provider_config, ApiProviderInput,
    AppPreferences, ModelAssignmentRole, ModelEntry,
};
use std::fs;

fn valid_api_provider_input() -> ApiProviderInput {
    ApiProviderInput {
        provider_id: None,
        provider_type: "openai".to_string(),
        display_name: "OpenAI".to_string(),
        base_url: "https://api.openai.com/v1".to_string(),
        model: "gpt-4.1".to_string(),
        enabled: true,
    }
}

#[test]
fn default_preferences_have_schema_version_three_and_local_agent_mode() {
    let preferences = AppPreferences::default();

    assert_eq!(preferences.schema_version, 3);
    assert_eq!(preferences.agent_model_mode, "local");
    assert!(preferences.active_api_provider_id.is_none());
    assert!(preferences.api_provider_configs.is_empty());
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
fn loads_version_one_preferences_as_version_three_model_library() {
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

    assert_eq!(preferences.schema_version, 3);
    assert_eq!(preferences.models[0].model_kind, "agent_llm");
    assert_eq!(preferences.models[0].path_kind, "file");
    assert_eq!(
        preferences.model_assignments.agent_chat_model_id.as_deref(),
        Some("model-1")
    );
    assert_eq!(agent_model_path(&preferences), Some(model_path));
}

#[test]
fn loads_version_two_preferences_as_version_three_local_mode() {
    let temp_dir = tempfile::tempdir().unwrap();
    let preferences_path = temp_dir.path().join("preferences.json");
    fs::write(
        &preferences_path,
        r#"{
          "schemaVersion": 2,
          "recentProjects": [],
          "modelDirectories": [],
          "modelStorageDir": "",
          "models": [],
          "defaultModelId": null,
          "modelAssignments": {"agentChatModelId": null, "speechToTextModelId": null},
          "toolEnablement": {}
        }"#,
    )
    .unwrap();

    let preferences = load_preferences_from_path(&preferences_path).unwrap();

    assert_eq!(preferences.schema_version, 3);
    assert_eq!(preferences.agent_model_mode, "local");
    assert!(preferences.active_api_provider_id.is_none());
    assert!(preferences.api_provider_configs.is_empty());
}

#[test]
fn agent_model_mode_helper_defaults_to_local_and_rejects_unknown_modes() {
    let mut preferences = AppPreferences::default();

    assert_eq!(default_agent_model_mode(), "local");
    set_agent_model_mode(&mut preferences, "api").unwrap();
    assert_eq!(preferences.agent_model_mode, "api");

    let error = set_agent_model_mode(&mut preferences, "remote").unwrap_err();

    assert!(error.contains("unknown agent model mode"));
    assert_eq!(preferences.agent_model_mode, "api");
}

#[test]
fn provider_preset_defaults_are_editable_openai_compatible_roots() {
    let deepseek = api_provider_preset("deepseek").unwrap();
    let custom = api_provider_preset("custom").unwrap();

    assert_eq!(deepseek.provider_type, "deepseek");
    assert_eq!(deepseek.base_url, "https://api.deepseek.com");
    assert_eq!(custom.provider_type, "custom");
    assert_eq!(custom.base_url, "");
}

#[test]
fn api_provider_configs_do_not_store_api_keys() {
    let mut preferences = AppPreferences::default();
    let provider = upsert_api_provider_config(
        &mut preferences,
        ApiProviderInput {
            provider_id: None,
            provider_type: "deepseek".to_string(),
            display_name: "DeepSeek".to_string(),
            base_url: "https://api.deepseek.com".to_string(),
            model: "deepseek-chat".to_string(),
            enabled: true,
        },
    )
    .unwrap();
    set_active_api_provider(&mut preferences, Some(&provider.provider_id)).unwrap();

    let serialized = serde_json::to_string(&preferences).unwrap();

    assert!(serialized.contains("deepseek-chat"));
    assert!(serialized.contains("alita.api-provider."));
    assert!(!serialized.contains("sk-"));
    assert_eq!(preferences.agent_model_mode, "api");
    assert_eq!(
        preferences.active_api_provider_id,
        Some(provider.provider_id)
    );
}

#[test]
fn deleting_active_api_provider_clears_active_selection() {
    let mut preferences = AppPreferences::default();
    let provider = upsert_api_provider_config(
        &mut preferences,
        ApiProviderInput {
            provider_id: None,
            provider_type: "openai".to_string(),
            display_name: "OpenAI".to_string(),
            base_url: "https://api.openai.com/v1".to_string(),
            model: "gpt-4.1".to_string(),
            enabled: true,
        },
    )
    .unwrap();
    set_active_api_provider(&mut preferences, Some(&provider.provider_id)).unwrap();

    let removed = delete_api_provider_config(&mut preferences, &provider.provider_id).unwrap();

    assert_eq!(
        removed.credential_ref,
        format!("alita.api-provider.{}", provider.provider_id)
    );
    assert!(preferences.active_api_provider_id.is_none());
    assert!(preferences.api_provider_configs.is_empty());
}

#[test]
fn upsert_api_provider_config_normalizes_custom_provider_input() {
    let mut preferences = AppPreferences::default();

    let provider = upsert_api_provider_config(
        &mut preferences,
        ApiProviderInput {
            provider_id: None,
            provider_type: " Custom ".to_string(),
            display_name: "  Custom Gateway  ".to_string(),
            base_url: " https://gateway.example.com/// ".to_string(),
            model: "  gateway-chat  ".to_string(),
            enabled: true,
        },
    )
    .unwrap();

    assert_eq!(provider.provider_type, "custom");
    assert_eq!(provider.display_name, "Custom Gateway");
    assert_eq!(provider.base_url, "https://gateway.example.com");
    assert_eq!(provider.model, "gateway-chat");
    assert_eq!(
        provider.capabilities,
        vec!["chat_completions".to_string(), "streaming".to_string()]
    );
}

#[test]
fn upsert_api_provider_config_rejects_invalid_provider_type() {
    let mut preferences = AppPreferences::default();

    let error = upsert_api_provider_config(
        &mut preferences,
        ApiProviderInput {
            provider_type: "anthropic".to_string(),
            ..valid_api_provider_input()
        },
    )
    .unwrap_err();

    assert!(error.contains("unknown API provider type"));
    assert!(preferences.api_provider_configs.is_empty());
    assert_eq!(preferences.agent_model_mode, "local");
}

#[test]
fn upsert_api_provider_config_rejects_blank_required_fields() {
    let cases = [
        (
            ApiProviderInput {
                display_name: "  ".to_string(),
                ..valid_api_provider_input()
            },
            "display name",
        ),
        (
            ApiProviderInput {
                base_url: " /// ".to_string(),
                ..valid_api_provider_input()
            },
            "base URL",
        ),
        (
            ApiProviderInput {
                model: "  ".to_string(),
                ..valid_api_provider_input()
            },
            "model name",
        ),
    ];

    for (input, expected_error) in cases {
        let mut preferences = AppPreferences::default();

        let error = upsert_api_provider_config(&mut preferences, input).unwrap_err();

        assert!(error.contains(expected_error));
        assert!(preferences.api_provider_configs.is_empty());
        assert_eq!(preferences.agent_model_mode, "local");
    }
}

#[test]
fn upsert_api_provider_config_rejects_unsafe_base_urls() {
    let cases = [
        "ftp://api.openai.com/v1",
        "http://example.com/v1",
        "https://sk-test@api.openai.com/v1",
        "https://api.openai.com/v1?api_key=sk-test",
        "https://api.openai.com/v1#sk-test",
    ];

    for base_url in cases {
        let mut preferences = AppPreferences::default();

        let error = upsert_api_provider_config(
            &mut preferences,
            ApiProviderInput {
                base_url: base_url.to_string(),
                ..valid_api_provider_input()
            },
        )
        .unwrap_err();

        assert!(error.contains("base URL"), "{base_url}: {error}");
        assert!(!error.contains("sk-test"), "{base_url}: {error}");
        assert!(preferences.api_provider_configs.is_empty());
        assert_eq!(preferences.agent_model_mode, "local");
    }
}

#[test]
fn upsert_api_provider_config_allows_plain_http_for_loopback_base_urls() {
    for base_url in [
        "http://localhost:8766/v1///",
        "http://127.0.0.1:8766/v1///",
        "http://[::1]:8766/v1///",
        "http://custom.localhost:8766/v1///",
    ] {
        let mut preferences = AppPreferences::default();

        let provider = upsert_api_provider_config(
            &mut preferences,
            ApiProviderInput {
                base_url: base_url.to_string(),
                ..valid_api_provider_input()
            },
        )
        .unwrap();

        assert!(!provider.base_url.ends_with('/'));
    }
}

#[test]
fn upsert_api_provider_config_updates_existing_provider_without_changing_secret_ref() {
    let mut preferences = AppPreferences::default();
    let created = upsert_api_provider_config(&mut preferences, valid_api_provider_input()).unwrap();

    let updated = upsert_api_provider_config(
        &mut preferences,
        ApiProviderInput {
            provider_id: Some(created.provider_id.clone()),
            provider_type: "deepseek".to_string(),
            display_name: " DeepSeek ".to_string(),
            base_url: "https://api.deepseek.com///".to_string(),
            model: " deepseek-chat ".to_string(),
            enabled: false,
        },
    )
    .unwrap();

    assert_eq!(preferences.api_provider_configs.len(), 1);
    assert_eq!(updated.provider_id, created.provider_id);
    assert_eq!(updated.credential_ref, created.credential_ref);
    assert_eq!(updated.created_at, created.created_at);
    assert_eq!(updated.provider_type, "deepseek");
    assert_eq!(updated.display_name, "DeepSeek");
    assert_eq!(updated.base_url, "https://api.deepseek.com");
    assert_eq!(updated.model, "deepseek-chat");
    assert!(!updated.enabled);
}

#[test]
fn first_api_provider_is_auto_selected() {
    let mut preferences = AppPreferences::default();

    let provider =
        upsert_api_provider_config(&mut preferences, valid_api_provider_input()).unwrap();

    assert_eq!(
        preferences.active_api_provider_id.as_deref(),
        Some(provider.provider_id.as_str())
    );
    assert_eq!(preferences.agent_model_mode, "api");
}

#[test]
fn set_active_api_provider_rejects_unknown_provider_id() {
    let mut preferences = AppPreferences::default();

    let error = set_active_api_provider(&mut preferences, Some("missing-provider")).unwrap_err();

    assert!(error.contains("unknown API provider id"));
    assert!(preferences.active_api_provider_id.is_none());
    assert_eq!(preferences.agent_model_mode, "local");
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
