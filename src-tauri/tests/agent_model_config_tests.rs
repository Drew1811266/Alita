#[path = "../src/agent_model_config.rs"]
#[allow(dead_code)]
mod agent_model_config;
#[path = "../src/api_credentials.rs"]
#[allow(dead_code)]
mod api_credentials;
#[path = "../src/preferences.rs"]
#[allow(dead_code)]
mod preferences;
#[path = "../src/tools.rs"]
#[allow(dead_code)]
mod tools;

use agent_model_config::{
    resolve_agent_model_config, AgentModelConfig, RegisterModelSessionRequest,
};
use api_credentials::{ApiCredentialStore, MemoryApiCredentialStore};
use preferences::{
    add_manual_model, upsert_api_provider_config, ApiProviderConfig, ApiProviderInput,
    AppPreferences,
};

struct StaticCredentialStore {
    api_key: Option<String>,
}

impl ApiCredentialStore for StaticCredentialStore {
    fn set_api_key(&self, _credential_ref: &str, _api_key: &str) -> Result<(), String> {
        unimplemented!("agent model config tests only read credentials")
    }

    fn get_api_key(&self, _credential_ref: &str) -> Result<Option<String>, String> {
        Ok(self.api_key.clone())
    }

    fn delete_api_key(&self, _credential_ref: &str) -> Result<(), String> {
        unimplemented!("agent model config tests only read credentials")
    }
}

fn legacy_api_preferences(mut provider: ApiProviderConfig) -> AppPreferences {
    provider.provider_id = "provider-1".to_string();
    provider.credential_ref = "alita.api-provider.provider-1".to_string();
    AppPreferences {
        agent_model_mode: "api".to_string(),
        active_api_provider_id: Some(provider.provider_id.clone()),
        api_provider_configs: vec![provider],
        ..AppPreferences::default()
    }
}

fn legacy_valid_provider() -> ApiProviderConfig {
    ApiProviderConfig {
        provider_id: "provider-1".to_string(),
        provider_type: "openai".to_string(),
        display_name: "OpenAI".to_string(),
        base_url: "https://api.openai.com/v1".to_string(),
        model: "gpt-4.1".to_string(),
        credential_ref: "alita.api-provider.provider-1".to_string(),
        enabled: true,
        capabilities: vec!["chat_completions".to_string()],
        created_at: "2026-05-24T00:00:00.000Z".to_string(),
        updated_at: "2026-05-24T00:00:00.000Z".to_string(),
    }
}

#[test]
fn resolves_api_agent_model_config_with_secret_from_store() {
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
    let store = MemoryApiCredentialStore::default();
    store
        .set_api_key(&provider.credential_ref, "sk-test")
        .unwrap();

    let resolved = resolve_agent_model_config(&preferences, &store).unwrap();

    assert_eq!(
        resolved,
        AgentModelConfig::Api {
            provider_id: provider.provider_id,
            provider_type: "openai".to_string(),
            display_name: "OpenAI".to_string(),
            base_url: "https://api.openai.com/v1".to_string(),
            model: "gpt-4.1".to_string(),
            api_key: "sk-test".to_string(),
        }
    );
}

#[test]
fn api_mode_without_key_returns_safe_error() {
    let mut preferences = AppPreferences::default();
    upsert_api_provider_config(
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
    let store = MemoryApiCredentialStore::default();

    let error = resolve_agent_model_config(&preferences, &store).unwrap_err();

    assert!(error.contains("API key is not configured"));
    assert!(!error.contains("sk-"));
}

#[test]
fn resolves_local_agent_model_config_from_model_file_stem() {
    let temp_dir = tempfile::tempdir().unwrap();
    let model_path = temp_dir.path().join("local-agent.gguf");
    std::fs::write(&model_path, b"model").unwrap();

    let mut preferences = AppPreferences::default();
    add_manual_model(&mut preferences, &model_path).unwrap();
    let store = MemoryApiCredentialStore::default();

    let resolved = resolve_agent_model_config(&preferences, &store).unwrap();

    assert_eq!(
        resolved,
        AgentModelConfig::Local {
            base_url: "http://127.0.0.1:8766".to_string(),
            model: "local-agent".to_string(),
        }
    );
}

#[test]
fn api_mode_without_selected_provider_returns_selection_error() {
    let mut preferences = AppPreferences::default();
    preferences.agent_model_mode = "api".to_string();
    let store = MemoryApiCredentialStore::default();

    let error = resolve_agent_model_config(&preferences, &store).unwrap_err();

    assert_eq!(error, "API Agent provider is not selected");
}

#[test]
fn api_mode_with_unknown_active_provider_returns_missing_provider_error() {
    let mut preferences = AppPreferences::default();
    preferences.agent_model_mode = "api".to_string();
    preferences.active_api_provider_id = Some("missing-provider".to_string());
    let store = MemoryApiCredentialStore::default();

    let error = resolve_agent_model_config(&preferences, &store).unwrap_err();

    assert_eq!(
        error,
        "active API provider does not exist: missing-provider"
    );
}

#[test]
fn disabled_api_provider_returns_disabled_provider_error() {
    let mut preferences = AppPreferences::default();
    upsert_api_provider_config(
        &mut preferences,
        ApiProviderInput {
            provider_id: None,
            provider_type: "openai".to_string(),
            display_name: "OpenAI".to_string(),
            base_url: "https://api.openai.com/v1".to_string(),
            model: "gpt-4.1".to_string(),
            enabled: false,
        },
    )
    .unwrap();
    let store = MemoryApiCredentialStore::default();

    let error = resolve_agent_model_config(&preferences, &store).unwrap_err();

    assert_eq!(error, "API provider 'OpenAI' is disabled");
}

#[test]
fn api_mode_rejects_unsafe_legacy_provider_base_url_before_session_registration() {
    let mut provider = legacy_valid_provider();
    provider.base_url = "https://api.openai.com/v1?api_key=sk-leaked".to_string();
    let preferences = legacy_api_preferences(provider);
    let store = StaticCredentialStore {
        api_key: Some("sk-session-secret".to_string()),
    };

    let error = resolve_agent_model_config(&preferences, &store).unwrap_err();

    assert!(error.contains("base URL"));
    assert!(!error.contains("sk-session-secret"));
    assert!(!error.contains("sk-leaked"));
}

#[test]
fn api_mode_rejects_blank_api_key_returned_by_credential_store() {
    let preferences = legacy_api_preferences(legacy_valid_provider());
    let store = StaticCredentialStore {
        api_key: Some("   ".to_string()),
    };

    let error = resolve_agent_model_config(&preferences, &store).unwrap_err();

    assert_eq!(error, "API provider API key is required");
}

#[test]
fn api_mode_rejects_invalid_legacy_provider_required_fields() {
    let cases = [
        (
            ApiProviderConfig {
                provider_type: "anthropic".to_string(),
                ..legacy_valid_provider()
            },
            "unknown API provider type",
        ),
        (
            ApiProviderConfig {
                display_name: "  ".to_string(),
                ..legacy_valid_provider()
            },
            "display name",
        ),
        (
            ApiProviderConfig {
                model: "  ".to_string(),
                ..legacy_valid_provider()
            },
            "model name",
        ),
    ];

    for (provider, expected_error) in cases {
        let preferences = legacy_api_preferences(provider);
        let store = StaticCredentialStore {
            api_key: Some("sk-session-secret".to_string()),
        };

        let error = resolve_agent_model_config(&preferences, &store).unwrap_err();

        assert!(error.contains(expected_error), "{error}");
        assert!(!error.contains("sk-session-secret"));
    }
}

#[test]
fn serializes_api_agent_model_config_with_tagged_camel_case_shape() {
    let config = AgentModelConfig::Api {
        provider_id: "provider-1".to_string(),
        provider_type: "openai".to_string(),
        display_name: "OpenAI".to_string(),
        base_url: "https://api.openai.com/v1".to_string(),
        model: "gpt-4.1".to_string(),
        api_key: "sk-serialize".to_string(),
    };

    let serialized = serde_json::to_value(config).unwrap();

    assert_eq!(
        serialized,
        serde_json::json!({
            "mode": "api",
            "providerId": "provider-1",
            "providerType": "openai",
            "displayName": "OpenAI",
            "baseUrl": "https://api.openai.com/v1",
            "model": "gpt-4.1",
            "apiKey": "sk-serialize",
        })
    );
}

#[test]
fn agent_model_config_debug_redacts_api_key() {
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
    let store = MemoryApiCredentialStore::default();
    store
        .set_api_key(&provider.credential_ref, "sk-debug-secret")
        .unwrap();

    let resolved = resolve_agent_model_config(&preferences, &store).unwrap();
    let debug = format!("{:?}", resolved);

    assert!(!debug.contains("sk-debug-secret"));
    assert!(debug.contains("<redacted>"));
}

#[test]
fn register_model_session_request_debug_redacts_nested_api_key() {
    let request = RegisterModelSessionRequest {
        model_config: AgentModelConfig::Api {
            provider_id: "provider-1".to_string(),
            provider_type: "openai".to_string(),
            display_name: "OpenAI".to_string(),
            base_url: "https://api.openai.com/v1".to_string(),
            model: "gpt-4.1".to_string(),
            api_key: "sk-request-debug-secret".to_string(),
        },
    };

    let debug = format!("{:?}", request);

    assert!(!debug.contains("sk-request-debug-secret"));
    assert!(debug.contains("<redacted>"));
}
