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
}

pub fn sidecar_token_header() -> &'static str {
    "X-Alita-Sidecar-Token"
}
