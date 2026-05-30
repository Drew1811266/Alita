from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from collections.abc import Iterable, Iterator
from typing import Any, Callable, Literal

from agent_service.model_tool_adapter import ModelToolCall
from agent_service.model_policy import ModelCallPolicy, apply_policy_defaults


ChatRole = Literal["system", "user", "assistant", "tool"]
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 1024


@dataclass(frozen=True)
class ChatMessage:
    role: ChatRole
    content: str


@dataclass(frozen=True)
class ChatWithToolsResponse:
    content: str
    tool_calls: list[ModelToolCall]


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
    supports_native_tool_calls: bool = False

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
                supports_native_tool_calls=_env_flag("ALITA_API_NATIVE_TOOL_CALLS"),
            )
        llama = ModelClientConfig.from_env()
        return cls(
            mode="local",
            enabled=llama.enabled,
            base_url=llama.base_url,
            model=llama.model,
            timeout_seconds=llama.timeout_seconds,
            supports_native_tool_calls=False,
        )


class ModelRuntimeDisabled(RuntimeError):
    pass


class ModelRuntimeRequestFailed(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


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
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ) -> str:
        self._ensure_enabled()
        payload = self._payload(
            messages,
            temperature,
            max_tokens,
            stream=False,
            policy=policy,
        )
        response = self._transport(
            self._chat_url(),
            payload,
            self.config.timeout_seconds,
            self._headers(),
        )
        content = _extract_api_chat_content(response)
        if content.strip():
            return content

        raise ModelRuntimeRequestFailed("OpenAI-compatible API returned an empty chat response")

    def chat_with_tools(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ) -> ChatWithToolsResponse:
        self._ensure_enabled()
        payload = self._payload(
            messages,
            temperature,
            max_tokens,
            stream=False,
            policy=policy,
        )
        payload["tools"] = list(tools)
        payload["tool_choice"] = tool_choice
        response = self._transport(
            self._chat_url(),
            payload,
            self.config.timeout_seconds,
            self._headers(),
        )
        parsed = _extract_api_chat_with_tools_response(response)
        if parsed.content.strip() or parsed.tool_calls:
            return parsed

        raise ModelRuntimeRequestFailed(
            "OpenAI-compatible API returned an empty chat response"
        )

    def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ) -> Iterator[str]:
        self._ensure_enabled()
        yielded_content = False
        try:
            for data in _iter_sse_data(
                self._stream_transport(
                    self._chat_url(),
                    self._payload(
                        messages,
                        temperature,
                        max_tokens,
                        stream=True,
                        policy=policy,
                    ),
                    self.config.timeout_seconds,
                    self._headers(),
                )
            ):
                if data == "[DONE]":
                    break
                try:
                    payload = json.loads(data)
                    delta = _extract_api_stream_delta(payload)
                except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
                    raise ModelRuntimeRequestFailed(
                        "OpenAI-compatible API returned an unexpected streaming chat response shape"
                    ) from error
                if delta:
                    yielded_content = True
                    yield delta
        except UnicodeDecodeError as error:
            provider = self.config.provider_display_name.strip() or "API provider"
            raise ModelRuntimeRequestFailed(
                f"{provider} returned a malformed streaming chat chunk"
            ) from error
        if not yielded_content:
            raise ModelRuntimeRequestFailed(
                "OpenAI-compatible API returned an empty streaming chat response"
            )

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
        temperature: float | None,
        max_tokens: int | None,
        *,
        stream: bool,
        policy: ModelCallPolicy | None,
    ) -> dict:
        if policy is None:
            resolved_temperature = (
                DEFAULT_TEMPERATURE if temperature is None else temperature
            )
            resolved_max_tokens = (
                DEFAULT_MAX_TOKENS if max_tokens is None else max_tokens
            )
            resolved_stream = stream
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
        return {
            "model": self.config.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "temperature": resolved_temperature,
            "max_tokens": resolved_max_tokens,
            "stream": resolved_stream,
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
    except urllib.error.HTTPError as error:
        detail = _read_http_error_body(error)
        message = f"llama.cpp chat request failed: HTTP {error.code}"
        if detail:
            message = f"{message}: {detail}"
        raise ModelRuntimeRequestFailed(message, status_code=error.code) from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise ModelRuntimeRequestFailed(f"llama.cpp chat request failed: {error}") from error


def _post_json_with_headers(
    url: str,
    payload: dict,
    timeout: float,
    headers: dict[str, str],
) -> dict:
    try:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise ModelRuntimeRequestFailed(
            f"API chat request failed with HTTP status {error.code}",
            status_code=error.code,
        ) from None
    except urllib.error.URLError as error:
        raise ModelRuntimeRequestFailed("API chat request failed") from None
    except TimeoutError as error:
        raise ModelRuntimeRequestFailed("API chat request timed out") from None
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ModelRuntimeRequestFailed("API chat request returned invalid JSON") from None
    except (ValueError, OSError) as error:
        raise ModelRuntimeRequestFailed("API chat request failed") from None


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


def _post_json_stream_with_headers(
    url: str,
    payload: dict,
    timeout: float,
    headers: dict[str, str],
) -> Iterable[bytes]:
    try:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            yield from response
    except urllib.error.HTTPError as error:
        raise ModelRuntimeRequestFailed(
            f"API streaming chat request failed with HTTP status {error.code}",
            status_code=error.code,
        ) from None
    except urllib.error.URLError as error:
        raise ModelRuntimeRequestFailed("API streaming chat request failed") from None
    except TimeoutError as error:
        raise ModelRuntimeRequestFailed("API streaming chat request timed out") from None
    except (ValueError, OSError) as error:
        raise ModelRuntimeRequestFailed("API streaming chat request failed") from None


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


def _extract_api_chat_with_tools_response(response: dict) -> ChatWithToolsResponse:
    try:
        message = response["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as error:
        raise ModelRuntimeRequestFailed(
            "OpenAI-compatible API returned an unexpected chat response shape"
        ) from error

    if not isinstance(message, dict):
        raise ModelRuntimeRequestFailed(
            "OpenAI-compatible API returned an unexpected chat response shape"
        )

    content = message.get("content") or ""
    if not isinstance(content, str):
        raise ModelRuntimeRequestFailed(
            "OpenAI-compatible API returned an unexpected chat response shape"
        )

    raw_tool_calls = message.get("tool_calls") or []
    if not isinstance(raw_tool_calls, list):
        raise ModelRuntimeRequestFailed(
            "OpenAI-compatible API returned an unexpected tool call response shape"
        )

    return ChatWithToolsResponse(
        content=content,
        tool_calls=[_extract_api_tool_call(raw) for raw in raw_tool_calls],
    )


def _extract_api_tool_call(raw: Any) -> ModelToolCall:
    if not isinstance(raw, dict):
        raise ModelRuntimeRequestFailed(
            "OpenAI-compatible API returned an unexpected tool call response shape"
        )
    function = raw.get("function")
    if not isinstance(function, dict):
        raise ModelRuntimeRequestFailed(
            "OpenAI-compatible API returned an unexpected tool call response shape"
        )
    call_id = raw.get("id")
    name = function.get("name")
    if not isinstance(call_id, str) or not isinstance(name, str):
        raise ModelRuntimeRequestFailed(
            "OpenAI-compatible API returned an unexpected tool call response shape"
        )
    arguments = function.get("arguments", {})
    if isinstance(arguments, str):
        try:
            parsed_arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError as error:
            raise ModelRuntimeRequestFailed(
                "OpenAI-compatible API returned malformed tool call arguments"
            ) from error
    elif isinstance(arguments, dict):
        parsed_arguments = dict(arguments)
    else:
        raise ModelRuntimeRequestFailed(
            "OpenAI-compatible API returned an unexpected tool call response shape"
        )
    if not isinstance(parsed_arguments, dict):
        raise ModelRuntimeRequestFailed(
            "OpenAI-compatible API returned malformed tool call arguments"
        )
    return ModelToolCall(id=call_id, name=name, arguments=parsed_arguments)


def _extract_api_stream_delta(response: dict) -> str:
    if not isinstance(response, dict):
        raise ModelRuntimeRequestFailed(
            "OpenAI-compatible API returned an unexpected streaming chat response shape"
        )
    try:
        choice = response["choices"][0]
    except (KeyError, IndexError, TypeError) as error:
        raise ModelRuntimeRequestFailed(
            "OpenAI-compatible API returned an unexpected streaming chat response shape"
        ) from error
    if not isinstance(choice, dict):
        raise ModelRuntimeRequestFailed(
            "OpenAI-compatible API returned an unexpected streaming chat response shape"
        )
    delta = choice.get("delta", {})
    if not isinstance(delta, dict):
        raise ModelRuntimeRequestFailed(
            "OpenAI-compatible API returned an unexpected streaming chat response shape"
        )
    content = delta.get("content", "")
    if not isinstance(content, str):
        raise ModelRuntimeRequestFailed(
            "OpenAI-compatible API returned an unexpected streaming chat response shape"
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

