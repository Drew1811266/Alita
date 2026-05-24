# API Agent Model Providers Design

## Goal

Add first-class API model provider support so Alita's Agent can be driven by either a local GGUF model or an OpenAI-compatible remote API model. The first version must be suitable for long-term user-facing use: API keys are stored in the system credential store, the Preferences UI clearly separates local and API Agent configuration, and every Agent LLM call uses the same global Agent model selection.

The first implementation covers generic text chat completions and streaming for:

- OpenAI
- DeepSeek
- Kimi
- GLM
- MiniMax
- Custom OpenAI-compatible APIs

Provider-specific advanced features are intentionally out of scope for this version.

## Pre-implementation State

Before API provider support, Alita already had a local-first model path:

- Preferences schema version 2 stores local model entries in `models`.
- `modelAssignments.agentChatModelId` selects the Agent GGUF model.
- Tauri resolves the Agent model path and starts `llama.cpp`.
- The Python sidecar reads `ALITA_LLAMA_*` environment variables and uses `LlamaCppModelClient`.
- Chat replies and graph model nodes already meet at the Python `model_client` / `model_runtime` boundary.

This is a good place to add API providers because the Agent UI and graph execution do not need separate provider-specific logic.

## Product Decisions

The user-approved first-version decisions are:

- Use one global Agent default model source: local or API.
- The choice applies to ordinary chat, task clarification, graph planning, and graph model nodes.
- Support preset providers plus a custom OpenAI-compatible provider.
- Store API keys in the system credential store, not in `preferences.json`.
- Support manual model name entry as the core path.
- Add "test connection" and "fetch model list" as helper actions; fetch failures must not block manual saving.
- Implement generic OpenAI-compatible chat completions only.

## Approach

Implement a unified Agent model configuration layer.

Preferences owns non-sensitive configuration. Rust owns secure credential access. Python owns model request execution. The frontend only receives masked credential state such as `hasApiKey`.

This avoids three weaker alternatives:

- API-only sidecar environment variables: too hidden for a real user-facing product.
- Per-feature provider configuration: confusing because chat and graph nodes could drift apart.
- Full provider plugin system in version one: too large before the generic API path is proven.

## Preferences Data Model

Move Preferences from schema version 2 to schema version 3.

```ts
type AgentModelMode = "local" | "api";

type ApiProviderType =
  | "openai"
  | "deepseek"
  | "kimi"
  | "glm"
  | "minimax"
  | "custom";

type ApiProviderCapability =
  | "chat_completions"
  | "streaming"
  | "model_list";

type ApiProviderConfig = {
  providerId: string;
  providerType: ApiProviderType;
  displayName: string;
  baseUrl: string;
  model: string;
  credentialRef: string;
  enabled: boolean;
  capabilities: ApiProviderCapability[];
  createdAt: string;
  updatedAt: string;
};

type AppPreferences = {
  schemaVersion: 3;
  agentModelMode: AgentModelMode;
  activeApiProviderId: string | null;
  apiProviderConfigs: ApiProviderConfig[];

  // Existing fields remain.
  models: ModelEntry[];
  defaultModelId: string | null;
  modelAssignments: ModelAssignments;
  toolEnablement: Record<string, boolean>;
};
```

Migration rules:

- Version 1 and 2 preferences load without user action.
- Migrated preferences default to `agentModelMode: "local"`.
- `activeApiProviderId` defaults to `null`.
- `apiProviderConfigs` defaults to an empty list.
- Existing local model assignments keep their current behavior.

API keys must never appear in:

- `preferences.json`
- `.alita` project files
- graph nodes or run history
- frontend state snapshots beyond one-time form entry
- logs and error messages

## Provider Presets

Provider presets fill initial values and remain editable. The implementation should treat `baseUrl` as the OpenAI-compatible API root and append `/chat/completions` or `/models` to it.

Default first-version presets:

| Provider | Default base URL | Notes |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | Chat Completions-compatible root. |
| DeepSeek | `https://api.deepseek.com` | Official OpenAI-compatible root; user may edit to `/v1` if needed. |
| Kimi | `https://api.moonshot.ai/v1` | Kimi/Moonshot OpenAI-compatible root. |
| GLM | `https://open.bigmodel.cn/api/paas/v4` | BigModel OpenAI-compatible root. |
| MiniMax | `https://api.minimax.io/v1` | International OpenAI-compatible root; regional alternatives can use custom or edited URL. |
| Custom | empty | User supplies all fields. |

The UI must not lock users into these defaults. Provider endpoints change over time, and users may use proxies, enterprise gateways, or regional endpoints.

## Credential Storage

Add a Rust credential boundary:

```rust
trait ApiCredentialStore {
    fn set_api_key(&self, credential_ref: &str, api_key: &str) -> Result<(), String>;
    fn get_api_key(&self, credential_ref: &str) -> Result<Option<String>, String>;
    fn delete_api_key(&self, credential_ref: &str) -> Result<(), String>;
}
```

Production implementation uses the OS credential store. On Windows, this should use Windows Credential Manager through a thin abstraction or a vetted Rust keychain crate. Tests use an in-memory implementation.

Credential reference format:

```text
alita.api-provider.<providerId>
```

Behavior:

- Creating an API provider stores the key under its credential reference.
- Editing a provider can replace the key without changing the provider ID.
- Editing non-sensitive fields does not require re-entering the key, except that changing provider type or base URL requires a new key entry so a saved key is not silently reused against a different endpoint.
- Deleting a provider also deletes its credential.
- If credential deletion fails, the UI reports the cleanup failure and keeps enough context for retry.
- The frontend receives `hasApiKey`, never the saved key value.

## Preferences UI

Add a dedicated Agent model configuration area inside Preferences.

Top-level controls:

- Agent model source segmented control: `Local model` / `API model`.
- Current Agent model summary.
- Speech-to-text model remains visible but separate from Agent model source.

Local model mode:

- Preserve current GGUF flows: import to library, reference external GGUF, scan model directory.
- Preserve local Agent assignment action.
- If switching from API to local, Tauri should ensure the local `llama.cpp` runtime is available for the selected GGUF model.

API model mode:

- Show API provider configurations as a dense list.
- Each row shows provider, display name, base URL, model, key state, enabled state, and current selection.
- Actions: add provider, edit settings, set as current Agent API, test connection, fetch model list, delete.

Add/edit provider form:

- Provider template selector: OpenAI, DeepSeek, Kimi, GLM, MiniMax, Custom.
- Display name input.
- Base URL input.
- Model name input.
- API key input for create or replace only.
- Saved-key state: "configured" or "not configured"; do not show the full key.
- Optional fetched model list, with manual model name entry always available.

## Runtime Data Flow

Rust remains the trusted bridge between local Preferences, secure credentials, and the Python sidecar.

Normal Agent request flow:

1. Frontend submits a chat or graph-run request to Tauri.
2. Rust loads Preferences and resolves the active Agent model source.
3. If mode is `local`, Rust sends local runtime config metadata and the Python sidecar uses `LlamaCppModelClient`.
4. If mode is `api`, Rust reads the active provider's API key from the credential store.
5. Rust passes the active model runtime config to the sidecar over the authenticated local sidecar request.
6. Python builds one `ModelClient` from that config for the request.
7. Chat streaming and graph model nodes use the same model client.

API keys should be passed to the sidecar only in memory for the active request. Do not persist them in Python global state beyond what is required to complete the request. The existing sidecar auth token remains required for local sidecar requests.

Development fallback:

- Existing `ALITA_LLAMA_*` overrides remain available for local development.
- New `ALITA_API_*` environment variables may be supported for developer troubleshooting, but Preferences plus credential storage is the normal product path.

## Python Model Client

Refactor `python/agent_service/model_client.py` into a provider-neutral model client boundary.

Keep:

- `ChatMessage`
- `ModelRuntimeDisabled`
- `ModelRuntimeRequestFailed`
- Existing llama.cpp request behavior

Add:

- `AgentModelClientConfig`
- `OpenAICompatibleModelClient`
- a factory that selects local or API client from request config or development environment

OpenAI-compatible request:

```json
{
  "model": "<configured model>",
  "messages": [
    { "role": "system", "content": "..." },
    { "role": "user", "content": "..." }
  ],
  "temperature": 0.2,
  "max_tokens": 1024,
  "stream": false
}
```

Streaming parser:

- Consume Server-Sent Events.
- Stop on `[DONE]`.
- Yield `choices[0].delta.content` when present.
- Ignore provider reasoning fields for version one unless they also include normal content.

Model list helper:

- Request `GET <baseUrl>/models`.
- Parse common OpenAI-compatible `data[].id` responses.
- Return an empty or failed helper result without invalidating manually entered model names.

## Runtime Management

Local mode:

- Start or reuse `llama.cpp` when the selected local model exists.
- If the user switches from API to local in the same session, Tauri should attempt to start the local runtime rather than requiring restart.

API mode:

- Do not require `llama.cpp`.
- If a local runtime is already running, it may be stopped to release resources. If stopping creates risk for the current session, it can be left running until app exit, but no API-mode request should depend on it.

Invalid states:

- API mode with no active provider: Agent replies with a clear Preferences action message.
- Active provider without API key: Agent replies with a clear API key missing message.
- Active provider disabled: Agent treats it as unavailable and reports the selected provider is disabled.
- Missing local GGUF in local mode: existing local-model error handling remains, updated to mention Agent model source.

## Error Handling

User-facing API errors should be concise and safe:

- Include provider display name.
- Include HTTP status code when available.
- Include provider error code/message when safe.
- Never include API key, Authorization header, or raw request headers.
- Avoid dumping full response bodies when they may include sensitive metadata.

Expected cases:

- 401 or 403: key invalid or unauthorized.
- 404: base URL or model name may be wrong.
- 429: rate limit or quota.
- 5xx: provider temporarily unavailable.
- Network timeout: connection failed or provider unreachable.
- Empty content: provider returned no assistant content.

## Implementation Scope

In scope:

- Preferences schema version 3 and migration.
- Rust API provider config operations.
- Rust credential store abstraction and Windows-backed production implementation.
- Preferences UI for local/API Agent source selection.
- API provider add/edit/delete/set-current flows.
- Test connection and fetch model list helper actions.
- Request-time Agent model config resolution.
- Python OpenAI-compatible model client and streaming parser.
- Chat and graph model-node integration through the unified model client.
- Documentation and tests.

Out of scope:

- Provider-specific advanced capabilities.
- Tool calling through provider APIs.
- Structured outputs.
- Vision/audio/multimodal API calls.
- Usage and billing dashboards.
- Multi-account sync.
- Cross-device credential migration.
- Automatic provider-specific model recommendations.

## Testing Strategy

Rust preferences tests:

- Version 2 preferences migrate to version 3 with `agentModelMode: "local"`.
- API provider configs serialize without API key fields.
- Add, edit, delete, and set active API provider.
- Deleting the active provider clears `activeApiProviderId`.
- Local Agent assignment behavior remains unchanged.

Rust credential tests:

- In-memory store saves, replaces, reads, and deletes API keys.
- API provider deletion calls credential deletion.
- Preferences views report `hasApiKey` without exposing the key.

Rust request/runtime tests:

- Local mode resolves llama.cpp config.
- API mode resolves active provider config and credential.
- API mode without credential returns a safe error.
- API request headers or payloads sent to sidecar do not serialize keys into Preferences or project state.

Python tests:

- OpenAI-compatible client posts the expected non-streaming request.
- OpenAI-compatible client parses streaming SSE chunks.
- Client handles `[DONE]`.
- Client maps 401, 429, 5xx, malformed JSON, and empty responses to `ModelRuntimeRequestFailed`.
- Existing llama.cpp client tests keep passing.
- Graph model runtime can use an injected API model client.

Frontend tests:

- Preferences can switch Agent model source between local and API.
- API provider form creates and edits non-sensitive fields.
- Saved API key is not displayed after save.
- Active API provider state is reflected in the list.
- Fetch model list failure still permits manual model entry.

Manual checks:

- Configure one local GGUF model and confirm local chat still works.
- Configure one API provider and confirm chat streaming works.
- Run a document graph and confirm model nodes use the same selected Agent source.
- Delete an API provider and confirm the UI no longer reports a saved key.

## Acceptance Criteria

- A user can choose local or API as the global Agent model source in Preferences.
- A user can configure OpenAI, DeepSeek, Kimi, GLM, MiniMax, or a custom OpenAI-compatible API.
- A user can manually enter a model name and optionally fetch a model list.
- API keys are stored only in the system credential store.
- Chat and graph model nodes use the same selected Agent source.
- API-mode errors are actionable and do not leak secrets.
- Existing local GGUF and ASR model configuration continues to work.

## Source Notes

Provider defaults were checked against public provider documentation on 2026-05-24:

- OpenAI Chat Completions API reference: https://platform.openai.com/docs/api-reference/chat/create
- DeepSeek API docs: https://api-docs.deepseek.com/
- Kimi API overview: https://platform.kimi.ai/docs/api/overview
- GLM OpenAI-compatible guide: https://docs.bigmodel.cn/cn/guide/develop/openai/introduction
- MiniMax OpenAI-compatible configuration reference: https://platform.minimax.io/docs/token-plan/other-tools
