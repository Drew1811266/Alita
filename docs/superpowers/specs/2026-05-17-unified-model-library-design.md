# Unified Model Library Design

## Goal

Build a unified local model library in Preferences so Alita can manage every local model through one durable configuration surface. The existing Agent AI model and the new speech-to-text model both become entries in this library, and each feature module selects the model it uses from role-specific assignments.

The first implementation covers two model roles:

- Agent chat and graph reasoning: local GGUF model through `llama.cpp`.
- Speech to text: local Qwen3-ASR-1.7B model directory through the Python ASR sidecar.

The design must leave a stable path for future local model roles such as embeddings, OCR, reranking, TTS, or vision models without adding one-off environment variables or one-off preference fields.

## Current State

Preferences already stores local models in `models`, but the shape is implicitly GGUF-only:

- `runtime` is effectively `llama_cpp`.
- model paths are file paths.
- `defaultModelId` selects the Agent model.
- import, external reference, and scan flows only accept `.gguf` files.

The ASR feature currently reads `ALITA_ASR_MODEL_PATH` in the Python sidecar. This works for development but bypasses Preferences, cannot be selected in the UI, and does not scale to additional local model-backed modules.

## Design Summary

Keep a single Preferences model library, but make each entry explicit about what it is and what it can serve.

Each model entry gets:

- `modelKind`: broad functional type, initially `agent_llm` or `speech_to_text`.
- `runtime`: concrete runtime, initially `llama_cpp` or `qwen_asr`.
- `pathKind`: `file` for GGUF models, `directory` for Qwen ASR models.
- `path`: local file or directory path.
- `fileExists`: retained as the existing compatibility field name, but interpreted as "path exists and matches `pathKind`".

Preferences also gets role assignments:

- `modelAssignments.agentChatModelId`
- `modelAssignments.speechToTextModelId`

The existing `defaultModelId` remains during migration as an alias for the Agent assignment. New code should read `modelAssignments.agentChatModelId`; compatibility code should populate it from `defaultModelId` when loading older preferences.

## Data Model

The Preferences schema moves from version 1 to version 2.

Version 2 `ModelEntry`:

```ts
type ModelKind = "agent_llm" | "speech_to_text";
type ModelRuntime = "llama_cpp" | "qwen_asr";
type ModelPathKind = "file" | "directory";
type ModelSource = "manual" | "scan" | "imported";

type ModelEntry = {
  modelId: string;
  name: string;
  path: string;
  pathKind: ModelPathKind;
  modelKind: ModelKind;
  runtime: ModelRuntime;
  source: ModelSource;
  fileExists: boolean;
  createdAt: string;
  updatedAt: string;
};
```

Version 2 `AppPreferences` adds:

```ts
type ModelAssignments = {
  agentChatModelId: string | null;
  speechToTextModelId: string | null;
};
```

Compatibility requirements:

- Version 1 preferences must load without user action.
- Existing `models` entries become `modelKind: "agent_llm"`, `runtime: "llama_cpp"`, and `pathKind: "file"`.
- Existing `defaultModelId` becomes `modelAssignments.agentChatModelId`.
- `defaultModelId` may remain serialized for one release as a compatibility mirror, but UI and runtime code should use `modelAssignments`.

## Preferences UI

The Preferences dialog keeps the current utilitarian layout. The "模型" section becomes "模型库".

Controls:

- Add Agent model: file picker filtered to `.gguf`.
- Import Agent GGUF into model library: existing import behavior.
- Scan Agent model directory: existing GGUF scan behavior.
- Add speech-to-text model: directory picker for a Qwen3-ASR-1.7B model directory.

The model list shows every model together, grouped or labeled by role:

- Name.
- Role label: Agent 模型 or 语音转文字.
- Runtime: `llama.cpp` or `Qwen ASR`.
- Source.
- Path or missing-path warning.
- Assignment action:
  - "设为 Agent 默认模型" for `agent_llm`.
  - "设为语音转文字模型" for `speech_to_text`.

The top of the section shows current assignments:

- Agent 模型: selected model name or "未配置".
- 语音转文字: selected model name or "未配置".

This keeps the model library as the source of truth while making each module's selected model easy to inspect.

## Runtime Behavior

Agent model startup:

- Development and packaged runtime should resolve the Agent model from `modelAssignments.agentChatModelId`.
- During transition, if `modelAssignments.agentChatModelId` is missing, use `defaultModelId`.
- Existing `ALITA_LLAMA_MODEL_PATH` remains an override for development and troubleshooting.

ASR model startup:

- Tauri should resolve the speech-to-text assignment from Preferences.
- The ASR status/transcription bridge should pass the assigned model path to the Python sidecar or export it into the sidecar environment as `ALITA_ASR_MODEL_PATH`.
- Existing `ALITA_ASR_MODEL_PATH` remains an override for development and troubleshooting, but Preferences is the normal user-facing configuration path.
- If no speech-to-text assignment exists, the microphone remains visible but disabled with a localized "未配置语音模型" message.

Future modules should add new assignment fields under `modelAssignments` rather than adding new top-level path settings.

## Validation And Errors

Path validation depends on `pathKind`:

- `file`: path must be an existing file.
- `directory`: path must be an existing directory.

Runtime validation depends on `runtime`:

- `llama_cpp`: `.gguf` file expected.
- `qwen_asr`: directory expected; deeper model-file validation may happen lazily in the ASR provider.

Selection validation:

- Agent assignment can only target `modelKind: "agent_llm"`.
- Speech-to-text assignment can only target `modelKind: "speech_to_text"`.
- Missing selected model paths are kept in Preferences but reported in UI and runtime status.

## Implementation Scope

In scope:

- Preferences schema migration and tests.
- Tauri commands for adding a speech-to-text model directory and assigning model roles.
- Frontend Preferences UI for model library entries and assignments.
- Development startup script update so Agent model resolution uses the new assignment field.
- ASR bridge/runtime update so speech-to-text model can be resolved from Preferences.
- Documentation updates for the unified model library.

Out of scope:

- Downloading models.
- Validating remote model manifests.
- Supporting multiple simultaneous ASR models.
- Automatic discovery of Qwen ASR directories beyond explicit user selection.
- Removing environment variable overrides.

## Testing Strategy

Rust tests:

- Migrate v1 preferences to v2 with existing GGUF model and default assignment preserved.
- Add Qwen ASR directory model.
- Reject invalid role assignment targets.
- Resolve Agent model assignment and speech-to-text assignment.

Frontend tests:

- Preferences UI renders Agent and speech-to-text assignments.
- Qwen ASR model row exposes "设为语音转文字模型".
- Missing model path is shown clearly.

Script tests:

- Development model environment reads `modelAssignments.agentChatModelId` before falling back to `defaultModelId`.

Integration checks:

- ASR status reports unavailable when no speech-to-text model is assigned.
- ASR status reports configured when an assigned Qwen ASR directory exists.

## First Implementation Decision

The first implementation should preserve the existing GGUF import/scan flows unchanged and add a separate Qwen ASR directory flow. A later version can generalize import/scan into a model-type picker if more model kinds are added.
