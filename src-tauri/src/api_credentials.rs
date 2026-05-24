use std::collections::HashMap;
use std::sync::Mutex;

const KEYRING_SERVICE: &str = "com.alita.ai-workbench.api-providers";

pub trait ApiCredentialStore: Send + Sync {
    fn set_api_key(&self, credential_ref: &str, api_key: &str) -> Result<(), String>;
    fn get_api_key(&self, credential_ref: &str) -> Result<Option<String>, String>;
    fn delete_api_key(&self, credential_ref: &str) -> Result<(), String>;
}

#[derive(Default)]
pub struct MemoryApiCredentialStore {
    api_keys: Mutex<HashMap<String, String>>,
}

impl ApiCredentialStore for MemoryApiCredentialStore {
    fn set_api_key(&self, credential_ref: &str, api_key: &str) -> Result<(), String> {
        let credential_ref = validate_credential_ref(credential_ref)?;
        let api_key = validate_api_key(api_key)?;

        self.api_keys
            .lock()
            .map_err(|_| "credential store lock was poisoned".to_string())?
            .insert(credential_ref.to_string(), api_key.to_string());

        Ok(())
    }

    fn get_api_key(&self, credential_ref: &str) -> Result<Option<String>, String> {
        let credential_ref = validate_credential_ref(credential_ref)?;

        Ok(self
            .api_keys
            .lock()
            .map_err(|_| "credential store lock was poisoned".to_string())?
            .get(credential_ref)
            .cloned())
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
    fn set_api_key(&self, credential_ref: &str, api_key: &str) -> Result<(), String> {
        let credential_ref = validate_credential_ref(credential_ref)?;
        let api_key = validate_api_key(api_key)?;

        keyring_entry(credential_ref)?
            .set_password(api_key)
            .map_err(format_keyring_error)
    }

    fn get_api_key(&self, credential_ref: &str) -> Result<Option<String>, String> {
        let credential_ref = validate_credential_ref(credential_ref)?;

        match keyring_entry(credential_ref)?.get_password() {
            Ok(api_key) => Ok(Some(api_key)),
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

fn keyring_entry(credential_ref: &str) -> Result<keyring::Entry, String> {
    keyring::Entry::new(KEYRING_SERVICE, credential_ref).map_err(format_keyring_error)
}

fn format_keyring_error(error: keyring::Error) -> String {
    format!("keyring credential operation failed: {error}")
}
