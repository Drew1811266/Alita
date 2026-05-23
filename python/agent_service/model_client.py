from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from collections.abc import Iterable, Iterator
from typing import Callable, Literal

from agent_service.model_policy import ModelCallPolicy, apply_policy_defaults


ChatRole = Literal["system", "user", "assistant", "tool"]
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 1024


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
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


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
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ) -> str:
        if not self.config.enabled:
            raise ModelRuntimeDisabled("llama.cpp model runtime is not configured")

        payload = self._chat_payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            policy=policy,
        )
        policy_has_extra_body = bool(policy and _policy_extra_body(policy))
        endpoint = f"{self.config.base_url}/v1/chat/completions"

        try:
            response = self._transport(
                endpoint,
                payload,
                self.config.timeout_seconds,
            )
        except ModelRuntimeRequestFailed as error:
            if not policy_has_extra_body or not _should_retry_without_policy_extra_body(error):
                raise

            payload = self._chat_payload(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
                policy=policy,
                include_policy_extra_body=False,
            )
            response = self._transport(
                endpoint,
                payload,
                self.config.timeout_seconds,
            )

        content = _extract_chat_content(response)
        if content.strip():
            return content

        if _should_retry_empty_reasoning_response(response):
            retry_payload = {
                **payload,
                "max_tokens": max(payload["max_tokens"] * 4, 4096),
            }
            retry_response = self._transport(
                endpoint,
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
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ) -> Iterator[str]:
        if not self.config.enabled:
            raise ModelRuntimeDisabled("llama.cpp model runtime is not configured")

        payload = self._chat_payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            policy=policy,
        )
        policy_has_extra_body = bool(policy and _policy_extra_body(policy))
        endpoint = f"{self.config.base_url}/v1/chat/completions"

        yielded = False
        try:
            for delta in self._stream_chat_payload(endpoint, payload):
                yielded = True
                yield delta
        except ModelRuntimeRequestFailed as error:
            if (
                not policy_has_extra_body
                or yielded
                or not _should_retry_without_policy_extra_body(error)
            ):
                raise

            retry_payload = self._chat_payload(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                policy=policy,
                include_policy_extra_body=False,
            )
            yield from self._stream_chat_payload(endpoint, retry_payload)

    def _stream_chat_payload(self, endpoint: str, payload: dict) -> Iterator[str]:
        for data in _iter_sse_data(
            self._stream_transport(
                endpoint,
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

    def _chat_payload(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None,
        max_tokens: int | None,
        stream: bool,
        policy: ModelCallPolicy | None,
        include_policy_extra_body: bool = True,
    ) -> dict:
        if policy is None:
            resolved_temperature = (
                DEFAULT_TEMPERATURE if temperature is None else temperature
            )
            resolved_max_tokens = (
                DEFAULT_MAX_TOKENS if max_tokens is None else max_tokens
            )
            resolved_stream = stream
            extra_body: dict = {}
        else:
            resolved = apply_policy_defaults(
                policy,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
            )
            resolved_temperature = resolved.temperature
            resolved_max_tokens = resolved.max_tokens
            resolved_stream = resolved.stream
            extra_body = _policy_extra_body(policy) if include_policy_extra_body else {}

        payload = dict(extra_body)
        payload.update(
            {
                "model": self.config.model,
                "messages": [
                    {"role": message.role, "content": message.content}
                    for message in messages
                ],
                "temperature": resolved_temperature,
                "max_tokens": resolved_max_tokens,
                "stream": resolved_stream,
            }
        )
        return payload


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
    except urllib.error.HTTPError as error:
        detail = _read_http_error_body(error)
        message = f"llama.cpp chat request failed: HTTP {error.code}"
        if detail:
            message = f"{message}: {detail}"
        raise ModelRuntimeRequestFailed(message, status_code=error.code) from error
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
    except urllib.error.HTTPError as error:
        detail = _read_http_error_body(error)
        message = f"llama.cpp streaming chat request failed: HTTP {error.code}"
        if detail:
            message = f"{message}: {detail}"
        raise ModelRuntimeRequestFailed(message, status_code=error.code) from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise ModelRuntimeRequestFailed(f"llama.cpp streaming chat request failed: {error}") from error


def _policy_extra_body(policy: ModelCallPolicy) -> dict:
    chat_template_kwargs: dict[str, bool] = {}
    if policy.thinking == "off":
        chat_template_kwargs["enable_thinking"] = False
    elif policy.thinking == "deep" or policy.preserve_thinking:
        chat_template_kwargs["enable_thinking"] = True

    if policy.preserve_thinking:
        chat_template_kwargs["preserve_thinking"] = True

    if not chat_template_kwargs:
        return {}
    return {"chat_template_kwargs": chat_template_kwargs}


def _should_retry_without_policy_extra_body(error: ModelRuntimeRequestFailed) -> bool:
    return error.status_code in {400, 422}


def _read_http_error_body(error: urllib.error.HTTPError) -> str:
    try:
        return error.read().decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


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

