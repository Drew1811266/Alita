# Local Qwen ASR Voice Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a development-only local voice input module that records up to 60 seconds of speech, transcribes it through Qwen3-ASR-1.7B on CPU, and inserts the transcript into the chat draft for user review.

**Architecture:** The feature is an input method layered onto the existing chat composer. React records and visualizes audio, Tauri writes a temporary WAV and calls the Python sidecar, and the sidecar lazily loads a CPU-only ASR provider from `ALITA_ASR_MODEL_PATH`.

**Tech Stack:** React, TypeScript, Web Audio API, Tauri commands, Rust `reqwest`, Python FastAPI, Pydantic, Qwen ASR runtime package.

---

## File Structure

- Create `python/agent_service/asr.py`: ASR status, error mapping, provider protocol, lazy CPU provider service, and request/response models.
- Modify `python/agent_service/app.py`: add authenticated `/asr/status` and `/asr/transcribe` endpoints.
- Create `python/tests/test_asr.py`: unit tests for status, fake provider transcription, busy rejection, and error mapping.
- Modify `python/pyproject.toml`: add an optional ASR dependency group for the Qwen runtime package.
- Create `src-tauri/src/asr.rs`: temporary WAV payload validation, base64 decode, temp file writing, cleanup helpers, and the frontend command payload type.
- Modify `src-tauri/src/agent_client.rs`: add ASR status/transcription client methods.
- Modify `src-tauri/src/commands.rs`: add `get_asr_status` and `transcribe_voice_audio` commands.
- Modify `src-tauri/src/lib.rs`: register the new module and commands.
- Create `src-tauri/tests/asr_tests.rs`: temp file, validation, and cleanup tests.
- Modify `src-tauri/tests/agent_client_tests.rs`: ASR request serialization and auth header constant coverage.
- Create `src/features/voice/asrApi.ts`: frontend Tauri API wrapper for status and transcription.
- Create `src/features/voice/asrApi.test.ts`: command payload and fallback error tests.
- Create `src/features/voice/draftInsertion.ts`: pure transcript insertion logic.
- Create `src/features/voice/draftInsertion.test.ts`: empty draft, append fallback, cursor insertion, selection replacement, and clamped offsets.
- Create `src/features/voice/audioCapture.ts`: WAV encoding, timer formatting, base64 conversion, and level bucket generation.
- Create `src/features/voice/audioCapture.test.ts`: WAV header and level bucket tests.
- Create `src/features/voice/AudioTrack.tsx`: compact waveform and timer component.
- Create `src/features/voice/AudioTrack.test.tsx`: static markup tests for bars and timer.
- Modify `src/features/chat/ChatPanel.tsx`: add microphone button, textarea selection reporting, recording/transcribing states, and waveform placement.
- Modify `src/features/chat/ChatPanel.test.tsx`: composer action count, disabled mic, recording track, and selection event tests.
- Modify `src/app/App.tsx`: orchestrate ASR status, recording, transcription, insertion, and errors.
- Modify `src/app/app.css`: style microphone button and compact audio track, including mobile three-button layout.

---

### Task 1: Python ASR Service

**Files:**
- Create: `python/agent_service/asr.py`
- Modify: `python/agent_service/app.py`
- Modify: `python/pyproject.toml`
- Test: `python/tests/test_asr.py`

- [ ] **Step 1: Write failing Python tests**

Create `python/tests/test_asr.py`:

```python
import os
import threading
import time
from pathlib import Path

import pytest

from agent_service.asr import (
    ALITA_ASR_MODEL_PATH_ENV,
    ASRError,
    ASRService,
    ASRStatus,
    TranscriptionRequest,
    get_asr_status,
)
from agent_service.app import app
from fastapi.testclient import TestClient


class FakeProvider:
    def __init__(self, text: str = "transcribed text", delay: float = 0.0):
        self.text = text
        self.delay = delay
        self.calls: list[tuple[Path, str]] = []

    def transcribe(self, audio_path: Path, language: str) -> str:
        self.calls.append((audio_path, language))
        if self.delay:
            time.sleep(self.delay)
        return self.text


def test_status_reports_missing_model_path(monkeypatch):
    monkeypatch.delenv(ALITA_ASR_MODEL_PATH_ENV, raising=False)

    status = get_asr_status()

    assert status == ASRStatus(
        available=False,
        configured=False,
        modelPath=None,
        message="voice model is not configured",
        errorCode="asr_not_configured",
    )


def test_status_reports_missing_model_directory(monkeypatch, tmp_path):
    missing_path = tmp_path / "missing-model"
    monkeypatch.setenv(ALITA_ASR_MODEL_PATH_ENV, str(missing_path))

    status = get_asr_status()

    assert status.available is False
    assert status.configured is True
    assert status.modelPath == str(missing_path)
    assert status.errorCode == "asr_model_missing"


def test_status_reports_missing_dependency(monkeypatch, tmp_path):
    model_dir = tmp_path / "Qwen3-ASR-1.7B"
    model_dir.mkdir()
    monkeypatch.setenv(ALITA_ASR_MODEL_PATH_ENV, str(model_dir))

    status = get_asr_status(dependency_available=lambda: False)

    assert status.available is False
    assert status.errorCode == "asr_dependency_missing"


def test_status_reports_available_model(monkeypatch, tmp_path):
    model_dir = tmp_path / "Qwen3-ASR-1.7B"
    model_dir.mkdir()
    monkeypatch.setenv(ALITA_ASR_MODEL_PATH_ENV, str(model_dir))

    status = get_asr_status(dependency_available=lambda: True)

    assert status.available is True
    assert status.configured is True
    assert status.modelPath == str(model_dir)
    assert status.errorCode is None


def test_transcribe_uses_provider_and_language(tmp_path):
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"RIFF....WAVEfmt ")
    provider = FakeProvider(text="hello from audio")
    service = ASRService(provider_factory=lambda _model_path: provider)

    result = service.transcribe(
        TranscriptionRequest(audioPath=str(audio_path), language="zh"),
        model_path=tmp_path / "Qwen3-ASR-1.7B",
    )

    assert result.text == "hello from audio"
    assert provider.calls == [(audio_path, "zh")]


def test_transcribe_rejects_missing_audio_file(tmp_path):
    service = ASRService(provider_factory=lambda _model_path: FakeProvider())

    with pytest.raises(ASRError) as error:
        service.transcribe(
            TranscriptionRequest(audioPath=str(tmp_path / "missing.wav")),
            model_path=tmp_path,
        )

    assert error.value.code == "asr_audio_invalid"


def test_transcribe_rejects_concurrent_requests(tmp_path):
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"RIFF....WAVEfmt ")
    service = ASRService(
        provider_factory=lambda _model_path: FakeProvider(delay=0.2),
    )
    first_error: list[Exception] = []

    def run_first_request():
        try:
            service.transcribe(
                TranscriptionRequest(audioPath=str(audio_path)),
                model_path=tmp_path,
            )
        except Exception as error:
            first_error.append(error)

    thread = threading.Thread(target=run_first_request)
    thread.start()
    time.sleep(0.05)

    with pytest.raises(ASRError) as error:
        service.transcribe(
            TranscriptionRequest(audioPath=str(audio_path)),
            model_path=tmp_path,
        )

    thread.join()
    assert first_error == []
    assert error.value.code == "asr_busy"


def test_asr_status_endpoint_without_model(monkeypatch):
    monkeypatch.delenv(ALITA_ASR_MODEL_PATH_ENV, raising=False)
    client = TestClient(app)

    response = client.get("/asr/status")

    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["errorCode"] == "asr_not_configured"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
python -m pytest python/tests/test_asr.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_service.asr'`.

- [ ] **Step 3: Implement `python/agent_service/asr.py`**

Create `python/agent_service/asr.py`:

```python
from __future__ import annotations

import importlib.util
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from pydantic import BaseModel, Field


ALITA_ASR_MODEL_PATH_ENV = "ALITA_ASR_MODEL_PATH"


class ASRError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ASRStatus(BaseModel):
    available: bool
    configured: bool
    modelPath: str | None = None
    message: str
    errorCode: str | None = None


class TranscriptionRequest(BaseModel):
    audioPath: str
    language: str = Field(default="zh")


class TranscriptionResponse(BaseModel):
    text: str


class ASRProvider(Protocol):
    def transcribe(self, audio_path: Path, language: str) -> str:
        ...


ProviderFactory = Callable[[Path], ASRProvider]


def qwen_asr_dependency_available() -> bool:
    return importlib.util.find_spec("qwen_asr") is not None


def configured_model_path() -> Path | None:
    value = os.getenv(ALITA_ASR_MODEL_PATH_ENV, "").strip()
    if not value:
        return None
    return Path(value)


def get_asr_status(
    dependency_available: Callable[[], bool] = qwen_asr_dependency_available,
) -> ASRStatus:
    model_path = configured_model_path()
    if model_path is None:
        return ASRStatus(
            available=False,
            configured=False,
            message="voice model is not configured",
            errorCode="asr_not_configured",
        )

    if not model_path.is_dir():
        return ASRStatus(
            available=False,
            configured=True,
            modelPath=str(model_path),
            message="voice model path does not exist",
            errorCode="asr_model_missing",
        )

    if not dependency_available():
        return ASRStatus(
            available=False,
            configured=True,
            modelPath=str(model_path),
            message="ASR runtime package is not installed",
            errorCode="asr_dependency_missing",
        )

    return ASRStatus(
        available=True,
        configured=True,
        modelPath=str(model_path),
        message="voice model is configured",
    )


class QwenASRProvider:
    def __init__(self, model_path: Path):
        self.model_path = model_path
        self._pipeline = self._load_pipeline()

    def _load_pipeline(self):
        try:
            qwen_asr = __import__("qwen_asr")
        except Exception as error:
            raise ASRError(
                "asr_dependency_missing",
                "ASR runtime package is not installed",
            ) from error

        try:
            pipeline_class = getattr(qwen_asr, "QwenASR")
            return pipeline_class(
                model_path=str(self.model_path),
                backend="transformers",
                device="cpu",
            )
        except ASRError:
            raise
        except Exception as error:
            raise ASRError(
                "asr_model_load_failed",
                f"failed to load ASR model: {error}",
            ) from error

    def transcribe(self, audio_path: Path, language: str) -> str:
        try:
            result = self._pipeline.transcribe(str(audio_path), language=language)
        except Exception as error:
            raise ASRError(
                "asr_transcription_failed",
                f"ASR transcription failed: {error}",
            ) from error

        if isinstance(result, str):
            return result.strip()
        if isinstance(result, dict) and isinstance(result.get("text"), str):
            return result["text"].strip()
        raise ASRError(
            "asr_transcription_failed",
            "ASR runtime returned an unexpected response",
        )


@dataclass
class ASRService:
    provider_factory: ProviderFactory = QwenASRProvider

    def __post_init__(self) -> None:
        self._provider: ASRProvider | None = None
        self._provider_path: Path | None = None
        self._lock = threading.Lock()

    def transcribe(
        self,
        request: TranscriptionRequest,
        model_path: Path | None = None,
    ) -> TranscriptionResponse:
        if not self._lock.acquire(blocking=False):
            raise ASRError("asr_busy", "transcription is already running")
        try:
            resolved_model_path = model_path or configured_model_path()
            if resolved_model_path is None:
                raise ASRError(
                    "asr_not_configured",
                    "voice model is not configured",
                )
            if not resolved_model_path.is_dir():
                raise ASRError(
                    "asr_model_missing",
                    "voice model path does not exist",
                )

            audio_path = Path(request.audioPath)
            if not audio_path.is_file():
                raise ASRError(
                    "asr_audio_invalid",
                    "temporary audio file is missing or unreadable",
                )

            provider = self._provider_for(resolved_model_path)
            text = provider.transcribe(audio_path, request.language)
            return TranscriptionResponse(text=text)
        finally:
            self._lock.release()

    def _provider_for(self, model_path: Path) -> ASRProvider:
        if self._provider is None or self._provider_path != model_path:
            self._provider = self.provider_factory(model_path)
            self._provider_path = model_path
        return self._provider


DEFAULT_ASR_SERVICE = ASRService()
```

- [ ] **Step 4: Add FastAPI endpoints**

Modify `python/agent_service/app.py`:

```python
from agent_service.asr import (
    ASRError,
    ASRStatus,
    DEFAULT_ASR_SERVICE,
    TranscriptionRequest,
    TranscriptionResponse,
    get_asr_status,
)
```

Add after `/health`:

```python
@app.get("/asr/status", response_model=ASRStatus)
def asr_status(_auth: None = Depends(require_sidecar_token)) -> ASRStatus:
    return get_asr_status()


@app.post("/asr/transcribe", response_model=TranscriptionResponse)
def asr_transcribe(
    request: TranscriptionRequest,
    _auth: None = Depends(require_sidecar_token),
) -> TranscriptionResponse:
    try:
        return DEFAULT_ASR_SERVICE.transcribe(request)
    except ASRError as error:
        raise HTTPException(
            status_code=409 if error.code == "asr_busy" else 400,
            detail={"errorCode": error.code, "error": error.message},
        ) from error
```

- [ ] **Step 5: Add optional ASR dependency group**

Modify `python/pyproject.toml`:

```toml
[project.optional-dependencies]
test = ["pytest", "httpx"]
package = ["pyinstaller"]
asr = ["qwen-asr"]
```

- [ ] **Step 6: Run Python tests**

Run:

```powershell
python -m pytest python/tests/test_asr.py -q
python -m pytest python/tests -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add python/agent_service/asr.py python/agent_service/app.py python/pyproject.toml python/tests/test_asr.py
git commit -m "feat: add local ASR sidecar service"
```

---

### Task 2: Tauri ASR Bridge

**Files:**
- Create: `src-tauri/src/asr.rs`
- Modify: `src-tauri/src/agent_client.rs`
- Modify: `src-tauri/src/commands.rs`
- Modify: `src-tauri/src/lib.rs`
- Test: `src-tauri/tests/asr_tests.rs`
- Test: `src-tauri/tests/agent_client_tests.rs`
- Modify: `src-tauri/Cargo.toml`

- [ ] **Step 1: Write failing Rust bridge tests**

Create `src-tauri/tests/asr_tests.rs`:

```rust
#[path = "../src/asr.rs"]
mod asr;

use std::fs;

use asr::{decode_wav_base64, remove_temp_audio_file, write_temp_audio_file, MAX_ASR_AUDIO_BYTES};

#[test]
fn decodes_base64_audio_payload() {
    let bytes = decode_wav_base64("UklGRg==").expect("payload should decode");

    assert_eq!(bytes, b"RIFF");
}

#[test]
fn rejects_payloads_over_max_size() {
    let oversized = vec![0_u8; MAX_ASR_AUDIO_BYTES + 1];
    let encoded = base64::Engine::encode(&base64::engine::general_purpose::STANDARD, oversized);

    let error = decode_wav_base64(&encoded).unwrap_err();

    assert!(error.contains("voice audio payload is too large"));
}

#[test]
fn writes_temp_audio_file_under_temp_directory() {
    let temp_dir = tempfile::tempdir().unwrap();

    let path = write_temp_audio_file(temp_dir.path(), b"RIFF....WAVE").unwrap();

    assert!(path.starts_with(temp_dir.path()));
    assert!(path.file_name().unwrap().to_string_lossy().starts_with("alita-asr-"));
    assert_eq!(fs::read(path).unwrap(), b"RIFF....WAVE");
}

#[test]
fn removes_temp_audio_file_without_failing_on_missing_file() {
    let temp_dir = tempfile::tempdir().unwrap();
    let path = write_temp_audio_file(temp_dir.path(), b"RIFF....WAVE").unwrap();

    remove_temp_audio_file(&path);
    remove_temp_audio_file(&path);

    assert!(!path.exists());
}
```

Modify `src-tauri/tests/agent_client_tests.rs`:

```rust
use agent_client::{
    AgentAttachment, AgentMessageRequest, AsrStatusResponse, AsrTranscriptionRequest,
};
```

Add:

```rust
#[test]
fn serializes_asr_transcription_request() {
    let request = AsrTranscriptionRequest {
        audio_path: "C:\\Temp\\alita-asr-input.wav".to_string(),
        language: "zh".to_string(),
    };

    let json = serde_json::to_value(request).expect("request should serialize");

    assert_eq!(json["audioPath"], "C:\\Temp\\alita-asr-input.wav");
    assert_eq!(json["language"], "zh");
}

#[test]
fn deserializes_asr_status_response() {
    let status: AsrStatusResponse = serde_json::from_value(serde_json::json!({
        "available": false,
        "configured": false,
        "modelPath": null,
        "message": "voice model is not configured",
        "errorCode": "asr_not_configured"
    }))
    .unwrap();

    assert!(!status.available);
    assert_eq!(status.error_code.as_deref(), Some("asr_not_configured"));
}
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml asr
```

Expected: FAIL because `src-tauri/src/asr.rs` and ASR client types do not exist.

- [ ] **Step 3: Add Rust dependency**

Modify `src-tauri/Cargo.toml`:

```toml
base64 = "0.22"
```

- [ ] **Step 4: Implement `src-tauri/src/asr.rs`**

Create `src-tauri/src/asr.rs`:

```rust
use std::{
    fs,
    path::{Path, PathBuf},
};

use base64::{engine::general_purpose, Engine as _};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

pub const MAX_ASR_AUDIO_BYTES: usize = 4 * 1024 * 1024;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct TranscribeVoiceAudioPayload {
    pub wav_base64: String,
}

pub fn decode_wav_base64(value: &str) -> Result<Vec<u8>, String> {
    let bytes = general_purpose::STANDARD
        .decode(value)
        .map_err(|error| format!("invalid voice audio payload: {error}"))?;
    if bytes.len() > MAX_ASR_AUDIO_BYTES {
        return Err(format!(
            "voice audio payload is too large: {} bytes exceeds {} bytes",
            bytes.len(),
            MAX_ASR_AUDIO_BYTES
        ));
    }
    Ok(bytes)
}

pub fn write_temp_audio_file(temp_dir: &Path, bytes: &[u8]) -> Result<PathBuf, String> {
    fs::create_dir_all(temp_dir).map_err(|error| {
        format!(
            "failed to create temp audio directory '{}': {error}",
            temp_dir.display()
        )
    })?;
    let path = temp_dir.join(format!("alita-asr-{}.wav", Uuid::new_v4()));
    fs::write(&path, bytes)
        .map_err(|error| format!("failed to write temp voice audio: {error}"))?;
    Ok(path)
}

pub fn remove_temp_audio_file(path: &Path) {
    let _ = fs::remove_file(path);
}
```

- [ ] **Step 5: Extend `agent_client.rs`**

Modify `src-tauri/src/agent_client.rs`:

```rust
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
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AsrTranscriptionResponse {
    pub text: String,
}
```

Add methods inside `impl AgentClient`:

```rust
    pub async fn get_asr_status(&self) -> Result<AsrStatusResponse, String> {
        let url = format!("{}/asr/status", self.base_url.trim_end_matches('/'));
        let mut request_builder = self.http.get(url);
        if let Some(token) = &self.auth_token {
            request_builder = request_builder.header(sidecar_token_header(), token);
        }

        let response = request_builder
            .send()
            .await
            .map_err(|error| format!("ASR sidecar status request failed: {error}"))?;

        if !response.status().is_success() {
            return Err(format!("ASR sidecar returned {}", response.status()));
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
            .map_err(|error| format!("ASR sidecar request failed: {error}"))?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            return Err(format!("ASR sidecar returned {status}: {body}"));
        }

        response
            .json::<AsrTranscriptionResponse>()
            .await
            .map_err(|error| format!("invalid ASR transcription response: {error}"))
    }
```

- [ ] **Step 6: Add commands and registration**

Modify `src-tauri/src/lib.rs`:

```rust
pub mod asr;
```

Register commands:

```rust
commands::get_asr_status,
commands::transcribe_voice_audio,
```

Modify `src-tauri/src/commands.rs` imports:

```rust
use crate::agent_client::{AsrTranscriptionRequest, AsrTranscriptionResponse};
use crate::agent_client::AsrStatusResponse;
use crate::asr::{decode_wav_base64, remove_temp_audio_file, write_temp_audio_file, TranscribeVoiceAudioPayload};
```

Add commands:

```rust
#[tauri::command]
pub async fn get_asr_status(app: AppHandle) -> Result<AsrStatusResponse, String> {
    AgentClient::new(crate::sidecar::agent_base_url())
        .with_auth_token(crate::sidecar::sidecar_auth_token(&app)?)
        .get_asr_status()
        .await
}

#[tauri::command]
pub async fn transcribe_voice_audio(
    app: AppHandle,
    payload: TranscribeVoiceAudioPayload,
) -> Result<AsrTranscriptionResponse, String> {
    let audio_bytes = decode_wav_base64(&payload.wav_base64)?;
    let temp_path = write_temp_audio_file(&std::env::temp_dir(), &audio_bytes)?;
    let result = AgentClient::new(crate::sidecar::agent_base_url())
        .with_auth_token(crate::sidecar::sidecar_auth_token(&app)?)
        .transcribe_asr_audio(&AsrTranscriptionRequest {
            audio_path: temp_path.to_string_lossy().into_owned(),
            language: "zh".to_string(),
        })
        .await;
    remove_temp_audio_file(&temp_path);
    result
}
```

- [ ] **Step 7: Run Rust tests**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml asr
cargo test --manifest-path src-tauri/Cargo.toml agent_client
cargo test --manifest-path src-tauri/Cargo.toml
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add src-tauri/Cargo.toml src-tauri/src/asr.rs src-tauri/src/agent_client.rs src-tauri/src/commands.rs src-tauri/src/lib.rs src-tauri/tests/asr_tests.rs src-tauri/tests/agent_client_tests.rs
git commit -m "feat: bridge voice audio to ASR sidecar"
```

---

### Task 3: Frontend Voice API And Pure Helpers

**Files:**
- Create: `src/features/voice/asrApi.ts`
- Create: `src/features/voice/asrApi.test.ts`
- Create: `src/features/voice/draftInsertion.ts`
- Create: `src/features/voice/draftInsertion.test.ts`
- Create: `src/features/voice/audioCapture.ts`
- Create: `src/features/voice/audioCapture.test.ts`

- [ ] **Step 1: Write failing helper tests**

Create `src/features/voice/draftInsertion.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { insertTranscriptIntoDraft } from "./draftInsertion";

describe("insertTranscriptIntoDraft", () => {
  it("fills an empty draft", () => {
    expect(
      insertTranscriptIntoDraft({
        currentDraft: "",
        transcript: "请总结这份文档",
        selection: null,
      }),
    ).toBe("请总结这份文档");
  });

  it("appends when there is no selection", () => {
    expect(
      insertTranscriptIntoDraft({
        currentDraft: "先分析结构",
        transcript: "再提炼重点",
        selection: null,
      }),
    ).toBe("先分析结构\n再提炼重点");
  });

  it("inserts at the captured cursor", () => {
    expect(
      insertTranscriptIntoDraft({
        currentDraft: "请  处理",
        transcript: "详细",
        selection: { start: 2, end: 2 },
      }),
    ).toBe("请详细  处理");
  });

  it("replaces the captured selection", () => {
    expect(
      insertTranscriptIntoDraft({
        currentDraft: "请快速处理",
        transcript: "详细分析",
        selection: { start: 1, end: 5 },
      }),
    ).toBe("请详细分析");
  });

  it("clamps stale selection offsets to the current draft", () => {
    expect(
      insertTranscriptIntoDraft({
        currentDraft: "短文本",
        transcript: "追加内容",
        selection: { start: 99, end: 120 },
      }),
    ).toBe("短文本追加内容");
  });
});
```

Create `src/features/voice/audioCapture.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { buildLevelBuckets, encodeWav, secondsToTimerLabel } from "./audioCapture";

describe("encodeWav", () => {
  it("encodes mono PCM as a WAV file", () => {
    const wav = encodeWav(new Float32Array([0, 0.5, -0.5]), 16000);
    const text = new TextDecoder("ascii").decode(wav.slice(0, 12));

    expect(text).toBe("RIFF*\u0000\u0000\u0000WAVE");
    expect(wav.byteLength).toBe(50);
  });
});

describe("buildLevelBuckets", () => {
  it("creates stable normalized waveform levels", () => {
    const levels = buildLevelBuckets(new Uint8Array([128, 255, 0, 128]), 4);

    expect(levels).toEqual([0, 1, 1, 0]);
  });
});

describe("secondsToTimerLabel", () => {
  it("formats elapsed seconds as mm:ss", () => {
    expect(secondsToTimerLabel(0)).toBe("00:00");
    expect(secondsToTimerLabel(65)).toBe("01:05");
  });
});
```

Create `src/features/voice/asrApi.test.ts`:

```typescript
import { invoke } from "@tauri-apps/api/core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { getAsrStatus, transcribeVoiceAudio } from "./asrApi";

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(),
}));

const invokeMock = vi.mocked(invoke);

afterEach(() => {
  vi.restoreAllMocks();
});

describe("getAsrStatus", () => {
  it("returns unavailable status when the command fails", async () => {
    invokeMock.mockRejectedValue(new Error("sidecar offline"));

    await expect(getAsrStatus()).resolves.toMatchObject({
      available: false,
      errorCode: "asr_status_unavailable",
    });
  });
});

describe("transcribeVoiceAudio", () => {
  it("sends base64 WAV bytes to the Tauri command", async () => {
    invokeMock.mockResolvedValue({ text: "转写文本" });

    const result = await transcribeVoiceAudio(new Uint8Array([82, 73, 70, 70]));

    expect(result.text).toBe("转写文本");
    expect(invokeMock).toHaveBeenCalledWith("transcribe_voice_audio", {
      payload: { wavBase64: "UklGRg==" },
    });
  });
});
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
npm run frontend:test -- src/features/voice/draftInsertion.test.ts src/features/voice/audioCapture.test.ts src/features/voice/asrApi.test.ts
```

Expected: FAIL because the new modules do not exist.

- [ ] **Step 3: Implement `draftInsertion.ts`**

Create `src/features/voice/draftInsertion.ts`:

```typescript
export type DraftSelection = {
  start: number;
  end: number;
};

type InsertTranscriptInput = {
  currentDraft: string;
  transcript: string;
  selection: DraftSelection | null;
};

export function insertTranscriptIntoDraft({
  currentDraft,
  transcript,
  selection,
}: InsertTranscriptInput): string {
  const cleanedTranscript = transcript.trim();
  if (!cleanedTranscript) {
    return currentDraft;
  }
  if (!currentDraft) {
    return cleanedTranscript;
  }
  if (!selection) {
    return `${currentDraft}\n${cleanedTranscript}`;
  }

  const start = clampOffset(selection.start, currentDraft.length);
  const end = clampOffset(selection.end, currentDraft.length);
  const from = Math.min(start, end);
  const to = Math.max(start, end);

  return `${currentDraft.slice(0, from)}${cleanedTranscript}${currentDraft.slice(to)}`;
}

function clampOffset(offset: number, length: number): number {
  if (!Number.isFinite(offset)) {
    return length;
  }
  return Math.min(Math.max(Math.trunc(offset), 0), length);
}
```

- [ ] **Step 4: Implement `audioCapture.ts`**

Create `src/features/voice/audioCapture.ts`:

```typescript
export const MAX_RECORDING_SECONDS = 60;
export const TARGET_SAMPLE_RATE = 16_000;

export function secondsToTimerLabel(seconds: number): string {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safeSeconds / 60);
  const remainingSeconds = safeSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
}

export function buildLevelBuckets(data: Uint8Array, bucketCount: number): number[] {
  if (bucketCount <= 0) {
    return [];
  }
  const bucketSize = Math.max(1, Math.floor(data.length / bucketCount));
  return Array.from({ length: bucketCount }, (_, index) => {
    const start = index * bucketSize;
    const end = Math.min(data.length, start + bucketSize);
    let max = 0;
    for (let cursor = start; cursor < end; cursor += 1) {
      max = Math.max(max, Math.abs(data[cursor] - 128));
    }
    return Math.min(1, Math.round((max / 127) * 100) / 100);
  });
}

export function encodeWav(samples: Float32Array, sampleRate: number): Uint8Array {
  const pcm = resampleTo16Khz(samples, sampleRate);
  const buffer = new ArrayBuffer(44 + pcm.length * 2);
  const view = new DataView(buffer);

  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + pcm.length * 2, true);
  writeAscii(view, 8, "WAVE");
  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, TARGET_SAMPLE_RATE, true);
  view.setUint32(28, TARGET_SAMPLE_RATE * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, "data");
  view.setUint32(40, pcm.length * 2, true);

  let offset = 44;
  for (const sample of pcm) {
    const clamped = Math.max(-1, Math.min(1, sample));
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
    offset += 2;
  }

  return new Uint8Array(buffer);
}

function resampleTo16Khz(samples: Float32Array, sampleRate: number): Float32Array {
  if (sampleRate === TARGET_SAMPLE_RATE) {
    return samples;
  }
  const ratio = sampleRate / TARGET_SAMPLE_RATE;
  const outputLength = Math.max(1, Math.floor(samples.length / ratio));
  const output = new Float32Array(outputLength);
  for (let index = 0; index < outputLength; index += 1) {
    output[index] = samples[Math.min(samples.length - 1, Math.floor(index * ratio))];
  }
  return output;
}

function writeAscii(view: DataView, offset: number, value: string) {
  for (let index = 0; index < value.length; index += 1) {
    view.setUint8(offset + index, value.charCodeAt(index));
  }
}

export function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    const chunk = bytes.slice(index, index + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}
```

- [ ] **Step 5: Implement `asrApi.ts`**

Create `src/features/voice/asrApi.ts`:

```typescript
import { invoke } from "@tauri-apps/api/core";

import { bytesToBase64 } from "./audioCapture";

export type AsrStatus = {
  available: boolean;
  configured: boolean;
  modelPath: string | null;
  message: string;
  errorCode: string | null;
};

export type AsrTranscription = {
  text: string;
};

export async function getAsrStatus(): Promise<AsrStatus> {
  try {
    return await invoke<AsrStatus>("get_asr_status");
  } catch (error) {
    return {
      available: false,
      configured: false,
      modelPath: null,
      message: String(error),
      errorCode: "asr_status_unavailable",
    };
  }
}

export async function transcribeVoiceAudio(
  wavBytes: Uint8Array,
): Promise<AsrTranscription> {
  return invoke<AsrTranscription>("transcribe_voice_audio", {
    payload: { wavBase64: bytesToBase64(wavBytes) },
  });
}
```

- [ ] **Step 6: Run frontend helper tests**

Run:

```powershell
npm run frontend:test -- src/features/voice/draftInsertion.test.ts src/features/voice/audioCapture.test.ts src/features/voice/asrApi.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/features/voice/asrApi.ts src/features/voice/asrApi.test.ts src/features/voice/audioCapture.ts src/features/voice/audioCapture.test.ts src/features/voice/draftInsertion.ts src/features/voice/draftInsertion.test.ts
git commit -m "feat: add voice input frontend helpers"
```

---

### Task 4: Chat Composer Voice UI

**Files:**
- Create: `src/features/voice/AudioTrack.tsx`
- Create: `src/features/voice/AudioTrack.test.tsx`
- Modify: `src/features/chat/ChatPanel.tsx`
- Modify: `src/features/chat/ChatPanel.test.tsx`
- Modify: `src/app/app.css`

- [ ] **Step 1: Write failing UI tests**

Create `src/features/voice/AudioTrack.test.tsx`:

```typescript
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AudioTrack } from "./AudioTrack";

describe("AudioTrack", () => {
  it("renders a timer and level bars", () => {
    const markup = renderToStaticMarkup(
      <AudioTrack elapsedSeconds={12} levels={[0, 0.5, 1]} maxSeconds={60} />,
    );

    expect(markup).toContain("00:12 / 01:00");
    expect((markup.match(/class="voiceLevelBar"/g) ?? []).length).toBe(3);
    expect(markup).toContain("height:50%");
  });
});
```

Modify `src/features/chat/ChatPanel.test.tsx`:

```typescript
it("renders a disabled microphone button when ASR is unavailable", () => {
  const markup = renderToStaticMarkup(
    <ChatPanel
      messages={messages}
      pendingAttachments={[]}
      draft=""
      onDraftChange={() => undefined}
      onSend={() => undefined}
      onAddFile={() => undefined}
      voiceInput={{
        available: false,
        status: "unavailable",
        message: "未配置语音模型",
        elapsedSeconds: 0,
        maxSeconds: 60,
        levels: [],
      }}
      onVoiceToggle={() => undefined}
      onDraftSelectionChange={() => undefined}
    />,
  );

  expect(markup).toContain("语音输入");
  expect(markup).toContain("disabled");
  expect(markup).toContain("未配置语音模型");
});

it("renders the recording audio track below the textarea", () => {
  const markup = renderToStaticMarkup(
    <ChatPanel
      messages={messages}
      pendingAttachments={[]}
      draft=""
      onDraftChange={() => undefined}
      onSend={() => undefined}
      onAddFile={() => undefined}
      voiceInput={{
        available: true,
        status: "recording",
        message: "录音中",
        elapsedSeconds: 8,
        maxSeconds: 60,
        levels: [0.2, 0.9],
      }}
      onVoiceToggle={() => undefined}
      onDraftSelectionChange={() => undefined}
    />,
  );

  expect(markup).toContain("00:08 / 01:00");
  expect(markup).toContain("voiceLevelBar");
});
```

Update the existing action test to expect three buttons.

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
npm run frontend:test -- src/features/voice/AudioTrack.test.tsx src/features/chat/ChatPanel.test.tsx
```

Expected: FAIL because voice props and `AudioTrack` do not exist.

- [ ] **Step 3: Implement `AudioTrack.tsx`**

Create `src/features/voice/AudioTrack.tsx`:

```tsx
import { secondsToTimerLabel } from "./audioCapture";

type AudioTrackProps = {
  elapsedSeconds: number;
  maxSeconds: number;
  levels: number[];
};

export function AudioTrack({
  elapsedSeconds,
  maxSeconds,
  levels,
}: AudioTrackProps) {
  return (
    <div className="voiceTrack" aria-label="录音音轨">
      <div className="voiceLevelBars" aria-hidden="true">
        {levels.map((level, index) => (
          <span
            className="voiceLevelBar"
            key={`${index}-${level}`}
            style={{ height: `${Math.max(8, Math.round(level * 100))}%` }}
          />
        ))}
      </div>
      <span className="voiceTimer">
        {secondsToTimerLabel(elapsedSeconds)} / {secondsToTimerLabel(maxSeconds)}
      </span>
    </div>
  );
}
```

- [ ] **Step 4: Extend `ChatPanel.tsx`**

Add imports:

```tsx
import { AudioTrack } from "../voice/AudioTrack";
import type { DraftSelection } from "../voice/draftInsertion";
```

Add types:

```tsx
export type VoiceInputStatus =
  | "checking"
  | "unavailable"
  | "idle"
  | "recording"
  | "transcribing"
  | "failed";

export type VoiceInputView = {
  available: boolean;
  status: VoiceInputStatus;
  message: string | null;
  elapsedSeconds: number;
  maxSeconds: number;
  levels: number[];
};
```

Extend props:

```tsx
  voiceInput: VoiceInputView;
  onVoiceToggle(selection: DraftSelection | null): void;
  onDraftSelectionChange(selection: DraftSelection | null): void;
```

Inside the component, add a textarea ref and selection helpers:

```tsx
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const currentSelection = (): DraftSelection | null => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return null;
    }
    return {
      start: textarea.selectionStart,
      end: textarea.selectionEnd,
    };
  };
  const reportSelection = () => onDraftSelectionChange(currentSelection());
```

Wire the textarea:

```tsx
          ref={textareaRef}
          onSelect={reportSelection}
          onClick={reportSelection}
          onKeyUp={reportSelection}
          onFocus={reportSelection}
```

Render the track after the textarea:

```tsx
        {voiceInput.status === "recording" ? (
          <AudioTrack
            elapsedSeconds={voiceInput.elapsedSeconds}
            levels={voiceInput.levels}
            maxSeconds={voiceInput.maxSeconds}
          />
        ) : null}
        {voiceInput.status === "failed" && voiceInput.message ? (
          <p className="voiceInputError">{voiceInput.message}</p>
        ) : null}
```

Add microphone button between add file and send:

```tsx
          <button
            aria-label="语音输入"
            className="secondaryButton voiceButton"
            disabled={!voiceInput.available || voiceInput.status === "transcribing"}
            onClick={() => onVoiceToggle(currentSelection())}
            title={voiceInput.message ?? "语音输入"}
            type="button"
          >
            {voiceInput.status === "recording"
              ? "停止录音"
              : voiceInput.status === "transcribing"
                ? "转写中"
                : "语音"}
          </button>
```

- [ ] **Step 5: Update CSS**

Modify `src/app/app.css`:

```css
.voiceTrack {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-height: 34px;
  padding: 8px 10px;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  background: #eff6ff;
}

.voiceLevelBars {
  display: grid;
  grid-template-columns: repeat(32, minmax(2px, 1fr));
  align-items: center;
  gap: 3px;
  height: 18px;
}

.voiceLevelBar {
  display: block;
  min-height: 3px;
  border-radius: 999px;
  background: #2563eb;
}

.voiceTimer {
  color: #1e3a8a;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  line-height: 16px;
}

.voiceInputError {
  margin: 0;
  color: #b91c1c;
  font-size: 12px;
  line-height: 17px;
}
```

Update mobile `.composerActions`:

```css
.composerActions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
```

- [ ] **Step 6: Run UI tests**

Run:

```powershell
npm run frontend:test -- src/features/voice/AudioTrack.test.tsx src/features/chat/ChatPanel.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/features/voice/AudioTrack.tsx src/features/voice/AudioTrack.test.tsx src/features/chat/ChatPanel.tsx src/features/chat/ChatPanel.test.tsx src/app/app.css
git commit -m "feat: add voice controls to chat composer"
```

---

### Task 5: App-Level Voice Orchestration

**Files:**
- Modify: `src/app/App.tsx`
- Create: `src/features/voice/voiceSession.ts`
- Create: `src/features/voice/voiceSession.test.ts`

- [ ] **Step 1: Write failing orchestration tests**

Create `src/features/voice/voiceSession.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import {
  createInitialVoiceInput,
  voiceFailed,
  voiceRecording,
  voiceTranscribing,
  voiceUnavailable,
} from "./voiceSession";

describe("voiceSession view state helpers", () => {
  it("creates idle state from available ASR status", () => {
    expect(
      createInitialVoiceInput({
        available: true,
        configured: true,
        modelPath: "D:\\Models\\Qwen3-ASR-1.7B",
        message: "voice model is configured",
        errorCode: null,
      }),
    ).toMatchObject({
      available: true,
      status: "idle",
      message: "voice model is configured",
    });
  });

  it("creates unavailable state from unavailable ASR status", () => {
    expect(
      createInitialVoiceInput({
        available: false,
        configured: false,
        modelPath: null,
        message: "not configured",
        errorCode: "asr_not_configured",
      }),
    ).toMatchObject({
      available: false,
      status: "unavailable",
      message: "未配置语音模型",
    });
  });

  it("updates recording, transcribing, and failed state", () => {
    const base = voiceRecording(createInitialVoiceInput(null), [0.2], 3);

    expect(base.status).toBe("recording");
    expect(voiceTranscribing(base).status).toBe("transcribing");
    expect(voiceFailed(base, "麦克风不可用")).toMatchObject({
      status: "failed",
      message: "麦克风不可用",
    });
  });
});
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```powershell
npm run frontend:test -- src/features/voice/voiceSession.test.ts
```

Expected: FAIL because `voiceSession.ts` does not exist.

- [ ] **Step 3: Implement `voiceSession.ts`**

Create `src/features/voice/voiceSession.ts`:

```typescript
import type { AsrStatus } from "./asrApi";
import { MAX_RECORDING_SECONDS } from "./audioCapture";
import type { VoiceInputView } from "../chat/ChatPanel";

const disabledVoiceMessage = "未配置语音模型";

export function createInitialVoiceInput(status: AsrStatus | null): VoiceInputView {
  if (!status) {
    return {
      available: false,
      status: "checking",
      message: "正在检查语音模型",
      elapsedSeconds: 0,
      maxSeconds: MAX_RECORDING_SECONDS,
      levels: [],
    };
  }

  if (!status.available) {
    return {
      available: false,
      status: "unavailable",
      message: disabledVoiceMessage,
      elapsedSeconds: 0,
      maxSeconds: MAX_RECORDING_SECONDS,
      levels: [],
    };
  }

  return {
    available: true,
    status: "idle",
    message: status.message,
    elapsedSeconds: 0,
    maxSeconds: MAX_RECORDING_SECONDS,
    levels: [],
  };
}

export function voiceRecording(
  current: VoiceInputView,
  levels: number[] = current.levels,
  elapsedSeconds = current.elapsedSeconds,
): VoiceInputView {
  return {
    ...current,
    available: true,
    status: "recording",
    message: "录音中",
    elapsedSeconds,
    levels,
  };
}

export function voiceTranscribing(current: VoiceInputView): VoiceInputView {
  return {
    ...current,
    status: "transcribing",
    message: "转写中",
  };
}

export function voiceFailed(
  current: VoiceInputView,
  message: string,
): VoiceInputView {
  return {
    ...current,
    status: "failed",
    message,
    elapsedSeconds: 0,
    levels: [],
  };
}
```

- [ ] **Step 4: Integrate in `App.tsx`**

Add imports:

```tsx
import { getAsrStatus, transcribeVoiceAudio } from "../features/voice/asrApi";
import {
  buildLevelBuckets,
  encodeWav,
  MAX_RECORDING_SECONDS,
} from "../features/voice/audioCapture";
import { insertTranscriptIntoDraft, type DraftSelection } from "../features/voice/draftInsertion";
import {
  createInitialVoiceInput,
  voiceFailed,
  voiceRecording,
  voiceTranscribing,
} from "../features/voice/voiceSession";
```

Add state and refs:

```tsx
  const [voiceInput, setVoiceInput] = useState(createInitialVoiceInput(null));
  const lastDraftSelectionRef = useRef<DraftSelection | null>(null);
  const recordingStreamRef = useRef<MediaStream | null>(null);
  const recordingChunksRef = useRef<Float32Array[]>([]);
  const recordingSampleRateRef = useRef(48_000);
  const recordingStartedAtRef = useRef<number | null>(null);
  const recordingTimerRef = useRef<number | null>(null);
  const recordingAudioContextRef = useRef<AudioContext | null>(null);
  const recordingProcessorRef = useRef<ScriptProcessorNode | null>(null);
```

Add ASR status effect:

```tsx
  useEffect(() => {
    let cancelled = false;
    getAsrStatus().then((status) => {
      if (!cancelled) {
        setVoiceInput(createInitialVoiceInput(status));
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);
```

Add handlers. Keep the first implementation direct in `App.tsx`; extract only if it grows past readability:

```tsx
  const stopRecordingStream = () => {
    recordingProcessorRef.current?.disconnect();
    recordingProcessorRef.current = null;
    void recordingAudioContextRef.current?.close();
    recordingAudioContextRef.current = null;
    recordingStreamRef.current?.getTracks().forEach((track) => track.stop());
    recordingStreamRef.current = null;
    if (recordingTimerRef.current !== null) {
      window.clearInterval(recordingTimerRef.current);
      recordingTimerRef.current = null;
    }
  };

  const handleDraftSelectionChange = (selection: DraftSelection | null) => {
    lastDraftSelectionRef.current = selection;
  };

  const startVoiceRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recordingStreamRef.current = stream;
      recordingChunksRef.current = [];
      recordingStartedAtRef.current = Date.now();
      const audioContext = new AudioContext();
      recordingAudioContextRef.current = audioContext;
      recordingSampleRateRef.current = audioContext.sampleRate;
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 64;
      source.connect(analyser);
      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      recordingProcessorRef.current = processor;
      source.connect(processor);
      processor.connect(audioContext.destination);
      processor.onaudioprocess = (event) => {
        recordingChunksRef.current.push(
          new Float32Array(event.inputBuffer.getChannelData(0)),
        );
      };
      const levelData = new Uint8Array(analyser.frequencyBinCount);
      setVoiceInput((current) => voiceRecording(current));
      recordingTimerRef.current = window.setInterval(() => {
        analyser.getByteTimeDomainData(levelData);
        const elapsed = recordingStartedAtRef.current
          ? Math.floor((Date.now() - recordingStartedAtRef.current) / 1000)
          : 0;
        setVoiceInput((current) =>
          voiceRecording(current, buildLevelBuckets(levelData, 32), elapsed),
        );
        if (elapsed >= MAX_RECORDING_SECONDS) {
          void stopVoiceRecording(lastDraftSelectionRef.current);
        }
      }, 250);
    } catch (error) {
      setVoiceInput((current) =>
        voiceFailed(current, `麦克风不可用：${String(error)}`),
      );
    }
  };

  const stopVoiceRecording = async (selection: DraftSelection | null) => {
    const capturedSelection = selection ?? lastDraftSelectionRef.current;
    const chunks = recordingChunksRef.current;
    stopRecordingStream();
    setVoiceInput((current) => voiceTranscribing(current));
    try {
      const totalLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
      const samples = new Float32Array(totalLength);
      let offset = 0;
      for (const chunk of chunks) {
        samples.set(chunk, offset);
        offset += chunk.length;
      }
      const wavBytes = encodeWav(samples, recordingSampleRateRef.current);
      const transcript = await transcribeVoiceAudio(wavBytes);
      setDraft((current) =>
        insertTranscriptIntoDraft({
          currentDraft: current,
          transcript: transcript.text,
          selection: capturedSelection,
        }),
      );
      setVoiceInput((current) => ({
        ...current,
        status: "idle",
        message: "语音模型已就绪",
        elapsedSeconds: 0,
        levels: [],
      }));
    } catch (error) {
      setVoiceInput((current) =>
        voiceFailed(current, `语音转写失败：${String(error)}`),
      );
    }
  };

  const handleVoiceToggle = async (selection: DraftSelection | null) => {
    if (!voiceInput.available || voiceInput.status === "transcribing") {
      return;
    }
    if (voiceInput.status === "recording") {
      await stopVoiceRecording(selection);
      return;
    }
    await startVoiceRecording();
  };
```

Pass props to `ChatPanel`:

```tsx
          voiceInput={voiceInput}
          onVoiceToggle={handleVoiceToggle}
          onDraftSelectionChange={handleDraftSelectionChange}
```

- [ ] **Step 5: Run focused frontend tests**

Run:

```powershell
npm run frontend:test -- src/features/voice/voiceSession.test.ts src/features/voice/draftInsertion.test.ts src/features/chat/ChatPanel.test.tsx
npm run frontend:lint
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/app/App.tsx src/features/voice/voiceSession.ts src/features/voice/voiceSession.test.ts
git commit -m "feat: orchestrate voice transcription in app"
```

---

### Task 6: Verification And Development Notes

**Files:**
- Modify: `docs/windows-desktop-runbook.md`
- Optional local-only command: no commit for local model path values.

- [ ] **Step 1: Add runbook note**

Modify `docs/windows-desktop-runbook.md` with:

```markdown
## Local ASR development

Voice input is enabled in development when `ALITA_ASR_MODEL_PATH` points to a local Qwen3-ASR-1.7B model directory. The ASR path is intentionally not stored in project files.

Example:

```powershell
$env:ALITA_ASR_MODEL_PATH="D:\Models\Qwen3-ASR-1.7B"
npm run desktop:dev
```

The first transcription lazily loads the ASR model on CPU. The microphone button remains visible but disabled when the environment variable is missing or the runtime package is not installed.
```

- [ ] **Step 2: Run full automated verification**

Run:

```powershell
npm run frontend:test
npm run frontend:lint
python -m pytest python/tests -q
cargo test --manifest-path src-tauri/Cargo.toml
```

Expected: PASS.

- [ ] **Step 3: Run manual development verification**

Set a real local model path:

```powershell
$env:ALITA_ASR_MODEL_PATH="D:\Models\Qwen3-ASR-1.7B"
npm run desktop:dev
```

Manual checks:

- Open or create a project.
- Confirm the microphone button is enabled.
- Click microphone, speak for a short sentence, and confirm the waveform moves.
- Stop recording and confirm transcription starts.
- Confirm the transcript is inserted into an empty draft.
- Type text, place the cursor in the middle, record again, and confirm insertion at the captured cursor.
- Select text, record again, and confirm the selected text is replaced.
- Confirm no audio file is left in the system temp directory with an `alita-asr-*.wav` name after success or failure.

- [ ] **Step 4: Commit docs**

```powershell
git add docs/windows-desktop-runbook.md
git commit -m "docs: add local ASR development notes"
```

---

## Final Verification

Before declaring the feature complete, run:

```powershell
git status --short
npm run frontend:test
npm run frontend:lint
python -m pytest python/tests -q
cargo test --manifest-path src-tauri/Cargo.toml
```

Expected: all tests pass. `git status --short` should show only intentional changes, or no changes after the final commits.

Manual verification with a real `ALITA_ASR_MODEL_PATH` is required before claiming real Qwen3-ASR transcription works on CPU.
