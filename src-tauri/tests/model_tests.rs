#[path = "../src/model.rs"]
mod model;

use model::{ModelCapabilities, RuntimeBackend};

#[test]
fn default_local_capabilities_are_text_and_embedding_ready() {
    let capabilities = ModelCapabilities::local_llama_cpp();

    assert_eq!(capabilities.runtime_backend, RuntimeBackend::LlamaCpp);
    assert!(capabilities.supports_chat);
    assert!(capabilities.supports_tools);
    assert!(capabilities.supports_embeddings);
    assert!(!capabilities.supports_images);
    assert!(!capabilities.supports_audio);
    assert_eq!(capabilities.context_window, 16384);
    assert!(capabilities.local_only);
}

#[test]
fn runtime_backend_serializes_as_snake_case() {
    let value = serde_json::to_value(RuntimeBackend::OnnxRuntimeGenAi)
        .expect("runtime backend should serialize");

    assert_eq!(value, "onnx_runtime_gen_ai");
}
