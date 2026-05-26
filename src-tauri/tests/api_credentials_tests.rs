#[path = "../src/api_credentials.rs"]
#[allow(dead_code)]
mod api_credentials;

use api_credentials::{ApiCredentialStore, ApiCredentialTarget, MemoryApiCredentialStore};

fn openai_target() -> ApiCredentialTarget {
    ApiCredentialTarget::new("openai", "https://api.openai.com/v1").unwrap()
}

#[test]
fn memory_store_saves_replaces_reads_and_deletes_api_keys() {
    let store = MemoryApiCredentialStore::default();

    store
        .set_api_key(
            "alita.api-provider.provider-1",
            &openai_target(),
            "sk-first",
        )
        .unwrap();
    assert_eq!(
        store
            .get_api_key("alita.api-provider.provider-1", &openai_target())
            .unwrap(),
        Some("sk-first".to_string())
    );

    store
        .set_api_key(
            "alita.api-provider.provider-1",
            &openai_target(),
            "sk-second",
        )
        .unwrap();
    assert_eq!(
        store
            .get_api_key("alita.api-provider.provider-1", &openai_target())
            .unwrap(),
        Some("sk-second".to_string())
    );

    store
        .delete_api_key("alita.api-provider.provider-1")
        .unwrap();
    assert_eq!(
        store
            .get_api_key("alita.api-provider.provider-1", &openai_target())
            .unwrap(),
        None
    );
}

#[test]
fn memory_store_does_not_return_api_key_for_different_target() {
    let store = MemoryApiCredentialStore::default();
    let original_target = openai_target();
    let changed_target = ApiCredentialTarget::new("openai", "https://attacker.example/v1").unwrap();

    store
        .set_api_key(
            "alita.api-provider.provider-1",
            &original_target,
            "sk-first",
        )
        .unwrap();

    assert_eq!(
        store
            .get_api_key("alita.api-provider.provider-1", &changed_target)
            .unwrap(),
        None
    );
}

#[test]
fn memory_store_rejects_empty_credential_reference() {
    let store = MemoryApiCredentialStore::default();

    let error = store
        .set_api_key("", &openai_target(), "sk-value")
        .unwrap_err();

    assert!(error.contains("credential reference is required"));
}

#[test]
fn memory_store_rejects_empty_api_key() {
    let store = MemoryApiCredentialStore::default();

    let error = store
        .set_api_key("alita.api-provider.provider-1", &openai_target(), "  ")
        .unwrap_err();

    assert!(error.contains("API key is required"));
}
