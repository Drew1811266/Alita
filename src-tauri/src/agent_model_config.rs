use std::fmt;

use serde::{Deserialize, Serialize};

use crate::{
    api_credentials::{ApiCredentialStore, ApiCredentialTarget},
    preferences::{
        agent_model_path, normalize_api_provider_api_key, normalize_api_provider_base_url,
        normalize_api_provider_display_name, normalize_api_provider_model,
        normalize_api_provider_type, AppPreferences,
    },
};

#[derive(Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", tag = "mode")]
pub enum AgentModelConfig {
    #[serde(rename_all = "camelCase")]
    Local { base_url: String, model: String },
    #[serde(rename_all = "camelCase")]
    Api {
        provider_id: String,
        provider_type: String,
        display_name: String,
        base_url: String,
        model: String,
        api_key: String,
    },
}

impl fmt::Debug for AgentModelConfig {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            AgentModelConfig::Local { base_url, model } => formatter
                .debug_struct("Local")
                .field("base_url", base_url)
                .field("model", model)
                .finish(),
            AgentModelConfig::Api {
                provider_id,
                provider_type,
                display_name,
                base_url,
                model,
                api_key: _,
            } => formatter
                .debug_struct("Api")
                .field("provider_id", provider_id)
                .field("provider_type", provider_type)
                .field("display_name", display_name)
                .field("base_url", base_url)
                .field("model", model)
                .field("api_key", &"<redacted>")
                .finish(),
        }
    }
}

#[derive(Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct RegisterModelSessionRequest {
    pub model_config: AgentModelConfig,
}

impl fmt::Debug for RegisterModelSessionRequest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RegisterModelSessionRequest")
            .field("model_config", &self.model_config)
            .finish()
    }
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
    let provider_type = normalize_api_provider_type(&provider.provider_type)?;
    let display_name = normalize_api_provider_display_name(&provider.display_name)?;
    let base_url = normalize_api_provider_base_url(&provider.base_url)?;
    let model = normalize_api_provider_model(&provider.model)?;
    if !provider.enabled {
        return Err(format!("API provider '{display_name}' is disabled"));
    }
    let credential_target = ApiCredentialTarget::new(&provider_type, &base_url)?;
    let api_key = credential_store
        .get_api_key(&provider.credential_ref, &credential_target)?
        .ok_or_else(|| format!("API key is not configured for {display_name}"))
        .and_then(|api_key| normalize_api_provider_api_key(&api_key))?;
    Ok(AgentModelConfig::Api {
        provider_id: provider.provider_id.clone(),
        provider_type,
        display_name,
        base_url,
        model,
        api_key,
    })
}
