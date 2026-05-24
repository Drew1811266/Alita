use alita_lib::{
    api_credentials::ApiCredentialStore,
    commands::{
        api_provider_test_payload_with_stored_key, delete_api_provider_config_core,
        preferences_view_with_api_key_status, save_api_provider_config_core,
        SaveApiProviderPayload, TestApiProviderPayload,
    },
    preferences::{upsert_api_provider_config, ApiProviderInput, AppPreferences},
};
use std::{collections::HashMap, sync::Mutex};

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

struct RecordingCredentialStore {
    operations: Mutex<Vec<CredentialOperation>>,
    api_keys: Mutex<HashMap<String, String>>,
    get_error: Option<String>,
    set_error: Option<String>,
    delete_error: Option<String>,
}

impl Default for RecordingCredentialStore {
    fn default() -> Self {
        Self {
            operations: Mutex::new(Vec::new()),
            api_keys: Mutex::new(HashMap::new()),
            get_error: None,
            set_error: None,
            delete_error: None,
        }
    }
}

impl RecordingCredentialStore {
    fn failing_set(error: &str) -> Self {
        Self {
            set_error: Some(error.to_string()),
            ..Self::default()
        }
    }

    fn failing_delete(error: &str) -> Self {
        Self {
            delete_error: Some(error.to_string()),
            ..Self::default()
        }
    }

    fn failing_get(error: &str) -> Self {
        Self {
            get_error: Some(error.to_string()),
            ..Self::default()
        }
    }

    fn operations(&self) -> Vec<CredentialOperation> {
        self.operations.lock().unwrap().clone()
    }

    fn insert_api_key(&self, credential_ref: &str, api_key: &str) {
        self.api_keys
            .lock()
            .unwrap()
            .insert(credential_ref.to_string(), api_key.to_string());
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
        match self.set_error.as_deref() {
            Some(error) => Err(error.to_string()),
            None => Ok(()),
        }
    }

    fn get_api_key(&self, credential_ref: &str) -> Result<Option<String>, String> {
        if let Some(error) = self.get_error.as_deref() {
            return Err(error.to_string());
        }
        Ok(self.api_keys.lock().unwrap().get(credential_ref).cloned())
    }

    fn delete_api_key(&self, credential_ref: &str) -> Result<(), String> {
        self.operations
            .lock()
            .unwrap()
            .push(CredentialOperation::Delete {
                credential_ref: credential_ref.to_string(),
            });
        match self.delete_error.as_deref() {
            Some(error) => Err(error.to_string()),
            None => Ok(()),
        }
    }
}

#[test]
fn api_provider_preferences_view_reports_configured_key_status_without_leaking_secret() {
    let mut preferences = AppPreferences::default();
    let provider_with_key =
        upsert_api_provider_config(&mut preferences, valid_api_provider_input()).unwrap();
    let provider_without_key = upsert_api_provider_config(
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
    let saved_preferences = serde_json::to_string(&preferences).unwrap();
    let credential_store = RecordingCredentialStore::default();
    credential_store.insert_api_key(&provider_with_key.credential_ref, "sk-secret");

    let view = preferences_view_with_api_key_status(preferences, Vec::new(), &credential_store);

    let with_key = view
        .preferences
        .api_provider_configs
        .iter()
        .find(|provider| provider.provider_id == provider_with_key.provider_id)
        .unwrap();
    let without_key = view
        .preferences
        .api_provider_configs
        .iter()
        .find(|provider| provider.provider_id == provider_without_key.provider_id)
        .unwrap();
    assert_eq!(with_key.has_api_key, Some(true));
    assert_eq!(with_key.api_key_status.as_deref(), Some("configured"));
    assert_eq!(without_key.has_api_key, Some(false));
    assert_eq!(without_key.api_key_status.as_deref(), Some("missing"));
    assert!(!saved_preferences.contains("sk-secret"));
    assert!(!saved_preferences.contains("hasApiKey"));
    assert!(!saved_preferences.contains("apiKeyStatus"));
}

#[test]
fn api_provider_preferences_view_does_not_fail_when_key_status_read_fails() {
    let mut preferences = AppPreferences::default();
    upsert_api_provider_config(&mut preferences, valid_api_provider_input()).unwrap();
    let credential_store = RecordingCredentialStore::failing_get("credential store unavailable");

    let view = preferences_view_with_api_key_status(preferences, Vec::new(), &credential_store);

    assert_eq!(
        view.preferences.api_provider_configs[0].has_api_key,
        Some(false)
    );
    assert_eq!(
        view.preferences.api_provider_configs[0]
            .api_key_status
            .as_deref(),
        Some("unknown")
    );
}

#[test]
fn api_provider_helper_payload_uses_saved_key_for_existing_provider() {
    let mut preferences = AppPreferences::default();
    let provider =
        upsert_api_provider_config(&mut preferences, valid_api_provider_input()).unwrap();
    let credential_store = RecordingCredentialStore::default();
    credential_store.insert_api_key(&provider.credential_ref, "sk-saved");
    let payload = valid_test_payload(Some(provider.provider_id.clone()), None);

    let hydrated =
        api_provider_test_payload_with_stored_key(&preferences, payload, &credential_store)
            .unwrap();

    assert_eq!(hydrated.api_key.as_deref(), Some("sk-saved"));
}

#[test]
fn api_provider_helper_payload_requires_explicit_key_when_target_changes() {
    let mut preferences = AppPreferences::default();
    let provider =
        upsert_api_provider_config(&mut preferences, valid_api_provider_input()).unwrap();
    let credential_store = RecordingCredentialStore::default();
    credential_store.insert_api_key(&provider.credential_ref, "sk-saved");
    let mut payload = valid_test_payload(Some(provider.provider_id.clone()), None);
    payload.base_url = "https://gateway.example.com/v1".to_string();

    let error = api_provider_test_payload_with_stored_key(&preferences, payload, &credential_store)
        .unwrap_err();

    assert_eq!(
        error,
        "API key is required when provider connection settings are changed"
    );
}

#[test]
fn api_provider_helper_payload_allows_saved_key_when_model_changes() {
    let mut preferences = AppPreferences::default();
    let provider =
        upsert_api_provider_config(&mut preferences, valid_api_provider_input()).unwrap();
    let credential_store = RecordingCredentialStore::default();
    credential_store.insert_api_key(&provider.credential_ref, "sk-saved");
    let mut payload = valid_test_payload(Some(provider.provider_id.clone()), None);
    payload.model = "gpt-4.1-mini".to_string();

    let hydrated =
        api_provider_test_payload_with_stored_key(&preferences, payload, &credential_store)
            .unwrap();

    assert_eq!(hydrated.api_key.as_deref(), Some("sk-saved"));
    assert_eq!(hydrated.model, "gpt-4.1-mini");
}

#[test]
fn api_provider_helper_payload_does_not_replace_explicit_blank_key() {
    let mut preferences = AppPreferences::default();
    let provider =
        upsert_api_provider_config(&mut preferences, valid_api_provider_input()).unwrap();
    let credential_store = RecordingCredentialStore::default();
    credential_store.insert_api_key(&provider.credential_ref, "sk-saved");
    let payload = valid_test_payload(Some(provider.provider_id.clone()), Some("   ".to_string()));

    let hydrated =
        api_provider_test_payload_with_stored_key(&preferences, payload, &credential_store)
            .unwrap();

    assert_eq!(hydrated.api_key.as_deref(), Some("   "));
}

#[test]
fn api_provider_helper_payload_rejects_unknown_saved_provider_id() {
    let preferences = AppPreferences::default();
    let credential_store = RecordingCredentialStore::default();
    let payload = valid_test_payload(Some("missing-provider".to_string()), None);

    let error = api_provider_test_payload_with_stored_key(&preferences, payload, &credential_store)
        .unwrap_err();

    assert_eq!(error, "unknown API provider id: missing-provider");
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

fn valid_test_payload(
    provider_id: Option<String>,
    api_key: Option<String>,
) -> TestApiProviderPayload {
    TestApiProviderPayload {
        provider_id,
        provider_type: "openai".to_string(),
        display_name: "OpenAI".to_string(),
        base_url: "https://api.openai.com/v1".to_string(),
        model: "gpt-4.1".to_string(),
        api_key,
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
fn save_api_provider_core_rejects_explicit_blank_api_key_without_saving() {
    let mut preferences = AppPreferences::default();
    let credential_store = RecordingCredentialStore::default();

    let error = save_api_provider_config_core(
        &mut preferences,
        valid_save_payload(Some("   ")),
        &credential_store,
        |_| Ok(()),
    )
    .unwrap_err();

    assert_eq!(error, "API provider API key is required");
    assert!(credential_store.operations().is_empty());
    assert!(preferences.api_provider_configs.is_empty());
}

#[test]
fn save_api_provider_core_rejects_new_provider_when_api_key_is_not_provided() {
    let mut preferences = AppPreferences::default();
    let credential_store = RecordingCredentialStore::default();

    let error = save_api_provider_config_core(
        &mut preferences,
        valid_save_payload(None),
        &credential_store,
        |_| Ok(()),
    )
    .unwrap_err();

    assert_eq!(error, "API provider API key is required");
    assert!(credential_store.operations().is_empty());
    assert!(preferences.api_provider_configs.is_empty());
}

#[test]
fn save_api_provider_core_preserves_secret_when_existing_api_key_is_not_provided() {
    let mut preferences = AppPreferences::default();
    let credential_store = RecordingCredentialStore::default();

    save_api_provider_config_core(
        &mut preferences,
        valid_save_payload(Some("sk-secret")),
        &credential_store,
        |_| Ok(()),
    )
    .unwrap();
    let provider_id = preferences.api_provider_configs[0].provider_id.clone();
    let mut payload = valid_save_payload(None);
    payload.provider_id = Some(provider_id.clone());
    payload.display_name = "Updated OpenAI".to_string();
    credential_store.operations.lock().unwrap().clear();

    save_api_provider_config_core(&mut preferences, payload, &credential_store, |_| Ok(()))
        .unwrap();

    assert!(credential_store.operations().is_empty());
    assert_eq!(preferences.api_provider_configs.len(), 1);
    assert_eq!(preferences.api_provider_configs[0].provider_id, provider_id);
    assert_eq!(
        preferences.api_provider_configs[0].display_name,
        "Updated OpenAI"
    );
}

#[test]
fn save_api_provider_core_requires_new_key_when_existing_connection_target_changes() {
    let mut preferences = AppPreferences::default();
    let credential_store = RecordingCredentialStore::default();

    save_api_provider_config_core(
        &mut preferences,
        valid_save_payload(Some("sk-secret")),
        &credential_store,
        |_| Ok(()),
    )
    .unwrap();
    let provider_id = preferences.api_provider_configs[0].provider_id.clone();
    let mut payload = valid_save_payload(None);
    payload.provider_id = Some(provider_id.clone());
    payload.base_url = "https://gateway.example.com/v1".to_string();
    credential_store.operations.lock().unwrap().clear();

    let error =
        save_api_provider_config_core(&mut preferences, payload, &credential_store, |_| Ok(()))
            .unwrap_err();

    assert_eq!(
        error,
        "API key is required when provider connection settings are changed"
    );
    assert!(credential_store.operations().is_empty());
    assert_eq!(preferences.api_provider_configs[0].provider_id, provider_id);
    assert_eq!(
        preferences.api_provider_configs[0].base_url,
        "https://api.openai.com/v1"
    );
}

#[test]
fn save_api_provider_core_rolls_back_preferences_when_credential_set_fails() {
    let mut preferences = AppPreferences::default();
    let original_preferences = preferences.clone();
    let credential_store = RecordingCredentialStore::failing_set("credential set failed");
    let saved_preferences = Mutex::new(Vec::new());

    let error = save_api_provider_config_core(
        &mut preferences,
        valid_save_payload(Some("sk-secret")),
        &credential_store,
        |prefs| {
            saved_preferences.lock().unwrap().push(prefs.clone());
            Ok(())
        },
    )
    .unwrap_err();

    assert_eq!(error, "credential set failed");
    assert_eq!(preferences, original_preferences);
    let saved_preferences = saved_preferences.lock().unwrap();
    assert_eq!(saved_preferences.len(), 2);
    assert_eq!(saved_preferences[0].api_provider_configs.len(), 1);
    assert_eq!(saved_preferences[1], original_preferences);
}

#[test]
fn delete_api_provider_core_rolls_back_preferences_when_credential_delete_fails() {
    let mut preferences = AppPreferences::default();
    let provider =
        upsert_api_provider_config(&mut preferences, valid_api_provider_input()).unwrap();
    let original_preferences = preferences.clone();
    let credential_store = RecordingCredentialStore::failing_delete("credential delete failed");
    let saved_preferences = Mutex::new(Vec::new());

    let error = delete_api_provider_config_core(
        &mut preferences,
        &provider.provider_id,
        &credential_store,
        |prefs| {
            saved_preferences.lock().unwrap().push(prefs.clone());
            Ok(())
        },
    )
    .unwrap_err();

    assert_eq!(error, "credential delete failed");
    assert_eq!(preferences, original_preferences);
    let saved_preferences = saved_preferences.lock().unwrap();
    assert_eq!(saved_preferences.len(), 2);
    assert!(saved_preferences[0].api_provider_configs.is_empty());
    assert_eq!(saved_preferences[1], original_preferences);
}
