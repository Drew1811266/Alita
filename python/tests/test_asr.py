import sys
import threading
import time
import types
from pathlib import Path

import pytest

import agent_service.app as app_module
from agent_service.asr import (
    ALITA_ASR_MODEL_PATH_ENV,
    ASRError,
    QwenASRProvider,
    ASRService,
    ASRStatus,
    TranscriptionRequest,
    TranscriptionResponse,
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


def install_fake_qwen_asr(monkeypatch, result):
    load_calls = []
    transcribe_calls = []

    class FakeQwen3ASRModel:
        @classmethod
        def from_pretrained(cls, model_path: str, **kwargs):
            load_calls.append((model_path, kwargs))
            return cls()

        def transcribe(self, audio_path: str, language: str):
            transcribe_calls.append((audio_path, language))
            return [result]

    fake_module = types.SimpleNamespace(Qwen3ASRModel=FakeQwen3ASRModel)
    monkeypatch.setitem(sys.modules, "qwen_asr", fake_module)
    return load_calls, transcribe_calls


class FakeEndpointService:
    def __init__(self, response: TranscriptionResponse | None = None):
        self.response = response or TranscriptionResponse(text="endpoint text")
        self.error: ASRError | None = None
        self.requests: list[TranscriptionRequest] = []

    def transcribe(self, request: TranscriptionRequest) -> TranscriptionResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response


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


@pytest.mark.parametrize("language", ["zh", "zh-CN", "chinese"])
def test_qwen_provider_loads_cpu_model_and_normalizes_chinese_language(
    monkeypatch, tmp_path, language
):
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"RIFF....WAVEfmt ")
    model_dir = tmp_path / "Qwen3-ASR-1.7B"
    model_dir.mkdir()
    result = types.SimpleNamespace(text=" qwen object text ")
    load_calls, transcribe_calls = install_fake_qwen_asr(monkeypatch, result)

    provider = QwenASRProvider(model_dir)
    text = provider.transcribe(audio_path, language)

    assert text == "qwen object text"
    assert load_calls == [(str(model_dir), {"device_map": "cpu"})]
    assert transcribe_calls == [(str(audio_path), "Chinese")]


def test_qwen_provider_extracts_text_from_dict_result(monkeypatch, tmp_path):
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"RIFF....WAVEfmt ")
    model_dir = tmp_path / "Qwen3-ASR-1.7B"
    model_dir.mkdir()
    load_calls, transcribe_calls = install_fake_qwen_asr(
        monkeypatch,
        {"text": " qwen dict text "},
    )

    provider = QwenASRProvider(model_dir)
    text = provider.transcribe(audio_path, "chinese")

    assert text == "qwen dict text"
    assert load_calls == [(str(model_dir), {"device_map": "cpu"})]
    assert transcribe_calls == [(str(audio_path), "Chinese")]


def test_transcribe_uses_provider_and_language(tmp_path):
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"RIFF....WAVEfmt ")
    model_dir = tmp_path / "Qwen3-ASR-1.7B"
    model_dir.mkdir()
    provider = FakeProvider(text="hello from audio")
    service = ASRService(provider_factory=lambda _model_path: provider)

    result = service.transcribe(
        TranscriptionRequest(audioPath=str(audio_path), language="zh"),
        model_path=model_dir,
    )

    assert result.text == "hello from audio"
    assert provider.calls == [(audio_path, "zh")]


def test_transcribe_rejects_missing_model_path(tmp_path):
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"RIFF....WAVEfmt ")
    service = ASRService(provider_factory=lambda _model_path: FakeProvider())

    with pytest.raises(ASRError) as error:
        service.transcribe(
            TranscriptionRequest(audioPath=str(audio_path)),
            model_path=tmp_path / "missing-model",
        )

    assert error.value.code == "asr_model_missing"


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


def test_asr_transcribe_endpoint_returns_transcript(monkeypatch):
    monkeypatch.delenv(app_module.SIDECAR_TOKEN_ENV, raising=False)
    service = FakeEndpointService(TranscriptionResponse(text="endpoint transcript"))
    monkeypatch.setattr(app_module, "DEFAULT_ASR_SERVICE", service)
    client = TestClient(app)

    response = client.post(
        "/asr/transcribe",
        json={"audioPath": "input.wav", "language": "zh"},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "endpoint transcript"}
    assert service.requests == [
        TranscriptionRequest(audioPath="input.wav", language="zh")
    ]


def test_asr_transcribe_endpoint_maps_busy_error_to_409(monkeypatch):
    monkeypatch.delenv(app_module.SIDECAR_TOKEN_ENV, raising=False)
    service = FakeEndpointService()
    service.error = ASRError("asr_busy", "transcription is already running")
    monkeypatch.setattr(app_module, "DEFAULT_ASR_SERVICE", service)
    client = TestClient(app)

    response = client.post("/asr/transcribe", json={"audioPath": "input.wav"})

    assert response.status_code == 409
    assert response.json()["detail"]["errorCode"] == "asr_busy"


def test_asr_transcribe_endpoint_maps_other_asr_errors_to_400(monkeypatch):
    monkeypatch.delenv(app_module.SIDECAR_TOKEN_ENV, raising=False)
    service = FakeEndpointService()
    service.error = ASRError("asr_audio_invalid", "temporary audio file is missing")
    monkeypatch.setattr(app_module, "DEFAULT_ASR_SERVICE", service)
    client = TestClient(app)

    response = client.post("/asr/transcribe", json={"audioPath": "input.wav"})

    assert response.status_code == 400
    assert response.json()["detail"]["errorCode"] == "asr_audio_invalid"
