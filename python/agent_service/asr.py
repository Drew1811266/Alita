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
