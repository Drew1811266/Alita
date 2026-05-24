use std::collections::HashMap;
use std::sync::Mutex;

use serde::{Deserialize, Serialize};

const KEYRING_SERVICE: &str = "com.alita.ai-workbench.api-providers";
const API_CREDENTIAL_SCHEMA_VERSION: u32 = 1;

pub trait ApiCredentialStore: Send + Sync {
    fn set_api_key(
        &self,
        credential_ref: &str,
        target: &ApiCredentialTarget,
        api_key: &str,
    ) -> Result<(), String>;
    fn get_api_key(
        &self,
        credential_ref: &str,
        target: &ApiCredentialTarget,
    ) -> Result<Option<String>, String>;
    fn delete_api_key(&self, credential_ref: &str) -> Result<(), String>;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ApiCredentialTarget {
    pub provider_type: String,
    pub base_url: String,
}

impl ApiCredentialTarget {
    pub fn new(provider_type: &str, base_url: &str) -> Result<Self, String> {
        let provider_type = provider_type.trim().to_string();
        if provider_type.is_empty() {
            return Err("API credential provider type is required".to_string());
        }
        let base_url = base_url.trim().trim_end_matches('/').to_string();
        if base_url.is_empty() {
            return Err("API credential base URL is required".to_string());
        }

        Ok(Self {
            provider_type,
            base_url,
        })
    }
}

#[derive(Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
struct StoredApiCredential {
    schema_version: u32,
    provider_type: String,
    base_url: String,
    api_key: String,
}

#[derive(Default)]
pub struct MemoryApiCredentialStore {
    api_keys: Mutex<HashMap<String, String>>,
}

impl ApiCredentialStore for MemoryApiCredentialStore {
    fn set_api_key(
        &self,
        credential_ref: &str,
        target: &ApiCredentialTarget,
        api_key: &str,
    ) -> Result<(), String> {
        let credential_ref = validate_credential_ref(credential_ref)?;
        let password = serialize_api_credential(target, api_key)?;

        self.api_keys
            .lock()
            .map_err(|_| "credential store lock was poisoned".to_string())?
            .insert(credential_ref.to_string(), password);

        Ok(())
    }

    fn get_api_key(
        &self,
        credential_ref: &str,
        target: &ApiCredentialTarget,
    ) -> Result<Option<String>, String> {
        let credential_ref = validate_credential_ref(credential_ref)?;

        self.api_keys
            .lock()
            .map_err(|_| "credential store lock was poisoned".to_string())?
            .get(credential_ref)
            .map(|password| deserialize_api_credential(password, target))
            .unwrap_or(Ok(None))
    }

    fn delete_api_key(&self, credential_ref: &str) -> Result<(), String> {
        let credential_ref = validate_credential_ref(credential_ref)?;

        self.api_keys
            .lock()
            .map_err(|_| "credential store lock was poisoned".to_string())?
            .remove(credential_ref);

        Ok(())
    }
}

#[derive(Default)]
pub struct SystemApiCredentialStore;

impl ApiCredentialStore for SystemApiCredentialStore {
    fn set_api_key(
        &self,
        credential_ref: &str,
        target: &ApiCredentialTarget,
        api_key: &str,
    ) -> Result<(), String> {
        let credential_ref = validate_credential_ref(credential_ref)?;
        let password = serialize_api_credential(target, api_key)?;

        keyring_entry(credential_ref)?
            .set_password(&password)
            .map_err(format_keyring_error)
    }

    fn get_api_key(
        &self,
        credential_ref: &str,
        target: &ApiCredentialTarget,
    ) -> Result<Option<String>, String> {
        let credential_ref = validate_credential_ref(credential_ref)?;

        match keyring_entry(credential_ref)?.get_password() {
            Ok(password) => deserialize_api_credential(&password, target),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(error) => Err(format_keyring_error(error)),
        }
    }

    fn delete_api_key(&self, credential_ref: &str) -> Result<(), String> {
        let credential_ref = validate_credential_ref(credential_ref)?;

        match keyring_entry(credential_ref)?.delete_credential() {
            Ok(()) => Ok(()),
            Err(keyring::Error::NoEntry) => Ok(()),
            Err(error) => Err(format_keyring_error(error)),
        }
    }
}

fn validate_credential_ref(credential_ref: &str) -> Result<&str, String> {
    let credential_ref = credential_ref.trim();
    if credential_ref.is_empty() {
        return Err("credential reference is required".to_string());
    }

    Ok(credential_ref)
}

fn validate_api_key(api_key: &str) -> Result<&str, String> {
    let api_key = api_key.trim();
    if api_key.is_empty() {
        return Err("API key is required".to_string());
    }

    Ok(api_key)
}

fn serialize_api_credential(target: &ApiCredentialTarget, api_key: &str) -> Result<String, String> {
    let target = ApiCredentialTarget::new(&target.provider_type, &target.base_url)?;
    let api_key = validate_api_key(api_key)?;
    let credential = StoredApiCredential {
        schema_version: API_CREDENTIAL_SCHEMA_VERSION,
        provider_type: target.provider_type,
        base_url: target.base_url,
        api_key: api_key.to_string(),
    };

    serde_json::to_string(&credential)
        .map_err(|error| format!("failed to encode API credential: {error}"))
}

fn deserialize_api_credential(
    password: &str,
    target: &ApiCredentialTarget,
) -> Result<Option<String>, String> {
    let target = ApiCredentialTarget::new(&target.provider_type, &target.base_url)?;
    let Ok(credential) = serde_json::from_str::<StoredApiCredential>(password) else {
        return Ok(None);
    };
    if credential.schema_version != API_CREDENTIAL_SCHEMA_VERSION
        || credential.provider_type != target.provider_type
        || credential.base_url != target.base_url
    {
        return Ok(None);
    }

    Ok(Some(validate_api_key(&credential.api_key)?.to_string()))
}

fn keyring_entry(credential_ref: &str) -> Result<keyring::Entry, String> {
    keyring::Entry::new(KEYRING_SERVICE, credential_ref).map_err(format_keyring_error)
}

fn format_keyring_error(error: keyring::Error) -> String {
    format!("keyring credential operation failed: {error}")
}
