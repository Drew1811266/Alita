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


@dataclass(frozen=True)
class AgentModelClientConfig:
    mode: Literal["local", "api"] = "local"
    enabled: bool = False
    base_url: str = "http://127.0.0.1:8766"
    model: str = "local-llama-cpp"
    api_key: str | None = None
    provider_display_name: str = "API provider"
    timeout_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> "AgentModelClientConfig":
        mode = os.getenv("ALITA_AGENT_MODEL_MODE", "local").strip().lower()
        if mode == "api":
            api_key = os.getenv("ALITA_API_KEY", "").strip() or None
            return cls(
                mode="api",
                enabled=bool(api_key),
                base_url=os.getenv("ALITA_API_BASE_URL", "").strip().rstrip("/"),
                model=os.getenv("ALITA_API_MODEL", "").strip(),
                api_key=api_key,
                provider_display_name=os.getenv("ALITA_API_PROVIDER_NAME", "API provider"),
            )
        llama = ModelClientConfig.from_env()
        return cls(
            mode="local",
            enabled=llama.enabled,
            base_url=llama.base_url,
            model=llama.model,
            timeout_seconds=llama.timeout_seconds,
        )


class ModelRuntimeDisabled(RuntimeError):
    pass


class ModelRuntimeRequestFailed(RuntimeError):
    pass


Transport = Callable[[str, dict, float], dict]
StreamTransport = Callable[[str, dict, float], Iterable[bytes | str]]
ApiTransport = Callable[[str, dict, float, dict[str, str]], dict]
ApiStreamTransport = Callable[[str, dict, float, dict[str, str]], Iterable[bytes | str]]


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


class OpenAICompatibleModelClient:
    def __init__(
        self,
        config: AgentModelClientConfig | None = None,
        *,
        transport: ApiTransport | None = None,
        stream_transport: ApiStreamTransport | None = None,
    ) -> None:
        self.config = config or AgentModelClientConfig.from_env()
        self._transport = transport or _post_json_with_headers
        self._stream_transport = stream_transport or _post_json_stream_with_headers

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str:
        self._ensure_enabled()

        response = self._transport(
            self._chat_url(),
            self._payload(messages, temperature, max_tokens, stream=False),
            self.config.timeout_seconds,
            self._headers(),
        )
        content = _extract_api_chat_content(response)
        if content.strip():
            return content

        raise ModelRuntimeRequestFailed("OpenAI-compatible API returned an empty chat response")

    def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> Iterator[str]:
        self._ensure_enabled()

        for data in _iter_sse_data(
            self._stream_transport(
                self._chat_url(),
                self._payload(messages, temperature, max_tokens, stream=True),
                self.config.timeout_seconds,
                self._headers(),
            )
        ):
            if data == "[DONE]":
                break

            try:
                payload = json.loads(data)
                delta = payload["choices"][0]["delta"].get("content", "")
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
                raise ModelRuntimeRequestFailed(
                    "OpenAI-compatible API returned an unexpected streaming chat response shape"
                ) from error

            if not isinstance(delta, str):
                raise ModelRuntimeRequestFailed(
                    "OpenAI-compatible API returned an unexpected streaming chat response shape"
                )
            if delta:
                yield delta

    def _ensure_enabled(self) -> None:
        if not self.config.api_key or not self.config.api_key.strip():
            raise ModelRuntimeDisabled("API key is not configured")
        if not self.config.base_url.strip():
            raise ModelRuntimeDisabled("API base URL is not configured")
        if not self.config.model.strip():
            raise ModelRuntimeDisabled("API model is not configured")
        if not self.config.enabled:
            raise ModelRuntimeDisabled(
                f"{self.config.provider_display_name} model runtime is not configured"
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(
        self,
        messages: list[ChatMessage],
        temperature: float,
        max_tokens: int,
        *,
        stream: bool,
    ) -> dict:
        return {
            "model": self.config.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

    def _chat_url(self) -> str:
        return f"{self.config.base_url.rstrip('/')}/chat/completions"


def create_model_client(
    config: AgentModelClientConfig | None = None,
) -> LlamaCppModelClient | OpenAICompatibleModelClient:
    resolved_config = config or AgentModelClientConfig.from_env()
    if resolved_config.mode == "api":
        return OpenAICompatibleModelClient(resolved_config)

    return LlamaCppModelClient(
        ModelClientConfig(
            enabled=resolved_config.enabled,
            base_url=resolved_config.base_url,
            model=resolved_config.model,
            timeout_seconds=resolved_config.timeout_seconds,
        )
    )


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


def _post_json_with_headers(
    url: str,
    payload: dict,
    timeout: float,
    headers: dict[str, str],
) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise ModelRuntimeRequestFailed(
            f"API chat request failed with HTTP status {error.code}"
        ) from error
    except urllib.error.URLError as error:
        raise ModelRuntimeRequestFailed(f"API chat request failed: {error.reason}") from error
    except TimeoutError as error:
        raise ModelRuntimeRequestFailed("API chat request timed out") from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ModelRuntimeRequestFailed("API chat request returned invalid JSON") from error


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


def _post_json_stream_with_headers(
    url: str,
    payload: dict,
    timeout: float,
    headers: dict[str, str],
) -> Iterable[bytes]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            yield from response
    except urllib.error.HTTPError as error:
        raise ModelRuntimeRequestFailed(
            f"API streaming chat request failed with HTTP status {error.code}"
        ) from error
    except urllib.error.URLError as error:
        raise ModelRuntimeRequestFailed(
            f"API streaming chat request failed: {error.reason}"
        ) from error
    except TimeoutError as error:
        raise ModelRuntimeRequestFailed("API streaming chat request timed out") from error


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


def _extract_api_chat_content(response: dict) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise ModelRuntimeRequestFailed(
            "OpenAI-compatible API returned an unexpected chat response shape"
        ) from error

    if not isinstance(content, str):
        raise ModelRuntimeRequestFailed(
            "OpenAI-compatible API returned an unexpected chat response shape"
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
