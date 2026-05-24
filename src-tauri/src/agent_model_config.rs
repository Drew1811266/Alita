use serde::{Deserialize, Serialize};

use crate::{
    api_credentials::ApiCredentialStore,
    preferences::{agent_model_path, AppPreferences},
};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", tag = "mode")]
pub enum AgentModelConfig {
    Local { base_url: String, model: String },
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
