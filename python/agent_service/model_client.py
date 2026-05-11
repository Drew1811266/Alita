from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from collections.abc import Iterable, Iterator
from typing import Callable, Literal


ChatRole = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ChatMessage:
    role: ChatRole
    content: str


@dataclass(frozen=True)
class ModelClientConfig:
    enabled: bool = False
    base_url: str = "http://127.0.0.1:8766"
    model: str = "local-llama-cpp"
    timeout_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> "ModelClientConfig":
        model_path = os.getenv("ALITA_LLAMA_MODEL_PATH", "").strip()
        return cls(
            enabled=bool(model_path),
            base_url=os.getenv("ALITA_LLAMA_BASE_URL", "http://127.0.0.1:8766").rstrip("/"),
            model=os.getenv("ALITA_LLAMA_MODEL_NAME", "local-llama-cpp"),
        )


class ModelRuntimeDisabled(RuntimeError):
    pass


class ModelRuntimeRequestFailed(RuntimeError):
    pass


Transport = Callable[[str, dict, float], dict]
StreamTransport = Callable[[str, dict, float], Iterable[bytes | str]]


class LlamaCppModelClient:
    def __init__(
        self,
        config: ModelClientConfig | None = None,
        *,
        transport: Transport | None = None,
        stream_transport: StreamTransport | None = None,
    ) -> None:
        self.config = config or ModelClientConfig.from_env()
        self._transport = transport or _post_json
        self._stream_transport = stream_transport or _post_json_stream

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str:
        if not self.config.enabled:
            raise ModelRuntimeDisabled("llama.cpp model runtime is not configured")

        payload = {
            "model": self.config.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        response = self._transport(
            f"{self.config.base_url}/v1/chat/completions",
            payload,
            self.config.timeout_seconds,
        )
        content = _extract_chat_content(response)
        if content.strip():
            return content

        if _should_retry_empty_reasoning_response(response):
            retry_payload = {
                **payload,
                "max_tokens": max(max_tokens * 4, 4096),
            }
            retry_response = self._transport(
                f"{self.config.base_url}/v1/chat/completions",
                retry_payload,
                self.config.timeout_seconds,
            )
            retry_content = _extract_chat_content(retry_response)
            if retry_content.strip():
                return retry_content

        raise ModelRuntimeRequestFailed("llama.cpp returned an empty chat response")

    def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> Iterator[str]:
        if not self.config.enabled:
            raise ModelRuntimeDisabled("llama.cpp model runtime is not configured")

        payload = {
            "model": self.config.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        for data in _iter_sse_data(
            self._stream_transport(
                f"{self.config.base_url}/v1/chat/completions",
                payload,
                self.config.timeout_seconds,
            )
        ):
            if data == "[DONE]":
                break

            try:
                payload = json.loads(data)
                delta = payload["choices"][0]["delta"].get("content", "")
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
                raise ModelRuntimeRequestFailed(
                    "llama.cpp returned an unexpected streaming chat response shape"
                ) from error

            if delta:
                yield delta


def _post_json(url: str, payload: dict, timeout: float) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise ModelRuntimeRequestFailed(f"llama.cpp chat request failed: {error}") from error


def _post_json_stream(url: str, payload: dict, timeout: float) -> Iterable[bytes]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            yield from response
    except (urllib.error.URLError, TimeoutError) as error:
        raise ModelRuntimeRequestFailed(f"llama.cpp streaming chat request failed: {error}") from error


def _extract_chat_content(response: dict) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise ModelRuntimeRequestFailed(
            "llama.cpp returned an unexpected chat response shape"
        ) from error

    if not isinstance(content, str):
        raise ModelRuntimeRequestFailed(
            "llama.cpp returned an unexpected chat response shape"
        )
    return content


def _should_retry_empty_reasoning_response(response: dict) -> bool:
    try:
        choice = response["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError):
        return False

    return (
        choice.get("finish_reason") == "length"
        and isinstance(message, dict)
        and bool(str(message.get("reasoning_content", "")).strip())
    )


def _iter_sse_data(chunks: Iterable[bytes | str]) -> Iterator[str]:
    for chunk in chunks:
        text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith(":") or not line.startswith("data:"):
                continue
            yield line.removeprefix("data:").strip()

