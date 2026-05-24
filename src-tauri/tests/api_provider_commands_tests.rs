use alita_lib::{
    api_credentials::ApiCredentialStore,
    commands::{
        delete_api_provider_config_core, save_api_provider_config_core, SaveApiProviderPayload,
    },
    preferences::{upsert_api_provider_config, ApiProviderInput, AppPreferences},
};
use std::sync::Mutex;

#[derive(Debug, Clone, PartialEq, Eq)]
enum CredentialOperation {
    Set {
        credential_ref: String,
        api_key: String,
    },
    Delete {
        credential_ref: String,
    },
}

#[derive(Default)]
struct RecordingCredentialStore {
    operations: Mutex<Vec<CredentialOperation>>,
}

impl RecordingCredentialStore {
    fn operations(&self) -> Vec<CredentialOperation> {
        self.operations.lock().unwrap().clone()
    }
}

impl ApiCredentialStore for RecordingCredentialStore {
    fn set_api_key(&self, credential_ref: &str, api_key: &str) -> Result<(), String> {
        self.operations
            .lock()
            .unwrap()
            .push(CredentialOperation::Set {
                credential_ref: credential_ref.to_string(),
                api_key: api_key.to_string(),
            });
        Ok(())
    }

    fn get_api_key(&self, _credential_ref: &str) -> Result<Option<String>, String> {
        Ok(None)
    }

    fn delete_api_key(&self, credential_ref: &str) -> Result<(), String> {
        self.operations
            .lock()
            .unwrap()
            .push(CredentialOperation::Delete {
                credential_ref: credential_ref.to_string(),
            });
        Ok(())
    }
}

fn valid_save_payload(api_key: Option<&str>) -> SaveApiProviderPayload {
    SaveApiProviderPayload {
        provider_id: None,
        provider_type: "openai".to_string(),
        display_name: "OpenAI".to_string(),
        base_url: "https://api.openai.com/v1".to_string(),
        model: "gpt-4.1".to_string(),
        enabled: true,
        api_key: api_key.map(str::to_string),
    }
}

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
fn save_api_provider_core_does_not_store_key_when_preference_save_fails() {
    let mut preferences = AppPreferences::default();
    let credential_store = RecordingCredentialStore::default();

    let error = save_api_provider_config_core(
        &mut preferences,
        valid_save_payload(Some("sk-secret")),
        &credential_store,
        |_| Err("preference save failed".to_string()),
    )
    .unwrap_err();

    assert_eq!(error, "preference save failed");
    assert!(credential_store.operations().is_empty());
}

#[test]
fn delete_api_provider_core_does_not_delete_key_when_preference_save_fails() {
    let mut preferences = AppPreferences::default();
    let provider =
        upsert_api_provider_config(&mut preferences, valid_api_provider_input()).unwrap();
    let credential_store = RecordingCredentialStore::default();

    let error = delete_api_provider_config_core(
        &mut preferences,
        &provider.provider_id,
        &credential_store,
        |_| Err("preference save failed".to_string()),
    )
    .unwrap_err();

    assert_eq!(error, "preference save failed");
    assert!(credential_store.operations().is_empty());
}

#[test]
fn save_api_provider_core_skips_blank_api_key() {
    let mut preferences = AppPreferences::default();
    let credential_store = RecordingCredentialStore::default();

    save_api_provider_config_core(
        &mut preferences,
        valid_save_payload(Some("   ")),
        &credential_store,
        |_| Ok(()),
    )
    .unwrap();

    assert!(credential_store.operations().is_empty());
    assert_eq!(preferences.api_provider_configs.len(), 1);
}
