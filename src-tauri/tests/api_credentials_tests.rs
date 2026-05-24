#[path = "../src/api_credentials.rs"]
#[allow(dead_code)]
mod api_credentials;

use api_credentials::{ApiCredentialStore, MemoryApiCredentialStore};

#[test]
fn memory_store_saves_replaces_reads_and_deletes_api_keys() {
    let store = MemoryApiCredentialStore::default();

    store
        .set_api_key("alita.api-provider.provider-1", "sk-first")
        .unwrap();
    assert_eq!(
        store.get_api_key("alita.api-provider.provider-1").unwrap(),
        Some("sk-first".to_string())
    );

    store
        .set_api_key("alita.api-provider.provider-1", "sk-second")
        .unwrap();
    assert_eq!(
        store.get_api_key("alita.api-provider.provider-1").unwrap(),
        Some("sk-second".to_string())
    );

    store
        .delete_api_key("alita.api-provider.provider-1")
        .unwrap();
    assert_eq!(
        store.get_api_key("alita.api-provider.provider-1").unwrap(),
        None
    );
}

#[test]
fn memory_store_rejects_empty_credential_reference() {
    let store = MemoryApiCredentialStore::default();

    let error = store.set_api_key("", "sk-value").unwrap_err();

    assert!(error.contains("credential reference is required"));
}

#[test]
fn memory_store_rejects_empty_api_key() {
    let store = MemoryApiCredentialStore::default();

    let error = store
        .set_api_key("alita.api-provider.provider-1", "  ")
        .unwrap_err();

    assert!(error.contains("API key is required"));
}
