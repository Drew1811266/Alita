use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeBackend {
    LlamaCpp,
    Ollama,
    LocalAi,
    OnnxRuntimeGenAi,
    ExternalApi,
    Mock,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ModelCapabilities {
    pub supports_chat: bool,
    pub supports_tools: bool,
    pub supports_embeddings: bool,
    pub supports_images: bool,
    pub supports_audio: bool,
    pub context_window: u32,
    pub max_output_tokens: u32,
    pub runtime_backend: RuntimeBackend,
    pub local_only: bool,
}

impl ModelCapabilities {
    pub fn local_llama_cpp() -> Self {
        Self {
            supports_chat: true,
            supports_tools: true,
            supports_embeddings: true,
            supports_images: false,
            supports_audio: false,
            context_window: 16384,
            max_output_tokens: 1024,
            runtime_backend: RuntimeBackend::LlamaCpp,
            local_only: true,
        }
    }
}
