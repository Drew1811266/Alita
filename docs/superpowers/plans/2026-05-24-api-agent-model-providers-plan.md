# API Agent Model Providers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a long-term-safe Agent model configuration system that lets users choose local GGUF or OpenAI-compatible API providers for every Agent LLM call.

**Architecture:** Preferences stores non-sensitive local/API model configuration. Rust owns OS credential access and creates short-lived sidecar model sessions so API keys never pass through React or project files. Python resolves a per-request model client from the sidecar session and uses the same client for chat streaming and graph model nodes.

**Tech Stack:** React 19, TypeScript, Vite, Vitest, Tauri 2, Rust, `reqwest`, `keyring` crate, Python FastAPI, Pydantic, pytest.

---

## File Structure

Create or modify these files:

- `src-tauri/Cargo.toml`: add `keyring` dependency with Windows credential-store support.
- `src-tauri/src/preferences.rs`: schema v3, Agent model mode, API provider config data model, provider helpers.
- `src-tauri/src/api_credentials.rs`: credential-store abstraction, system implementation, in-memory test implementation.
- `src-tauri/src/agent_model_config.rs`: resolves current Agent model source and prepares sidecar model-session payloads.
- `src-tauri/src/agent_client.rs`: registers model sessions with sidecar and supports helper API calls.
- `src-tauri/src/commands.rs`: Tauri commands for Agent model mode, API provider CRUD, test connection, model list, and model session preparation.
- `src-tauri/src/lib.rs`: register new modules and commands.
- `src-tauri/tests/preferences_tests.rs`: schema v3 and API provider preference tests.
- `src-tauri/tests/api_credentials_tests.rs`: credential store unit tests.
- `src-tauri/tests/agent_model_config_tests.rs`: local/API model config resolution tests.
- `src-tauri/tests/agent_client_tests.rs`: sidecar model-session request tests.
- `python/agent_service/schemas.py`: optional `model_session_id` on message and graph requests; model-session request schema.
- `python/agent_service/model_sessions.py`: in-memory model session registry with one-time consumption.
- `python/agent_service/model_client.py`: OpenAI-compatible model client and model-client factory while preserving llama.cpp behavior.
- `python/agent_service/graph.py`: use request/session model clients for chat and streaming.
- `python/agent_service/execution.py`: graph execution receives request/session model client.
- `python/agent_service/app.py`: protected model-session endpoint and request-time model-client resolution.
- `python/tests/test_model_client.py`: API client request, streaming, and error tests.
- `python/tests/test_model_sessions.py`: sidecar session registry tests.
- `python/tests/test_app.py`: protected model-session endpoint tests.
- `python/tests/test_graph.py` and `python/tests/test_execution.py`: session-backed model client coverage.
- `src/shared/types.ts`: schema v3 API provider types.
- `src/features/preferences/preferencesApi.ts`: API provider commands and payload types.
- `src/features/preferences/PreferencesDialog.tsx`: local/API model source UI and provider form.
- `src/features/preferences/PreferencesDialog.test.tsx`: UI tests for API provider state and hidden keys.
- `src/features/task/useTaskEvents.ts`: include `modelSessionId` in sidecar requests.
- `src/app/App.tsx`: prepare model sessions before stream calls and graph runs.
- `src/app/App.test.tsx`: session preparation and fallback behavior tests for the existing send and graph-run handlers.
- `README.md`: note API provider configuration and credential storage.

## Task 1: Preferences Schema V3 And API Provider Data Model

**Files:**
- Modify: `src-tauri/src/preferences.rs`
- Modify: `src-tauri/tests/preferences_tests.rs`
- Modify: `src/shared/types.ts`

- [ ] **Step 1: Write failing Rust preferences tests**

Add these tests to `src-tauri/tests/preferences_tests.rs`:

```rust
#[test]
fn default_preferences_have_schema_version_three_and_local_agent_mode() {
    let preferences = AppPreferences::default();

    assert_eq!(preferences.schema_version, 3);
    assert_eq!(preferences.agent_model_mode, "local");
    assert!(preferences.active_api_provider_id.is_none());
    assert!(preferences.api_provider_configs.is_empty());
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
    assert_eq!(preferences.active_api_provider_id, Some(provider.provider_id));
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

    assert_eq!(removed.credential_ref, format!("alita.api-provider.{}", provider.provider_id));
    assert!(preferences.active_api_provider_id.is_none());
    assert!(preferences.api_provider_configs.is_empty());
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml --test preferences_tests
```

Expected: fails because `agent_model_mode`, `api_provider_configs`, `ApiProviderInput`, `upsert_api_provider_config`, `set_active_api_provider`, and `delete_api_provider_config` do not exist.

- [ ] **Step 3: Add Rust preference types and helpers**

In `src-tauri/src/preferences.rs`, change `PREFERENCES_SCHEMA_VERSION` to `3`, add these structs near `ModelAssignments`, and add the fields to `AppPreferences`:

```rust
const PREFERENCES_SCHEMA_VERSION: u32 = 3;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ApiProviderConfig {
    pub provider_id: String,
    pub provider_type: String,
    pub display_name: String,
    pub base_url: String,
    pub model: String,
    pub credential_ref: String,
    pub enabled: bool,
    pub capabilities: Vec<String>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ApiProviderInput {
    pub provider_id: Option<String>,
    pub provider_type: String,
    pub display_name: String,
    pub base_url: String,
    pub model: String,
    pub enabled: bool,
}
```

Add these fields to `AppPreferences`:

```rust
#[serde(default = "default_agent_model_mode")]
pub agent_model_mode: String,
#[serde(default)]
pub active_api_provider_id: Option<String>,
#[serde(default)]
pub api_provider_configs: Vec<ApiProviderConfig>,
```

Add these helper functions in the same file:

```rust
fn default_agent_model_mode() -> String {
    "local".to_string()
}

pub fn api_provider_credential_ref(provider_id: &str) -> String {
    format!("alita.api-provider.{provider_id}")
}

pub fn provider_default_capabilities(provider_type: &str) -> Vec<String> {
    match provider_type {
        "custom" => vec!["chat_completions".to_string(), "streaming".to_string()],
        _ => vec![
            "chat_completions".to_string(),
            "streaming".to_string(),
            "model_list".to_string(),
        ],
    }
}

pub fn set_agent_model_mode(
    preferences: &mut AppPreferences,
    mode: &str,
) -> Result<(), String> {
    match mode {
        "local" | "api" => {
            preferences.agent_model_mode = mode.to_string();
            Ok(())
        }
        other => Err(format!("unknown agent model mode: {other}")),
    }
}

pub fn upsert_api_provider_config(
    preferences: &mut AppPreferences,
    input: ApiProviderInput,
) -> Result<ApiProviderConfig, String> {
    let provider_type = input.provider_type.trim().to_ascii_lowercase();
    if !matches!(
        provider_type.as_str(),
        "openai" | "deepseek" | "kimi" | "glm" | "minimax" | "custom"
    ) {
        return Err(format!("unknown API provider type: {}", input.provider_type));
    }

    let display_name = input.display_name.trim().to_string();
    if display_name.is_empty() {
        return Err("API provider display name is required".to_string());
    }
    let base_url = input.base_url.trim().trim_end_matches('/').to_string();
    if base_url.is_empty() {
        return Err("API provider base URL is required".to_string());
    }
    let model = input.model.trim().to_string();
    if model.is_empty() {
        return Err("API provider model name is required".to_string());
    }

    let now = Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true);
    if let Some(provider_id) = input.provider_id.as_deref() {
        let existing = preferences
            .api_provider_configs
            .iter_mut()
            .find(|provider| provider.provider_id == provider_id)
            .ok_or_else(|| format!("unknown API provider id: {provider_id}"))?;
        existing.provider_type = provider_type;
        existing.display_name = display_name;
        existing.base_url = base_url;
        existing.model = model;
        existing.enabled = input.enabled;
        existing.capabilities = provider_default_capabilities(&existing.provider_type);
        existing.updated_at = now;
        preferences.agent_model_mode = "api".to_string();
        return Ok(existing.clone());
    }

    let provider_id = Uuid::new_v4().to_string();
    let config = ApiProviderConfig {
        credential_ref: api_provider_credential_ref(&provider_id),
        provider_id: provider_id.clone(),
        provider_type,
        display_name,
        base_url,
        model,
        enabled: input.enabled,
        capabilities: provider_default_capabilities(&input.provider_type),
        created_at: now.clone(),
        updated_at: now,
    };
    preferences.api_provider_configs.push(config.clone());
    preferences.agent_model_mode = "api".to_string();
    if preferences.active_api_provider_id.is_none() {
        preferences.active_api_provider_id = Some(provider_id);
    }
    Ok(config)
}

pub fn set_active_api_provider(
    preferences: &mut AppPreferences,
    provider_id: Option<&str>,
) -> Result<(), String> {
    let Some(provider_id) = provider_id else {
        preferences.active_api_provider_id = None;
        return Ok(());
    };
    if !preferences
        .api_provider_configs
        .iter()
        .any(|provider| provider.provider_id == provider_id)
    {
        return Err(format!("unknown API provider id: {provider_id}"));
    }
    preferences.active_api_provider_id = Some(provider_id.to_string());
    preferences.agent_model_mode = "api".to_string();
    Ok(())
}

pub fn delete_api_provider_config(
    preferences: &mut AppPreferences,
    provider_id: &str,
) -> Result<ApiProviderConfig, String> {
    let index = preferences
        .api_provider_configs
        .iter()
        .position(|provider| provider.provider_id == provider_id)
        .ok_or_else(|| format!("unknown API provider id: {provider_id}"))?;
    let removed = preferences.api_provider_configs.remove(index);
    if preferences.active_api_provider_id.as_deref() == Some(provider_id) {
        preferences.active_api_provider_id = None;
    }
    Ok(removed)
}
```

Update `Default for AppPreferences` so the new fields are initialized to local mode and empty API provider state. Update `load_preferences_from_path` so versions `1 | 2 | 3` deserialize, and ensure `normalize_preferences` sets schema version `3` and local defaults when fields are missing.

- [ ] **Step 4: Update frontend shared types**

In `src/shared/types.ts`, change `AppPreferences.schemaVersion` to `3`, extend `ModelRuntime`, and add:

```ts
export type AgentModelMode = "local" | "api";

export type ApiProviderType =
  | "openai"
  | "deepseek"
  | "kimi"
  | "glm"
  | "minimax"
  | "custom";

export type ApiProviderCapability =
  | "chat_completions"
  | "streaming"
  | "model_list";

export type ApiProviderConfig = {
  providerId: string;
  providerType: ApiProviderType;
  displayName: string;
  baseUrl: string;
  model: string;
  credentialRef: string;
  enabled: boolean;
  capabilities: ApiProviderCapability[];
  hasApiKey?: boolean;
  createdAt: string;
  updatedAt: string;
};
```

Add these fields to `AppPreferences`:

```ts
agentModelMode: AgentModelMode;
activeApiProviderId: string | null;
apiProviderConfigs: ApiProviderConfig[];
```

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml --test preferences_tests
npm run frontend:lint
```

Expected: preferences tests pass; frontend typecheck passes. Commit:

```powershell
git add src-tauri/src/preferences.rs src-tauri/tests/preferences_tests.rs src/shared/types.ts
git commit -m "feat: add api provider preferences"
```

## Task 2: Secure API Credential Store

**Files:**
- Modify: `src-tauri/Cargo.toml`
- Create: `src-tauri/src/api_credentials.rs`
- Modify: `src-tauri/src/lib.rs`
- Create: `src-tauri/tests/api_credentials_tests.rs`

- [ ] **Step 1: Add failing credential tests**

Create `src-tauri/tests/api_credentials_tests.rs`:

```rust
#[path = "../src/api_credentials.rs"]
#[allow(dead_code)]
mod api_credentials;

use api_credentials::{ApiCredentialStore, MemoryApiCredentialStore};

#[test]
fn memory_store_saves_replaces_reads_and_deletes_api_keys() {
    let store = MemoryApiCredentialStore::default();

    store.set_api_key("alita.api-provider.provider-1", "sk-first").unwrap();
    assert_eq!(
        store.get_api_key("alita.api-provider.provider-1").unwrap(),
        Some("sk-first".to_string())
    );

    store.set_api_key("alita.api-provider.provider-1", "sk-second").unwrap();
    assert_eq!(
        store.get_api_key("alita.api-provider.provider-1").unwrap(),
        Some("sk-second".to_string())
    );

    store.delete_api_key("alita.api-provider.provider-1").unwrap();
    assert_eq!(store.get_api_key("alita.api-provider.provider-1").unwrap(), None);
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml --test api_credentials_tests
```

Expected: fails because `api_credentials.rs` does not exist.

- [ ] **Step 3: Add dependency and implementation**

In `src-tauri/Cargo.toml`, add:

```toml
keyring = { version = "3", features = ["windows-native"] }
```

Create `src-tauri/src/api_credentials.rs`:

```rust
use std::{collections::HashMap, sync::Mutex};

const KEYRING_SERVICE: &str = "com.alita.ai-workbench.api-providers";

pub trait ApiCredentialStore: Send + Sync {
    fn set_api_key(&self, credential_ref: &str, api_key: &str) -> Result<(), String>;
    fn get_api_key(&self, credential_ref: &str) -> Result<Option<String>, String>;
    fn delete_api_key(&self, credential_ref: &str) -> Result<(), String>;
}

#[derive(Debug, Default)]
pub struct MemoryApiCredentialStore {
    values: Mutex<HashMap<String, String>>,
}

impl ApiCredentialStore for MemoryApiCredentialStore {
    fn set_api_key(&self, credential_ref: &str, api_key: &str) -> Result<(), String> {
        let credential_ref = validate_credential_ref(credential_ref)?;
        let api_key = validate_api_key(api_key)?;
        self.values
            .lock()
            .map_err(|error| format!("API credential store lock poisoned: {error}"))?
            .insert(credential_ref.to_string(), api_key.to_string());
        Ok(())
    }

    fn get_api_key(&self, credential_ref: &str) -> Result<Option<String>, String> {
        let credential_ref = validate_credential_ref(credential_ref)?;
        Ok(self
            .values
            .lock()
            .map_err(|error| format!("API credential store lock poisoned: {error}"))?
            .get(credential_ref)
            .cloned())
    }

    fn delete_api_key(&self, credential_ref: &str) -> Result<(), String> {
        let credential_ref = validate_credential_ref(credential_ref)?;
        self.values
            .lock()
            .map_err(|error| format!("API credential store lock poisoned: {error}"))?
            .remove(credential_ref);
        Ok(())
    }
}

#[derive(Debug, Default)]
pub struct SystemApiCredentialStore;

impl ApiCredentialStore for SystemApiCredentialStore {
    fn set_api_key(&self, credential_ref: &str, api_key: &str) -> Result<(), String> {
        let credential_ref = validate_credential_ref(credential_ref)?;
        let api_key = validate_api_key(api_key)?;
        let entry = keyring::Entry::new(KEYRING_SERVICE, credential_ref)
            .map_err(|error| format!("failed to open API credential entry: {error}"))?;
        entry
            .set_password(api_key)
            .map_err(|error| format!("failed to save API credential: {error}"))
    }

    fn get_api_key(&self, credential_ref: &str) -> Result<Option<String>, String> {
        let credential_ref = validate_credential_ref(credential_ref)?;
        let entry = keyring::Entry::new(KEYRING_SERVICE, credential_ref)
            .map_err(|error| format!("failed to open API credential entry: {error}"))?;
        match entry.get_password() {
            Ok(value) => Ok(Some(value)),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(error) => Err(format!("failed to read API credential: {error}")),
        }
    }

    fn delete_api_key(&self, credential_ref: &str) -> Result<(), String> {
        let credential_ref = validate_credential_ref(credential_ref)?;
        let entry = keyring::Entry::new(KEYRING_SERVICE, credential_ref)
            .map_err(|error| format!("failed to open API credential entry: {error}"))?;
        match entry.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(error) => Err(format!("failed to delete API credential: {error}")),
        }
    }
}

fn validate_credential_ref(value: &str) -> Result<&str, String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return Err("credential reference is required".to_string());
    }
    Ok(trimmed)
}

fn validate_api_key(value: &str) -> Result<&str, String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return Err("API key is required".to_string());
    }
    Ok(trimmed)
}
```

In `src-tauri/src/lib.rs`, add:

```rust
pub mod api_credentials;
```

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml --test api_credentials_tests
cargo test --manifest-path src-tauri/Cargo.toml --test preferences_tests
```

Expected: both test targets pass. Commit:

```powershell
git add src-tauri/Cargo.toml src-tauri/Cargo.lock src-tauri/src/api_credentials.rs src-tauri/src/lib.rs src-tauri/tests/api_credentials_tests.rs
git commit -m "feat: add api credential store"
```

## Task 3: Agent Model Config Resolver

**Files:**
- Create: `src-tauri/src/agent_model_config.rs`
- Modify: `src-tauri/src/lib.rs`
- Create: `src-tauri/tests/agent_model_config_tests.rs`

- [ ] **Step 1: Write failing resolver tests**

Create `src-tauri/tests/agent_model_config_tests.rs`:

```rust
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml --test agent_model_config_tests
```

Expected: fails because `agent_model_config.rs` does not exist.

- [ ] **Step 3: Add resolver implementation**

Create `src-tauri/src/agent_model_config.rs`:

```rust
use serde::{Deserialize, Serialize};

use crate::{
    api_credentials::ApiCredentialStore,
    preferences::{agent_model_path, AppPreferences},
};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", tag = "mode")]
pub enum AgentModelConfig {
    Local {
        base_url: String,
        model: String,
    },
    Api {
        provider_id: String,
        provider_type: String,
        display_name: String,
        base_url: String,
        model: String,
        api_key: String,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct RegisterModelSessionRequest {
    pub model_config: AgentModelConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct RegisterModelSessionResponse {
    pub model_session_id: String,
}

pub fn resolve_agent_model_config(
    preferences: &AppPreferences,
    credential_store: &dyn ApiCredentialStore,
) -> Result<AgentModelConfig, String> {
    match preferences.agent_model_mode.as_str() {
        "api" => resolve_api_config(preferences, credential_store),
        "local" => resolve_local_config(preferences),
        other => Err(format!("unknown agent model mode: {other}")),
    }
}

fn resolve_local_config(preferences: &AppPreferences) -> Result<AgentModelConfig, String> {
    let model_path = agent_model_path(preferences)
        .ok_or_else(|| "local Agent model is not configured".to_string())?;
    let model = model_path
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("local-llama-cpp")
        .to_string();
    Ok(AgentModelConfig::Local {
        base_url: "http://127.0.0.1:8766".to_string(),
        model,
    })
}

fn resolve_api_config(
    preferences: &AppPreferences,
    credential_store: &dyn ApiCredentialStore,
) -> Result<AgentModelConfig, String> {
    let active_id = preferences
        .active_api_provider_id
        .as_deref()
        .ok_or_else(|| "API Agent provider is not selected".to_string())?;
    let provider = preferences
        .api_provider_configs
        .iter()
        .find(|provider| provider.provider_id == active_id)
        .ok_or_else(|| format!("active API provider does not exist: {active_id}"))?;
    if !provider.enabled {
        return Err(format!("API provider '{}' is disabled", provider.display_name));
    }
    let api_key = credential_store
        .get_api_key(&provider.credential_ref)?
        .ok_or_else(|| format!("API key is not configured for {}", provider.display_name))?;
    Ok(AgentModelConfig::Api {
        provider_id: provider.provider_id.clone(),
        provider_type: provider.provider_type.clone(),
        display_name: provider.display_name.clone(),
        base_url: provider.base_url.clone(),
        model: provider.model.clone(),
        api_key,
    })
}
```

In `src-tauri/src/lib.rs`, add:

```rust
pub mod agent_model_config;
```

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml --test agent_model_config_tests
cargo test --manifest-path src-tauri/Cargo.toml --test preferences_tests
```

Expected: both test targets pass. Commit:

```powershell
git add src-tauri/src/agent_model_config.rs src-tauri/src/lib.rs src-tauri/tests/agent_model_config_tests.rs
git commit -m "feat: resolve agent model configs"
```

## Task 4: Sidecar Model Session Registration

**Files:**
- Modify: `src-tauri/src/agent_client.rs`
- Modify: `src-tauri/tests/agent_client_tests.rs`
- Modify: `python/agent_service/schemas.py`
- Create: `python/agent_service/model_sessions.py`
- Modify: `python/agent_service/app.py`
- Create: `python/tests/test_model_sessions.py`
- Modify: `python/tests/test_app.py`

- [ ] **Step 1: Write failing Rust client test**

Add to `src-tauri/tests/agent_client_tests.rs`:

```rust
#[test]
fn register_model_session_sends_auth_header_and_model_config() {
    let (base_url, server) = spawn_test_server(r#"{"modelSessionId":"session-1"}"#);
    let client = agent_client::AgentClient::new(base_url).with_auth_token("token-session");
    let request = agent_client::RegisterModelSessionRequest {
        model_config: serde_json::json!({
            "mode": "api",
            "providerId": "provider-1",
            "providerType": "openai",
            "displayName": "OpenAI",
            "baseUrl": "https://api.openai.com/v1",
            "model": "gpt-4.1",
            "apiKey": "sk-test"
        }),
    };

    let response = tauri::async_runtime::block_on(client.register_model_session(&request))
        .expect("model session request should succeed");
    let captured = server.join().expect("server should capture request");
    let body: serde_json::Value =
        serde_json::from_str(&captured.body).expect("request body should be JSON");

    assert_eq!(response.model_session_id, "session-1");
    assert_eq!(captured.method, "POST");
    assert_eq!(captured.path, "/agent/model/session");
    assert_eq!(
        captured.header(agent_client::sidecar_token_header()),
        Some("token-session")
    );
    assert_eq!(body["modelConfig"]["apiKey"], "sk-test");
}
```

- [ ] **Step 2: Run Rust test to verify it fails**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml --test agent_client_tests register_model_session_sends_auth_header_and_model_config
```

Expected: fails because model-session request/response types and client method do not exist.

- [ ] **Step 3: Add Rust client method**

In `src-tauri/src/agent_client.rs`, add:

```rust
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct RegisterModelSessionRequest {
    pub model_config: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct RegisterModelSessionResponse {
    pub model_session_id: String,
}
```

Add this method to `impl AgentClient`:

```rust
pub async fn register_model_session(
    &self,
    request: &RegisterModelSessionRequest,
) -> Result<RegisterModelSessionResponse, String> {
    let url = format!("{}/agent/model/session", self.base_url.trim_end_matches('/'));
    let mut request_builder = self.http.post(url).json(request);
    if let Some(token) = &self.auth_token {
        request_builder = request_builder.header(sidecar_token_header(), token);
    }

    let response = request_builder
        .send()
        .await
        .map_err(|error| format!("model session request failed: {error}"))?;

    if !response.status().is_success() {
        return Err(sidecar_error_message(response, "model session request").await);
    }

    response
        .json::<RegisterModelSessionResponse>()
        .await
        .map_err(|error| format!("invalid model session response: {error}"))
}
```

- [ ] **Step 4: Write Python session tests**

Create `python/tests/test_model_sessions.py`:

```python
from __future__ import annotations

import pytest

from agent_service.model_sessions import ModelSessionRegistry
from agent_service.schemas import AgentModelConfig


def test_model_session_registry_consumes_registered_config_once() -> None:
    registry = ModelSessionRegistry()
    config = AgentModelConfig(
        mode="api",
        provider_id="provider-1",
        provider_type="openai",
        display_name="OpenAI",
        base_url="https://api.openai.com/v1",
        model="gpt-4.1",
        api_key="sk-test",
    )

    session_id = registry.register(config)

    assert registry.consume(session_id) == config
    assert registry.consume(session_id) is None


def test_model_session_registry_rejects_empty_session_id() -> None:
    registry = ModelSessionRegistry()

    with pytest.raises(ValueError, match="model session id is required"):
        registry.consume("")
```

Add this test to `python/tests/test_app.py`:

```python
def test_register_model_session_requires_sidecar_token(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from agent_service.app import app

    monkeypatch.setenv("ALITA_SIDECAR_TOKEN", "expected-token")
    client = TestClient(app)

    response = client.post(
        "/agent/model/session",
        json={
            "modelConfig": {
                "mode": "api",
                "providerId": "provider-1",
                "providerType": "openai",
                "displayName": "OpenAI",
                "baseUrl": "https://api.openai.com/v1",
                "model": "gpt-4.1",
                "apiKey": "sk-test",
            }
        },
    )

    assert response.status_code == 401
```

- [ ] **Step 5: Run Python tests to verify they fail**

Run:

```powershell
cd python
python -m pytest tests/test_model_sessions.py tests/test_app.py -q
```

Expected: fails because model session schemas, registry, and endpoint do not exist.

- [ ] **Step 6: Add Python schemas, registry, and endpoint**

In `python/agent_service/schemas.py`, add:

```python
class AgentModelConfig(BaseModel):
    mode: Literal["local", "api"]
    base_url: str
    model: str
    provider_id: str | None = None
    provider_type: str | None = None
    display_name: str | None = None
    api_key: str | None = None


class RegisterModelSessionRequest(BaseModel):
    model_config: AgentModelConfig = Field(alias="modelConfig")


class RegisterModelSessionResponse(BaseModel):
    model_session_id: str = Field(alias="modelSessionId")
```

Add optional session IDs:

```python
class UserMessage(BaseModel):
    task_id: str
    content: str
    attachments: list[Attachment] = Field(default_factory=list)
    model_session_id: str | None = None


class RunGraphRequest(BaseModel):
    task_id: str
    project_path: str
    graph: RunGraph
    attachments: list[RunAttachment] = Field(default_factory=list)
    run_id: str = Field(default_factory=lambda: f"run-{uuid4()}")
    mode: RunMode = Field(default_factory=RunMode)
    disabled_tool_ids: list[str] = Field(default_factory=list)
    approved_permissions: list[str] = Field(default_factory=list)
    model_session_id: str | None = None
```

Create `python/agent_service/model_sessions.py`:

```python
from __future__ import annotations

from threading import Lock
from uuid import uuid4

from agent_service.schemas import AgentModelConfig


class ModelSessionRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._configs: dict[str, AgentModelConfig] = {}

    def register(self, config: AgentModelConfig) -> str:
        session_id = f"model-session-{uuid4()}"
        with self._lock:
            self._configs[session_id] = config
        return session_id

    def consume(self, session_id: str) -> AgentModelConfig | None:
        if not session_id.strip():
            raise ValueError("model session id is required")
        with self._lock:
            return self._configs.pop(session_id, None)


DEFAULT_MODEL_SESSION_REGISTRY = ModelSessionRegistry()
```

In `python/agent_service/app.py`, import the new types and add:

```python
from agent_service.model_sessions import DEFAULT_MODEL_SESSION_REGISTRY
from agent_service.schemas import RegisterModelSessionRequest, RegisterModelSessionResponse


@app.post("/agent/model/session", response_model=RegisterModelSessionResponse)
def register_model_session(
    request: RegisterModelSessionRequest,
    _auth: None = Depends(require_sidecar_token),
) -> RegisterModelSessionResponse:
    session_id = DEFAULT_MODEL_SESSION_REGISTRY.register(request.model_config)
    return RegisterModelSessionResponse(modelSessionId=session_id)
```

- [ ] **Step 7: Run tests and commit**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml --test agent_client_tests register_model_session_sends_auth_header_and_model_config
cd python
python -m pytest tests/test_model_sessions.py tests/test_app.py -q
```

Expected: listed tests pass. Commit:

```powershell
git add src-tauri/src/agent_client.rs src-tauri/tests/agent_client_tests.rs python/agent_service/schemas.py python/agent_service/model_sessions.py python/agent_service/app.py python/tests/test_model_sessions.py python/tests/test_app.py
git commit -m "feat: add sidecar model sessions"
```

## Task 5: OpenAI-Compatible Python Model Client

**Files:**
- Modify: `python/agent_service/model_client.py`
- Modify: `python/tests/test_model_client.py`

- [ ] **Step 1: Add failing API client tests**

Add to `python/tests/test_model_client.py`:

```python
from agent_service.model_client import (
    AgentModelClientConfig,
    OpenAICompatibleModelClient,
    create_model_client,
)


def test_openai_compatible_client_posts_chat_request_with_authorization() -> None:
    calls: list[tuple[str, dict, float, dict[str, str]]] = []

    def transport(url: str, payload: dict, timeout: float, headers: dict[str, str]) -> dict:
        calls.append((url, payload, timeout, headers))
        return {"choices": [{"message": {"content": "api reply"}}]}

    client = OpenAICompatibleModelClient(
        AgentModelClientConfig(
            mode="api",
            enabled=True,
            base_url="https://api.openai.com/v1",
            model="gpt-4.1",
            api_key="sk-test",
            provider_display_name="OpenAI",
        ),
        transport=transport,
    )

    result = client.chat([ChatMessage(role="user", content="hello")])

    assert result == "api reply"
    assert calls == [
        (
            "https://api.openai.com/v1/chat/completions",
            {
                "model": "gpt-4.1",
                "messages": [{"role": "user", "content": "hello"}],
                "temperature": 0.2,
                "max_tokens": 1024,
                "stream": False,
            },
            60.0,
            {"Authorization": "Bearer sk-test", "Content-Type": "application/json"},
        )
    ]


def test_openai_compatible_client_streams_chat_chunks() -> None:
    def stream_transport(url: str, payload: dict, timeout: float, headers: dict[str, str]):
        return [
            b'data: {"choices":[{"delta":{"content":"A"}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":"B"}}]}\n\n',
            b"data: [DONE]\n\n",
        ]

    client = OpenAICompatibleModelClient(
        AgentModelClientConfig(
            mode="api",
            enabled=True,
            base_url="https://api.deepseek.com",
            model="deepseek-chat",
            api_key="sk-test",
            provider_display_name="DeepSeek",
        ),
        stream_transport=stream_transport,
    )

    assert list(client.stream_chat([ChatMessage(role="user", content="hello")])) == ["A", "B"]


def test_openai_compatible_client_rejects_missing_api_key() -> None:
    client = OpenAICompatibleModelClient(
        AgentModelClientConfig(
            mode="api",
            enabled=True,
            base_url="https://api.openai.com/v1",
            model="gpt-4.1",
            api_key=None,
            provider_display_name="OpenAI",
        )
    )

    with pytest.raises(ModelRuntimeDisabled, match="API key is not configured"):
        client.chat([ChatMessage(role="user", content="hello")])


def test_create_model_client_returns_api_client_for_api_config() -> None:
    client = create_model_client(
        AgentModelClientConfig(
            mode="api",
            enabled=True,
            base_url="https://api.openai.com/v1",
            model="gpt-4.1",
            api_key="sk-test",
            provider_display_name="OpenAI",
        )
    )

    assert isinstance(client, OpenAICompatibleModelClient)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
cd python
python -m pytest tests/test_model_client.py -q
```

Expected: fails because API client config and client do not exist.

- [ ] **Step 3: Implement API client**

In `python/agent_service/model_client.py`, add:

```python
@dataclass(frozen=True)
class AgentModelClientConfig:
    mode: Literal["local", "api"] = "local"
    enabled: bool = False
    base_url: str = "http://127.0.0.1:8766"
    model: str = "local-llama-cpp"
    api_key: str | None = None
    provider_display_name: str = "API provider"
    timeout_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> "AgentModelClientConfig":
        mode = os.getenv("ALITA_AGENT_MODEL_MODE", "local").strip().lower()
        if mode == "api":
            api_key = os.getenv("ALITA_API_KEY", "").strip() or None
            return cls(
                mode="api",
                enabled=bool(api_key),
                base_url=os.getenv("ALITA_API_BASE_URL", "").strip().rstrip("/"),
                model=os.getenv("ALITA_API_MODEL", "").strip(),
                api_key=api_key,
                provider_display_name=os.getenv("ALITA_API_PROVIDER_NAME", "API provider"),
            )
        llama = ModelClientConfig.from_env()
        return cls(
            mode="local",
            enabled=llama.enabled,
            base_url=llama.base_url,
            model=llama.model,
            timeout_seconds=llama.timeout_seconds,
        )
```

Add API transport aliases:

```python
ApiTransport = Callable[[str, dict, float, dict[str, str]], dict]
ApiStreamTransport = Callable[[str, dict, float, dict[str, str]], Iterable[bytes | str]]
```

Add the client:

```python
class OpenAICompatibleModelClient:
    def __init__(
        self,
        config: AgentModelClientConfig,
        *,
        transport: ApiTransport | None = None,
        stream_transport: ApiStreamTransport | None = None,
    ) -> None:
        self.config = config
        self._transport = transport or _post_json_with_headers
        self._stream_transport = stream_transport or _post_json_stream_with_headers

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str:
        self._ensure_enabled()
        payload = self._payload(messages, temperature, max_tokens, stream=False)
        response = self._transport(
            f"{self.config.base_url.rstrip('/')}/chat/completions",
            payload,
            self.config.timeout_seconds,
            self._headers(),
        )
        content = _extract_chat_content(response)
        if content.strip():
            return content
        raise ModelRuntimeRequestFailed(
            f"{self.config.provider_display_name} returned an empty chat response"
        )

    def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> Iterator[str]:
        self._ensure_enabled()
        payload = self._payload(messages, temperature, max_tokens, stream=True)
        for data in _iter_sse_data(
            self._stream_transport(
                f"{self.config.base_url.rstrip('/')}/chat/completions",
                payload,
                self.config.timeout_seconds,
                self._headers(),
            )
        ):
            if data == "[DONE]":
                break
            try:
                parsed = json.loads(data)
                delta = parsed["choices"][0]["delta"].get("content", "")
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
                raise ModelRuntimeRequestFailed(
                    f"{self.config.provider_display_name} returned an unexpected streaming response shape"
                ) from error
            if delta:
                yield delta

    def _ensure_enabled(self) -> None:
        if not self.config.api_key:
            raise ModelRuntimeDisabled(
                f"{self.config.provider_display_name} API key is not configured"
            )
        if not self.config.base_url.strip():
            raise ModelRuntimeDisabled(
                f"{self.config.provider_display_name} base URL is not configured"
            )
        if not self.config.model.strip():
            raise ModelRuntimeDisabled(
                f"{self.config.provider_display_name} model is not configured"
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(
        self,
        messages: list[ChatMessage],
        temperature: float,
        max_tokens: int,
        *,
        stream: bool,
    ) -> dict:
        return {
            "model": self.config.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
```

Add helpers:

```python
def create_model_client(config: AgentModelClientConfig | None = None):
    resolved = config or AgentModelClientConfig.from_env()
    if resolved.mode == "api":
        return OpenAICompatibleModelClient(resolved)
    return LlamaCppModelClient(
        ModelClientConfig(
            enabled=resolved.enabled,
            base_url=resolved.base_url,
            model=resolved.model,
            timeout_seconds=resolved.timeout_seconds,
        )
    )


def _post_json_with_headers(
    url: str,
    payload: dict,
    timeout: float,
    headers: dict[str, str],
) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        safe_body = error.read().decode("utf-8", errors="replace")[:500]
        raise ModelRuntimeRequestFailed(
            f"API chat request returned HTTP {error.code}: {safe_body}"
        ) from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise ModelRuntimeRequestFailed(f"API chat request failed: {error}") from error


def _post_json_stream_with_headers(
    url: str,
    payload: dict,
    timeout: float,
    headers: dict[str, str],
) -> Iterable[bytes]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            yield from response
    except urllib.error.HTTPError as error:
        safe_body = error.read().decode("utf-8", errors="replace")[:500]
        raise ModelRuntimeRequestFailed(
            f"API streaming chat request returned HTTP {error.code}: {safe_body}"
        ) from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise ModelRuntimeRequestFailed(f"API streaming chat request failed: {error}") from error
```

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
cd python
python -m pytest tests/test_model_client.py -q
```

Expected: model client tests pass. Commit:

```powershell
git add python/agent_service/model_client.py python/tests/test_model_client.py
git commit -m "feat: add openai compatible model client"
```

## Task 6: Use Model Sessions In Chat And Graph Execution

**Files:**
- Modify: `python/agent_service/app.py`
- Modify: `python/agent_service/graph.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/tests/test_graph.py`
- Modify: `python/tests/test_execution.py`

- [ ] **Step 1: Add failing graph/session test**

Add to `python/tests/test_graph.py`:

```python
def test_run_agent_uses_model_session_client_for_chat() -> None:
    from agent_service.graph import run_agent
    from agent_service.model_sessions import ModelSessionRegistry
    from agent_service.schemas import AgentModelConfig, UserMessage

    class FakeClient:
        def chat(self, messages, *, temperature=0.2, max_tokens=1024):
            return "api session reply"

    registry = ModelSessionRegistry()
    session_id = registry.register(
        AgentModelConfig(
            mode="api",
            provider_id="provider-1",
            provider_type="openai",
            display_name="OpenAI",
            base_url="https://api.openai.com/v1",
            model="gpt-4.1",
            api_key="sk-test",
        )
    )

    events = run_agent(
        UserMessage(task_id="task-1", content="hello", model_session_id=session_id),
        model_client_factory=lambda config: FakeClient(),
        model_session_registry=registry,
    )

    assert events[0].payload["message"]["content"] == "api session reply"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
cd python
python -m pytest tests/test_graph.py::test_run_agent_uses_model_session_client_for_chat -q
```

Expected: fails because graph functions do not accept model session registry or factory.

- [ ] **Step 3: Update graph model-client resolution**

In `python/agent_service/graph.py`, import:

```python
from agent_service.model_client import AgentModelClientConfig, create_model_client
from agent_service.model_sessions import DEFAULT_MODEL_SESSION_REGISTRY, ModelSessionRegistry
from agent_service.schemas import AgentModelConfig
```

Add:

```python
def _client_config_from_session(config: AgentModelConfig) -> AgentModelClientConfig:
    return AgentModelClientConfig(
        mode=config.mode,
        enabled=True,
        base_url=config.base_url,
        model=config.model,
        api_key=config.api_key,
        provider_display_name=config.display_name or config.provider_type or "API provider",
    )


def _model_client_for_message(
    message: UserMessage,
    *,
    model_client: ModelClient | None,
    model_client_factory=create_model_client,
    model_session_registry: ModelSessionRegistry = DEFAULT_MODEL_SESSION_REGISTRY,
) -> ModelClient:
    if model_client is not None:
        return model_client
    if message.model_session_id:
        session_config = model_session_registry.consume(message.model_session_id)
        if session_config is None:
            raise ModelRuntimeDisabled("Agent model session expired or was not found")
        return model_client_factory(_client_config_from_session(session_config))
    return create_model_client()
```

Update `build_graph`, `answer_with_model`, `run_agent`, and `stream_agent_events` signatures to accept `model_client_factory` and `model_session_registry`, then replace direct `LlamaCppModelClient()` construction with `_model_client_for_message(...)`.

- [ ] **Step 4: Update graph execution request path**

In `python/agent_service/app.py`, add a helper:

```python
def _model_client_for_session(model_session_id: str | None):
    if not model_session_id:
        return create_model_client()
    config = DEFAULT_MODEL_SESSION_REGISTRY.consume(model_session_id)
    if config is None:
        raise HTTPException(status_code=409, detail="Agent model session expired or was not found")
    return create_model_client(
        AgentModelClientConfig(
            mode=config.mode,
            enabled=True,
            base_url=config.base_url,
            model=config.model,
            api_key=config.api_key,
            provider_display_name=config.display_name or config.provider_type or "API provider",
        )
    )
```

Use it in endpoints:

```python
return run_agent(
    message,
    model_client=_model_client_for_session(message.model_session_id),
)
```

For streams, pass the resolved client into `stream_agent_events`. For graph runs, pass it into `run_graph_events(request, model_client=...)`.

- [ ] **Step 5: Add graph execution test**

Add to `python/tests/test_execution.py`:

```python
def test_document_flow_executor_uses_injected_model_client_for_model_nodes() -> None:
    from agent_service.execution import DocumentFlowExecutor
    from agent_service.node_output import NodeOutput
    from agent_service.schemas import RunGraphRequest, RunGraph

    class FakeModelClient:
        def chat(self, messages, *, temperature=0.2, max_tokens=1024):
            return "model output"

    request = RunGraphRequest(
        task_id="task-1",
        project_path="D:\\Project\\demo.alita",
        graph=RunGraph(graphId="graph-1", nodes=[], edges=[]),
    )
    executor = DocumentFlowExecutor(request, model_client=FakeModelClient())

    output = executor.run(
        "content-organize",
        {"document-parse": NodeOutput(values={"text": "source text"})},
    )

    assert output.values["outline"] == "model output"
```

- [ ] **Step 6: Run tests and commit**

Run:

```powershell
cd python
python -m pytest tests/test_graph.py tests/test_execution.py tests/test_model_sessions.py tests/test_model_client.py -q
```

Expected: listed Python tests pass. Commit:

```powershell
git add python/agent_service/app.py python/agent_service/graph.py python/agent_service/execution.py python/tests/test_graph.py python/tests/test_execution.py
git commit -m "feat: route agent calls through model sessions"
```

## Task 7: Tauri Commands For API Provider Management

**Files:**
- Modify: `src-tauri/src/commands.rs`
- Modify: `src-tauri/src/lib.rs`
- Modify: `src-tauri/tests/preferences_tests.rs`

- [ ] **Step 1: Add command payload tests**

Add to `src-tauri/tests/preferences_tests.rs`:

```rust
#[test]
fn provider_preset_defaults_are_editable_openai_compatible_roots() {
    let deepseek = api_provider_preset("deepseek").unwrap();
    let custom = api_provider_preset("custom").unwrap();

    assert_eq!(deepseek.provider_type, "deepseek");
    assert_eq!(deepseek.base_url, "https://api.deepseek.com");
    assert_eq!(custom.provider_type, "custom");
    assert_eq!(custom.base_url, "");
}
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml --test preferences_tests provider_preset_defaults_are_editable_openai_compatible_roots
```

Expected: fails because `api_provider_preset` does not exist.

- [ ] **Step 3: Add provider presets**

In `src-tauri/src/preferences.rs`, add:

```rust
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ApiProviderPreset {
    pub provider_type: String,
    pub display_name: String,
    pub base_url: String,
}

pub fn api_provider_preset(provider_type: &str) -> Result<ApiProviderPreset, String> {
    let preset = match provider_type {
        "openai" => ("openai", "OpenAI", "https://api.openai.com/v1"),
        "deepseek" => ("deepseek", "DeepSeek", "https://api.deepseek.com"),
        "kimi" => ("kimi", "Kimi", "https://api.moonshot.ai/v1"),
        "glm" => ("glm", "GLM", "https://open.bigmodel.cn/api/paas/v4"),
        "minimax" => ("minimax", "MiniMax", "https://api.minimax.io/v1"),
        "custom" => ("custom", "Custom API", ""),
        other => return Err(format!("unknown API provider type: {other}")),
    };
    Ok(ApiProviderPreset {
        provider_type: preset.0.to_string(),
        display_name: preset.1.to_string(),
        base_url: preset.2.to_string(),
    })
}
```

- [ ] **Step 4: Add command payloads and handlers**

In `src-tauri/src/commands.rs`, import new helpers:

```rust
use crate::{
    api_credentials::{ApiCredentialStore, SystemApiCredentialStore},
    agent_model_config::{resolve_agent_model_config, RegisterModelSessionRequest},
};
```

Add payload structs:

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SetAgentModelModePayload {
    pub mode: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SaveApiProviderPayload {
    pub provider_id: Option<String>,
    pub provider_type: String,
    pub display_name: String,
    pub base_url: String,
    pub model: String,
    pub enabled: bool,
    pub api_key: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ApiProviderIdPayload {
    pub provider_id: String,
}
```

Add handlers:

```rust
#[tauri::command]
pub async fn set_agent_model_mode_command(
    app: AppHandle,
    payload: SetAgentModelModePayload,
) -> Result<PreferencesView, String> {
    let (path, mut preferences) = load_preferences_for_app(&app)?;
    crate::preferences::set_agent_model_mode(&mut preferences, &payload.mode)?;
    save_preferences_to_path(&path, &preferences)?;
    let tools = summarize_tool_manifests(packages_root(), &preferences);
    Ok(PreferencesView { preferences, tools })
}

#[tauri::command]
pub async fn save_api_provider_config(
    app: AppHandle,
    payload: SaveApiProviderPayload,
) -> Result<PreferencesView, String> {
    let (path, mut preferences) = load_preferences_for_app(&app)?;
    let provider = crate::preferences::upsert_api_provider_config(
        &mut preferences,
        crate::preferences::ApiProviderInput {
            provider_id: payload.provider_id,
            provider_type: payload.provider_type,
            display_name: payload.display_name,
            base_url: payload.base_url,
            model: payload.model,
            enabled: payload.enabled,
        },
    )?;
    if let Some(api_key) = payload.api_key.as_deref().filter(|value| !value.trim().is_empty()) {
        SystemApiCredentialStore.set_api_key(&provider.credential_ref, api_key)?;
    }
    save_preferences_to_path(&path, &preferences)?;
    let tools = summarize_tool_manifests(packages_root(), &preferences);
    Ok(PreferencesView { preferences, tools })
}

#[tauri::command]
pub async fn delete_api_provider_config_command(
    app: AppHandle,
    payload: ApiProviderIdPayload,
) -> Result<PreferencesView, String> {
    let (path, mut preferences) = load_preferences_for_app(&app)?;
    let removed = crate::preferences::delete_api_provider_config(
        &mut preferences,
        &payload.provider_id,
    )?;
    SystemApiCredentialStore.delete_api_key(&removed.credential_ref)?;
    save_preferences_to_path(&path, &preferences)?;
    let tools = summarize_tool_manifests(packages_root(), &preferences);
    Ok(PreferencesView { preferences, tools })
}

#[tauri::command]
pub async fn set_active_api_provider_command(
    app: AppHandle,
    payload: ApiProviderIdPayload,
) -> Result<PreferencesView, String> {
    let (path, mut preferences) = load_preferences_for_app(&app)?;
    crate::preferences::set_active_api_provider(&mut preferences, Some(&payload.provider_id))?;
    save_preferences_to_path(&path, &preferences)?;
    let tools = summarize_tool_manifests(packages_root(), &preferences);
    Ok(PreferencesView { preferences, tools })
}
```

Register commands in `src-tauri/src/lib.rs`.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml --test preferences_tests
cargo test --manifest-path src-tauri/Cargo.toml --test api_credentials_tests
```

Expected: tests pass. Commit:

```powershell
git add src-tauri/src/preferences.rs src-tauri/src/commands.rs src-tauri/src/lib.rs src-tauri/tests/preferences_tests.rs
git commit -m "feat: add api provider commands"
```

## Task 8: Prepare Model Sessions From Tauri

**Files:**
- Modify: `src-tauri/src/commands.rs`
- Modify: `src-tauri/src/agent_client.rs`
- Modify: `src-tauri/tests/agent_model_config_tests.rs`

- [ ] **Step 1: Add command handler implementation**

Add to `src-tauri/src/commands.rs`:

```rust
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct PrepareAgentModelSessionResponse {
    pub model_session_id: String,
}

#[tauri::command]
pub async fn prepare_agent_model_session(
    app: AppHandle,
) -> Result<PrepareAgentModelSessionResponse, String> {
    let (_, preferences) = load_preferences_for_app(&app)?;
    let config = resolve_agent_model_config(&preferences, &SystemApiCredentialStore)?;
    let request = RegisterModelSessionRequest {
        model_config: serde_json::to_value(config)
            .map_err(|error| format!("failed to serialize model config: {error}"))?,
    };
    let client = AgentClient::new(crate::sidecar::agent_base_url())
        .with_auth_token(crate::sidecar::sidecar_auth_token(&app)?);
    let response = client.register_model_session(&request).await?;
    Ok(PrepareAgentModelSessionResponse {
        model_session_id: response.model_session_id,
    })
}
```

Register `commands::prepare_agent_model_session` in `src-tauri/src/lib.rs`.

- [ ] **Step 2: Add provider helper commands**

Add model list and connection command payloads to `src-tauri/src/commands.rs`:

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TestApiProviderPayload {
    pub provider_id: Option<String>,
    pub provider_type: String,
    pub display_name: String,
    pub base_url: String,
    pub model: String,
    pub api_key: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ApiProviderConnectionResult {
    pub ok: bool,
    pub message: String,
    pub models: Vec<String>,
}
```

Implement helper calls with `reqwest` in Rust so provider testing does not require storing an invalid key. The command must redact the key from every returned error string before returning it.

- [ ] **Step 3: Run Rust tests and commit**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml --test agent_client_tests
cargo test --manifest-path src-tauri/Cargo.toml --test agent_model_config_tests
```

Expected: tests pass. Commit:

```powershell
git add src-tauri/src/commands.rs src-tauri/src/lib.rs src-tauri/src/agent_client.rs
git commit -m "feat: prepare agent model sessions"
```

## Task 9: Frontend API Types And Preferences API

**Files:**
- Modify: `src/features/preferences/preferencesApi.ts`
- Modify: `src/features/task/useTaskEvents.ts`

- [ ] **Step 1: Add TypeScript API functions**

In `src/features/preferences/preferencesApi.ts`, add:

```ts
import type { AgentModelMode, ApiProviderConfig, ApiProviderType } from "../../shared/types";

export type SaveApiProviderPayload = {
  providerId?: string;
  providerType: ApiProviderType;
  displayName: string;
  baseUrl: string;
  model: string;
  enabled: boolean;
  apiKey?: string;
};

export type ApiProviderConnectionResult = {
  ok: boolean;
  message: string;
  models: string[];
};

export async function setAgentModelMode(
  mode: AgentModelMode,
): Promise<PreferencesView> {
  return invoke<PreferencesView>("set_agent_model_mode_command", {
    payload: { mode },
  });
}

export async function saveApiProviderConfig(
  payload: SaveApiProviderPayload,
): Promise<PreferencesView> {
  return invoke<PreferencesView>("save_api_provider_config", { payload });
}

export async function deleteApiProviderConfig(
  providerId: string,
): Promise<PreferencesView> {
  return invoke<PreferencesView>("delete_api_provider_config_command", {
    payload: { providerId },
  });
}

export async function setActiveApiProvider(
  providerId: string,
): Promise<PreferencesView> {
  return invoke<PreferencesView>("set_active_api_provider_command", {
    payload: { providerId },
  });
}

export async function prepareAgentModelSession(): Promise<string | null> {
  if (!isTauriRuntime()) {
    return null;
  }
  const response = await invoke<{ modelSessionId: string }>(
    "prepare_agent_model_session",
  );
  return response.modelSessionId;
}
```

- [ ] **Step 2: Add model session IDs to task payloads**

In `src/features/task/useTaskEvents.ts`, update payload types:

```ts
export type SubmitMessagePayload = {
  taskId: string;
  content: string;
  attachments: ChatAttachment[];
  modelSessionId?: string | null;
};

export type RunNodeGraphPayload = {
  runId: string;
  taskId: string;
  projectPath: string;
  graph: NodeGraph;
  attachments: ChatAttachment[];
  mode: RunNodeGraphMode;
  disabledToolIds?: string[];
  approvedPermissions?: string[];
  modelSessionId?: string | null;
  signal?: AbortSignal;
};
```

Update `toSidecarMessage` and graph request JSON:

```ts
function toSidecarMessage(payload: SubmitMessagePayload) {
  return {
    task_id: payload.taskId,
    content: payload.content,
    attachments: payload.attachments.map(toSidecarAttachment),
    model_session_id: payload.modelSessionId ?? null,
  };
}
```

Add `model_session_id: payload.modelSessionId ?? null` to `runNodeGraphStream` request body.

- [ ] **Step 3: Run frontend typecheck and commit**

Run:

```powershell
npm run frontend:lint
```

Expected: typecheck passes. Commit:

```powershell
git add src/features/preferences/preferencesApi.ts src/features/task/useTaskEvents.ts
git commit -m "feat: add frontend api provider client functions"
```

## Task 10: Preferences UI For Local/API Agent Source

**Files:**
- Modify: `src/features/preferences/PreferencesDialog.tsx`
- Modify: `src/features/preferences/PreferencesDialog.test.tsx`
- Modify: `src/app/App.tsx`

- [ ] **Step 1: Update failing PreferencesDialog test**

Update `PreferencesDialog.test.tsx` fixture to `schemaVersion: 3` and add one API provider:

```ts
agentModelMode: "api",
activeApiProviderId: "api-1",
apiProviderConfigs: [
  {
    providerId: "api-1",
    providerType: "openai",
    displayName: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
    model: "gpt-4.1",
    credentialRef: "alita.api-provider.api-1",
    enabled: true,
    capabilities: ["chat_completions", "streaming", "model_list"],
    hasApiKey: true,
    createdAt: "2026-05-24T00:00:00.000Z",
    updatedAt: "2026-05-24T00:00:00.000Z",
  },
],
```

Add assertions:

```ts
expect(markup).toContain("Agent 模型来源");
expect(markup).toContain("本地模型");
expect(markup).toContain("API 模型");
expect(markup).toContain("API 供应商");
expect(markup).toContain("OpenAI");
expect(markup).toContain("gpt-4.1");
expect(markup).toContain("密钥已配置");
expect(markup).not.toContain("sk-test");
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
npm run frontend:test -- PreferencesDialog.test.tsx
```

Expected: fails because UI does not render API provider controls.

- [ ] **Step 3: Add PreferencesDialog props and UI**

Extend `PreferencesDialogProps`:

```ts
onSetAgentModelMode(mode: AgentModelMode): void;
onSaveApiProvider(payload: SaveApiProviderPayload): void;
onDeleteApiProvider(providerId: string): void;
onSetActiveApiProvider(providerId: string): void;
```

Render an Agent model source section before the model library list:

```tsx
<section className="preferencesSection">
  <div className="preferencesSectionHeader">
    <h3>Agent 模型配置</h3>
  </div>
  <div className="modelSourceControl" aria-label="Agent 模型来源">
    <button
      className={view.preferences.agentModelMode === "local" ? "primaryButton" : "secondaryButton"}
      onClick={() => onSetAgentModelMode("local")}
      type="button"
    >
      本地模型
    </button>
    <button
      className={view.preferences.agentModelMode === "api" ? "primaryButton" : "secondaryButton"}
      onClick={() => onSetAgentModelMode("api")}
      type="button"
    >
      API 模型
    </button>
  </div>
  {view.preferences.agentModelMode === "api" ? (
    <ApiProviderList
      activeProviderId={view.preferences.activeApiProviderId}
      providers={view.preferences.apiProviderConfigs}
      onDeleteApiProvider={onDeleteApiProvider}
      onSetActiveApiProvider={onSetActiveApiProvider}
    />
  ) : null}
</section>
```

Add a focused `ApiProviderList` helper in the same file:

```tsx
function ApiProviderList({
  activeProviderId,
  providers,
  onDeleteApiProvider,
  onSetActiveApiProvider,
}: {
  activeProviderId: string | null;
  providers: ApiProviderConfig[];
  onDeleteApiProvider(providerId: string): void;
  onSetActiveApiProvider(providerId: string): void;
}) {
  return (
    <div className="apiProviderList" aria-label="API 供应商">
      {providers.length === 0 ? <p>还没有配置 API 供应商。</p> : null}
      {providers.map((provider) => (
        <div className="apiProviderItem" key={provider.providerId}>
          <div>
            <strong>{provider.displayName}</strong>
            <span>{provider.model}</span>
            <span>{provider.baseUrl}</span>
            <span>{provider.hasApiKey ? "密钥已配置" : "未配置密钥"}</span>
          </div>
          <div className="preferencesActions">
            {activeProviderId === provider.providerId ? (
              <span className="modelDefaultBadge">当前 Agent API</span>
            ) : (
              <button
                className="secondaryButton compactButton"
                onClick={() => onSetActiveApiProvider(provider.providerId)}
                type="button"
              >
                设为当前 API
              </button>
            )}
            <button
              className="secondaryButton compactButton"
              onClick={() => onDeleteApiProvider(provider.providerId)}
              type="button"
            >
              删除
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
```

Add create/edit form in the next UI pass after this test is green; keep this first UI step focused on rendering and mode selection.

- [ ] **Step 4: Wire App handlers**

In `src/app/App.tsx`, import the new API functions and add handlers:

```ts
const handleSetAgentModelMode = async (mode: AgentModelMode) => {
  try {
    setPreferencesError(null);
    applyPreferencesView(await setAgentModelMode(mode));
  } catch (error) {
    setPreferencesError(String(error));
  }
};

const handleDeleteApiProvider = async (providerId: string) => {
  try {
    setPreferencesError(null);
    applyPreferencesView(await deleteApiProviderConfig(providerId));
  } catch (error) {
    setPreferencesError(String(error));
  }
};

const handleSetActiveApiProvider = async (providerId: string) => {
  try {
    setPreferencesError(null);
    applyPreferencesView(await setActiveApiProvider(providerId));
  } catch (error) {
    setPreferencesError(String(error));
  }
};
```

Pass handlers into `PreferencesDialog`.

- [ ] **Step 5: Run frontend tests and commit**

Run:

```powershell
npm run frontend:test -- PreferencesDialog.test.tsx
npm run frontend:lint
```

Expected: tests and typecheck pass. Commit:

```powershell
git add src/features/preferences/PreferencesDialog.tsx src/features/preferences/PreferencesDialog.test.tsx src/app/App.tsx
git commit -m "feat: show api agent model preferences"
```

## Task 11: Prepare Model Sessions In Frontend Request Flow

**Files:**
- Modify: `src/app/App.tsx`
- Modify: `src/app/App.test.tsx`
- Modify: `src/features/task/useTaskEvents.test.ts`

- [ ] **Step 1: Add task event serialization test**

Export `toSidecarMessageForTest` from `src/features/task/useTaskEvents.ts`, then add this test to `src/features/task/useTaskEvents.test.ts`:

```ts
import { toSidecarMessageForTest } from "./useTaskEvents";

it("includes model session id in sidecar message payload", () => {
  expect(
    toSidecarMessageForTest({
      taskId: "task-1",
      content: "hello",
      attachments: [],
      modelSessionId: "model-session-1",
    }),
  ).toEqual({
    task_id: "task-1",
    content: "hello",
    attachments: [],
    model_session_id: "model-session-1",
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
npm run frontend:test -- useTaskEvents.test.ts
```

Expected: fails until the test helper and session field are present.

- [ ] **Step 3: Prepare session before each Agent call**

In `src/app/App.tsx`, import `prepareAgentModelSession` and update `handleSend`:

```ts
const createAgentSession = async (): Promise<string | null> => {
  try {
    return await prepareAgentModelSession();
  } catch (error) {
    throw new Error(`Agent 模型配置不可用：${formatUnknownError(error)}`);
  }
};
```

In `handleSend`, prepare a fresh session for the streaming attempt and another fresh session for fallback:

```ts
let receivedStreamEvent = false;
try {
  await submitUserMessageStream(
    { ...payload, modelSessionId: await createAgentSession() },
    (event) => {
      receivedStreamEvent = true;
      applyBackendEvent(event);
    },
  );
} catch (streamError) {
  if (receivedStreamEvent) {
    throw streamError;
  }

  const events = await submitUserMessage({
    ...payload,
    modelSessionId: await createAgentSession(),
  });
  for (const event of events) {
    applyBackendEvent(event);
  }
}
```

In `runGraphWithMode`, add:

```ts
const modelSessionId = await createAgentSession();
```

and pass `modelSessionId` to `runNodeGraphStream`.

- [ ] **Step 4: Run frontend tests and commit**

Run:

```powershell
npm run frontend:test -- useTaskEvents.test.ts App.test.tsx
npm run frontend:lint
```

Expected: tests and typecheck pass. Commit:

```powershell
git add src/app/App.tsx src/app/App.test.tsx src/features/task/useTaskEvents.ts src/features/task/useTaskEvents.test.ts
git commit -m "feat: attach model sessions to agent requests"
```

## Task 12: Provider Create/Edit Form And Helper Actions

**Files:**
- Modify: `src/features/preferences/PreferencesDialog.tsx`
- Modify: `src/features/preferences/PreferencesDialog.test.tsx`
- Modify: `src/features/preferences/preferencesApi.ts`
- Modify: `src/app/App.tsx`

- [ ] **Step 1: Add UI test for key masking and form fields**

Add to `PreferencesDialog.test.tsx`:

```ts
it("renders API provider controls without exposing saved keys", () => {
  const markup = renderToStaticMarkup(
    <PreferencesDialog
      error={null}
      loading={false}
      onAddModel={() => undefined}
      onAddSpeechToTextModel={() => undefined}
      onClose={() => undefined}
      onDeleteApiProvider={() => undefined}
      onImportModel={() => undefined}
      onSaveApiProvider={() => undefined}
      onScanModelDirectory={() => undefined}
      onSetActiveApiProvider={() => undefined}
      onSetAgentModelMode={() => undefined}
      onSetDefaultModel={() => undefined}
      onSetModelAssignment={() => undefined}
      onSetModelStorageDirectory={() => undefined}
      onSetToolEnabled={() => undefined}
      open
      view={view}
    />,
  );

  expect(markup).toContain("添加 API 供应商");
  expect(markup).toContain("测试连接");
  expect(markup).toContain("拉取模型列表");
  expect(markup).toContain("密钥已配置");
  expect(markup).not.toContain("sk-test");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
npm run frontend:test -- PreferencesDialog.test.tsx
```

Expected: fails until controls are rendered.

- [ ] **Step 3: Add minimal provider form state**

In `PreferencesDialog.tsx`, add local state:

```tsx
const [apiFormOpen, setApiFormOpen] = useState(false);
const [apiForm, setApiForm] = useState<SaveApiProviderPayload>({
  providerType: "openai",
  displayName: "OpenAI",
  baseUrl: "https://api.openai.com/v1",
  model: "",
  enabled: true,
  apiKey: "",
});
```

Render form fields with labels for provider type, display name, base URL, model name, and API key. On submit, call `onSaveApiProvider(apiForm)` and clear only `apiKey` from state after save returns from App.

Add visible buttons for "添加 API 供应商", "测试连接", and "拉取模型列表". In this task, the buttons can call props. The helper implementations are wired in the next step.

- [ ] **Step 4: Wire helper API functions**

In `preferencesApi.ts`, add:

```ts
export async function testApiProviderConnection(
  payload: SaveApiProviderPayload,
): Promise<ApiProviderConnectionResult> {
  return invoke<ApiProviderConnectionResult>("test_api_provider_connection", {
    payload,
  });
}

export async function fetchApiProviderModels(
  payload: SaveApiProviderPayload,
): Promise<ApiProviderConnectionResult> {
  return invoke<ApiProviderConnectionResult>("fetch_api_provider_models", {
    payload,
  });
}
```

In `App.tsx`, add `handleSaveApiProvider`, `handleTestApiProviderConnection`, and `handleFetchApiProviderModels`. Store helper failures in `preferencesError`, but do not block `handleSaveApiProvider`.

- [ ] **Step 5: Run frontend tests and commit**

Run:

```powershell
npm run frontend:test -- PreferencesDialog.test.tsx
npm run frontend:lint
```

Expected: tests and typecheck pass. Commit:

```powershell
git add src/features/preferences/PreferencesDialog.tsx src/features/preferences/PreferencesDialog.test.tsx src/features/preferences/preferencesApi.ts src/app/App.tsx
git commit -m "feat: add api provider preferences form"
```

## Task 13: Verification And Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-05-24-api-agent-model-providers-design.md` if implementation discovers a documented mismatch.

- [ ] **Step 1: Update README**

Add a section after "配置本地模型":

```md
### API Agent 模型

Alita 可以把 Agent 默认模型切换为 OpenAI-compatible API。进入 `首选项 -> Agent 模型配置`，选择 `API 模型`，添加 OpenAI、DeepSeek、Kimi、GLM、MiniMax 或自定义兼容接口。

API 模型配置包含 Base URL、模型名和 API Key。Base URL 和模型名保存在本机首选项中；API Key 保存在系统凭据库中，不写入 `.alita` 工程文件或 `preferences.json`。

第一版 API 支持范围是文本聊天和流式输出。工具调用、结构化输出、多模态和各供应商专有能力不在第一版范围内。
```

- [ ] **Step 2: Run complete verification**

Run:

```powershell
npm run frontend:test
npm run frontend:lint
cd python
python -m pytest
cd ..
cargo test --manifest-path src-tauri/Cargo.toml
```

Expected: all available tests pass. If `cargo test` fails because `link.exe` or MSVC Build Tools are unavailable, capture the exact linker error and run narrower Rust test targets that do not require unavailable local tooling only if possible.

- [ ] **Step 3: Manual smoke checks**

Run the app:

```powershell
npm run desktop:dev
```

Manual checks:

- Preferences opens and shows Agent model source.
- Local model mode still shows GGUF actions.
- API model mode lets a user create an API provider without showing the saved key.
- Chat request in API mode creates a sidecar model session before streaming.
- Graph run in API mode includes the same model session mechanism.

- [ ] **Step 4: Commit docs and final fixes**

Commit:

```powershell
git add README.md docs/superpowers/specs/2026-05-24-api-agent-model-providers-design.md
git commit -m "docs: document api agent model providers"
```

## Self-Review

Spec coverage:

- Global local/API Agent model source is implemented in Tasks 1, 3, 7, 9, 10, and 11.
- Secure credential storage is implemented in Task 2 and used by Tasks 7 and 8.
- Preset plus custom providers are implemented in Tasks 1, 7, 10, and 12.
- Manual model entry plus optional helper actions are implemented in Tasks 8 and 12.
- OpenAI-compatible client and streaming are implemented in Task 5.
- Chat and graph model nodes using the same selected source are implemented in Tasks 6 and 11.
- API key non-leakage is covered in Tasks 1, 2, 7, 10, 11, and 12.
- Documentation and full verification are covered in Task 13.

Placeholder scan:

- The plan does not use unresolved planning markers.
- Each task lists exact files, commands, expected outcomes, and commit commands.

Type consistency:

- Rust uses `agent_model_mode`, `active_api_provider_id`, and `api_provider_configs`.
- TypeScript uses camelCase equivalents `agentModelMode`, `activeApiProviderId`, and `apiProviderConfigs`.
- Python request payloads use snake_case `model_session_id`, while Rust/TypeScript sidecar session responses use camelCase `modelSessionId`.
