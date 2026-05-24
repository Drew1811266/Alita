#[path = "../src/api_credentials.rs"]
#[allow(dead_code)]
mod api_credentials;
#[path = "../src/agent_model_config.rs"]
#[allow(dead_code)]
mod agent_model_config;
#[path = "../src/preferences.rs"]
#[allow(dead_code)]
mod preferences;
#[path = "../src/tools.rs"]
#[allow(dead_code)]
mod tools;

use api_credentials::{ApiCredentialStore, MemoryApiCredentialStore};
use agent_model_config::{resolve_agent_model_config, AgentModelConfig};
use preferences::{upsert_api_provider_config, ApiProviderInput, AppPreferences};

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
    store.set_api_key(&provider.credential_ref, "sk-test").unwrap();

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
