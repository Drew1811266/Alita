use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AgentAttachment {
    pub attachment_id: String,
    pub name: String,
    pub path: String,
    pub size_bytes: u64,
    pub mime_type: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AgentMessageRequest {
    pub task_id: String,
    pub content: String,
    pub attachments: Vec<AgentAttachment>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AgentEvent {
    pub r#type: String,
    pub payload: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct AsrStatusResponse {
    pub available: bool,
    pub configured: bool,
    pub model_path: Option<String>,
    pub message: String,
    pub error_code: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct AsrTranscriptionRequest {
    pub audio_path: String,
    pub language: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub model_path: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AsrTranscriptionResponse {
    pub text: String,
}

#[derive(Debug, Clone)]
pub struct AgentClient {
    base_url: String,
    http: reqwest::Client,
    auth_token: Option<String>,
}

impl AgentClient {
    pub fn new(base_url: impl Into<String>) -> Self {
        Self {
            base_url: base_url.into(),
            http: reqwest::Client::new(),
            auth_token: None,
        }
    }

    pub fn with_auth_token(mut self, token: impl Into<String>) -> Self {
        self.auth_token = Some(token.into());
        self
    }

    pub fn auth_token(&self) -> Option<&str> {
        self.auth_token.as_deref()
    }

    pub async fn send_message(
        &self,
        request: &AgentMessageRequest,
    ) -> Result<Vec<AgentEvent>, String> {
        let url = format!("{}/agent/message", self.base_url.trim_end_matches('/'));
        let mut request_builder = self.http.post(url).json(request);
        if let Some(token) = &self.auth_token {
            request_builder = request_builder.header(sidecar_token_header(), token);
        }

        let response = request_builder
            .send()
            .await
            .map_err(|error| format!("agent sidecar request failed: {error}"))?;

        if !response.status().is_success() {
            return Err(format!("agent sidecar returned {}", response.status()));
        }

        response
            .json::<Vec<AgentEvent>>()
            .await
            .map_err(|error| format!("invalid agent response: {error}"))
    }

    pub async fn get_asr_status(&self) -> Result<AsrStatusResponse, String> {
        self.get_asr_status_for_model(None).await
    }

    pub async fn get_asr_status_for_model(
        &self,
        model_path: Option<&str>,
    ) -> Result<AsrStatusResponse, String> {
        let url = format!("{}/asr/status", self.base_url.trim_end_matches('/'));
        let mut request_builder = self.http.get(url);
        if let Some(model_path) = model_path {
            request_builder = request_builder.query(&[("modelPath", model_path)]);
        }
        if let Some(token) = &self.auth_token {
            request_builder = request_builder.header(sidecar_token_header(), token);
        }

        let response = request_builder
            .send()
            .await
            .map_err(|error| format!("ASR status request failed: {error}"))?;

        if !response.status().is_success() {
            return Err(sidecar_error_message(response, "ASR status request").await);
        }

        response
            .json::<AsrStatusResponse>()
            .await
            .map_err(|error| format!("invalid ASR status response: {error}"))
    }

    pub async fn transcribe_asr_audio(
        &self,
        request: &AsrTranscriptionRequest,
    ) -> Result<AsrTranscriptionResponse, String> {
        let url = format!("{}/asr/transcribe", self.base_url.trim_end_matches('/'));
        let mut request_builder = self.http.post(url).json(request);
        if let Some(token) = &self.auth_token {
            request_builder = request_builder.header(sidecar_token_header(), token);
        }

        let response = request_builder
            .send()
            .await
            .map_err(|error| format!("ASR transcription request failed: {error}"))?;

        if !response.status().is_success() {
            return Err(sidecar_error_message(response, "ASR transcription request").await);
        }

        response
            .json::<AsrTranscriptionResponse>()
            .await
            .map_err(|error| format!("invalid ASR transcription response: {error}"))
    }
}

pub fn sidecar_token_header() -> &'static str {
    "X-Alita-Sidecar-Token"
}

async fn sidecar_error_message(response: reqwest::Response, label: &str) -> String {
    let status = response.status();
    match response.text().await {
        Ok(body) if !body.trim().is_empty() => format!("{label} returned {status}: {body}"),
        _ => format!("{label} returned {status}"),
    }
}
