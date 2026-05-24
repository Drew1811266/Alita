from __future__ import annotations

import pytest

from agent_service.model_client import (
    AgentModelClientConfig,
    ChatMessage,
    LlamaCppModelClient,
    ModelClientConfig,
    ModelRuntimeDisabled,
    ModelRuntimeRequestFailed,
    OpenAICompatibleModelClient,
    create_model_client,
)


def test_default_model_config_is_disabled_without_model_path() -> None:
    config = ModelClientConfig()

    assert not config.enabled
    assert config.base_url == "http://127.0.0.1:8766"
    assert config.model == "local-llama-cpp"


def test_model_config_uses_alita_env(monkeypatch) -> None:
    monkeypatch.setenv("ALITA_LLAMA_MODEL_PATH", "D:\\Alita\\model.gguf")
    monkeypatch.setenv("ALITA_LLAMA_BASE_URL", "http://127.0.0.1:8766/")
    monkeypatch.setenv("ALITA_LLAMA_MODEL_NAME", "alita-model")

    alita_config = ModelClientConfig.from_env()

    assert alita_config.enabled
    assert alita_config.base_url == "http://127.0.0.1:8766"
    assert alita_config.model == "alita-model"


def test_model_config_ignores_non_alita_env(monkeypatch) -> None:
    model_path_env = "BOO" + "OOK_LLAMA_MODEL_PATH"
    base_url_env = "BOO" + "OOK_LLAMA_BASE_URL"
    model_name_env = "BOO" + "OOK_LLAMA_MODEL_NAME"
    monkeypatch.delenv("ALITA_LLAMA_MODEL_PATH", raising=False)
    monkeypatch.delenv("ALITA_LLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("ALITA_LLAMA_MODEL_NAME", raising=False)
    monkeypatch.setenv(model_path_env, "D:\\Legacy\\model.gguf")
    monkeypatch.setenv(base_url_env, "http://127.0.0.1:9000")
    monkeypatch.setenv(model_name_env, "legacy-model")

    config = ModelClientConfig.from_env()

    assert not config.enabled
    assert config.base_url == "http://127.0.0.1:8766"
    assert config.model == "local-llama-cpp"


def test_disabled_model_client_rejects_chat_calls() -> None:
    client = LlamaCppModelClient(ModelClientConfig())

    with pytest.raises(ModelRuntimeDisabled):
        client.chat([ChatMessage(role="user", content="你好")])


def test_llama_client_posts_openai_compatible_chat_request() -> None:
    calls: list[tuple[str, dict, float]] = []

    def transport(url: str, payload: dict, timeout: float) -> dict:
        calls.append((url, payload, timeout))
        return {
            "choices": [
                {
                    "message": {
                        "content": "本地模型回复",
                    }
                }
            ]
        }

    config = ModelClientConfig(
        enabled=True,
        base_url="http://127.0.0.1:8766",
        model="local-llama-cpp",
        timeout_seconds=3.0,
    )
    client = LlamaCppModelClient(config, transport=transport)

    result = client.chat(
        [
            ChatMessage(role="system", content="你是助手"),
            ChatMessage(role="user", content="总结文档"),
        ],
        temperature=0.2,
    )

    assert result == "本地模型回复"
    assert calls == [
        (
            "http://127.0.0.1:8766/v1/chat/completions",
            {
                "model": "local-llama-cpp",
                "messages": [
                    {"role": "system", "content": "你是助手"},
                    {"role": "user", "content": "总结文档"},
                ],
                "temperature": 0.2,
                "max_tokens": 1024,
                "stream": False,
            },
            3.0,
        )
    ]


def test_llama_client_allows_overriding_max_tokens() -> None:
    calls: list[tuple[str, dict, float]] = []

    def transport(url: str, payload: dict, timeout: float) -> dict:
        calls.append((url, payload, timeout))
        return {"choices": [{"message": {"content": "ok"}}]}

    client = LlamaCppModelClient(
        ModelClientConfig(enabled=True),
        transport=transport,
    )

    assert client.chat([ChatMessage(role="user", content="hello")], max_tokens=2048) == "ok"
    assert calls[0][1]["max_tokens"] == 2048


def test_llama_client_retries_when_reasoning_output_exhausts_token_budget() -> None:
    calls: list[tuple[str, dict, float]] = []

    def transport(url: str, payload: dict, timeout: float) -> dict:
        calls.append((url, payload, timeout))
        if len(calls) == 1:
            return {
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {
                            "content": "",
                            "reasoning_content": "still thinking",
                        },
                    }
                ]
            }
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": "最终正文",
                    },
                }
            ]
        }

    client = LlamaCppModelClient(
        ModelClientConfig(enabled=True),
        transport=transport,
    )

    assert client.chat([ChatMessage(role="user", content="hello")], max_tokens=256) == "最终正文"
    assert calls[0][1]["max_tokens"] == 256
    assert calls[1][1]["max_tokens"] == 4096


def test_llama_client_rejects_empty_chat_content() -> None:
    def transport(url: str, payload: dict, timeout: float) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": "still thinking",
                    }
                }
            ]
        }

    client = LlamaCppModelClient(
        ModelClientConfig(enabled=True),
        transport=transport,
    )

    with pytest.raises(ModelRuntimeRequestFailed):
        client.chat([ChatMessage(role="user", content="hello")])


def test_llama_client_streams_openai_compatible_chat_chunks() -> None:
    calls: list[tuple[str, dict, float]] = []

    def stream_transport(url: str, payload: dict, timeout: float):
        calls.append((url, payload, timeout))
        return [
            b'data: {"choices":[{"delta":{"reasoning_content":"thinking"}}]}\n\n',
            'data: {"choices":[{"delta":{"content":"\\u4f60"}}]}\n\n'.encode("utf-8"),
            'data: {"choices":[{"delta":{"content":"\\u597d"}}]}\n\n'.encode("utf-8"),
            b"data: [DONE]\n\n",
        ]

    client = LlamaCppModelClient(
        ModelClientConfig(
            enabled=True,
            base_url="http://127.0.0.1:8766",
            model="local-llama-cpp",
            timeout_seconds=3.0,
        ),
        stream_transport=stream_transport,
    )

    chunks = list(client.stream_chat([ChatMessage(role="user", content="你好")]))

    assert chunks == ["你", "好"]
    assert calls == [
        (
            "http://127.0.0.1:8766/v1/chat/completions",
            {
                "model": "local-llama-cpp",
                "messages": [{"role": "user", "content": "你好"}],
                "temperature": 0.2,
                "max_tokens": 1024,
                "stream": True,
            },
            3.0,
        )
    ]


def test_openai_compatible_client_posts_chat_request_with_authorization() -> None:
    calls: list[tuple[str, dict, float, dict[str, str]]] = []

    def transport(url: str, payload: dict, timeout: float, headers: dict[str, str]) -> dict:
        calls.append((url, payload, timeout, headers))
        return {"choices": [{"message": {"content": "api reply"}}]}

    client = OpenAICompatibleModelClient(
        AgentModelClientConfig(
            mode="api",
            enabled=True,
            base_url="https://api.openai.com/v1",
            model="gpt-4.1",
            api_key="sk-test",
            provider_display_name="OpenAI",
        ),
        transport=transport,
    )

    result = client.chat([ChatMessage(role="user", content="hello")])

    assert result == "api reply"
    assert calls == [
        (
            "https://api.openai.com/v1/chat/completions",
            {
                "model": "gpt-4.1",
                "messages": [{"role": "user", "content": "hello"}],
                "temperature": 0.2,
                "max_tokens": 1024,
                "stream": False,
            },
            60.0,
            {"Authorization": "Bearer sk-test", "Content-Type": "application/json"},
        )
    ]


def test_openai_compatible_client_streams_chat_chunks() -> None:
    def stream_transport(url: str, payload: dict, timeout: float, headers: dict[str, str]):
        return [
            b'data: {"choices":[{"delta":{"content":"A"}}]}\n\n',
            'data: {"choices":[{"delta":{"content":"B"}}]}\n\n',
            b"data: [DONE]\n\n",
        ]

    client = OpenAICompatibleModelClient(
        AgentModelClientConfig(
            mode="api",
            enabled=True,
            base_url="https://api.deepseek.com",
            model="deepseek-chat",
            api_key="sk-test",
            provider_display_name="DeepSeek",
        ),
        stream_transport=stream_transport,
    )

    assert list(client.stream_chat([ChatMessage(role="user", content="hello")])) == ["A", "B"]


def test_openai_compatible_client_wraps_malformed_stream_bytes() -> None:
    def stream_transport(url: str, payload: dict, timeout: float, headers: dict[str, str]):
        return [b"\xff"]

    client = OpenAICompatibleModelClient(
        AgentModelClientConfig(
            mode="api",
            enabled=True,
            base_url="https://api.openai.com/v1",
            model="gpt-4.1",
            api_key="sk-test",
            provider_display_name="OpenAI",
        ),
        stream_transport=stream_transport,
    )

    with pytest.raises(
        ModelRuntimeRequestFailed,
        match="OpenAI returned a malformed streaming chat chunk",
    ):
        list(client.stream_chat([ChatMessage(role="user", content="hello")]))


def test_openai_compatible_client_rejects_malformed_stream_json() -> None:
    def stream_transport(url: str, payload: dict, timeout: float, headers: dict[str, str]):
        return [b"data: {not-json}\n\n"]

    client = OpenAICompatibleModelClient(
        AgentModelClientConfig(
            mode="api",
            enabled=True,
            base_url="https://api.openai.com/v1",
            model="gpt-4.1",
            api_key="sk-test",
            provider_display_name="OpenAI",
        ),
        stream_transport=stream_transport,
    )

    with pytest.raises(
        ModelRuntimeRequestFailed,
        match="OpenAI-compatible API returned an unexpected streaming chat response shape",
    ):
        list(client.stream_chat([ChatMessage(role="user", content="hello")]))


def test_openai_compatible_client_rejects_non_object_stream_delta() -> None:
    def stream_transport(url: str, payload: dict, timeout: float, headers: dict[str, str]):
        return ['data: {"choices":[{"delta":null}]}\n\n']

    client = OpenAICompatibleModelClient(
        AgentModelClientConfig(
            mode="api",
            enabled=True,
            base_url="https://api.openai.com/v1",
            model="gpt-4.1",
            api_key="sk-test",
            provider_display_name="OpenAI",
        ),
        stream_transport=stream_transport,
    )

    with pytest.raises(
        ModelRuntimeRequestFailed,
        match="OpenAI-compatible API returned an unexpected streaming chat response shape",
    ):
        list(client.stream_chat([ChatMessage(role="user", content="hello")]))


def test_openai_compatible_client_wraps_invalid_chat_url() -> None:
    client = OpenAICompatibleModelClient(
        AgentModelClientConfig(
            mode="api",
            enabled=True,
            base_url="not a url",
            model="gpt-4.1",
            api_key="sk-test",
            provider_display_name="OpenAI",
            timeout_seconds=0.01,
        )
    )

    with pytest.raises(ModelRuntimeRequestFailed, match="API chat request failed") as error:
        client.chat([ChatMessage(role="user", content="hello")])

    assert "sk-test" not in str(error.value)
    assert "Authorization" not in str(error.value)


def test_openai_compatible_client_wraps_invalid_stream_url() -> None:
    client = OpenAICompatibleModelClient(
        AgentModelClientConfig(
            mode="api",
            enabled=True,
            base_url="not a url",
            model="gpt-4.1",
            api_key="sk-test",
            provider_display_name="OpenAI",
            timeout_seconds=0.01,
        )
    )

    with pytest.raises(
        ModelRuntimeRequestFailed,
        match="API streaming chat request failed",
    ) as error:
        list(client.stream_chat([ChatMessage(role="user", content="hello")]))

    assert "sk-test" not in str(error.value)
    assert "Authorization" not in str(error.value)


def test_openai_compatible_client_suppresses_secret_chat_transport_cause() -> None:
    secret = "sk-secret-chat"
    client = OpenAICompatibleModelClient(
        AgentModelClientConfig(
            mode="api",
            enabled=True,
            base_url="http://127.0.0.1:1",
            model="gpt-4.1",
            api_key=f"{secret}\r\nX-Injected: leaked",
            provider_display_name="OpenAI",
            timeout_seconds=0.01,
        )
    )

    with pytest.raises(ModelRuntimeRequestFailed) as error:
        client.chat([ChatMessage(role="user", content="hello")])

    assert secret not in str(error.value)
    assert error.value.__cause__ is None or secret not in str(error.value.__cause__)


def test_openai_compatible_client_suppresses_secret_stream_transport_cause() -> None:
    secret = "sk-secret-stream"
    client = OpenAICompatibleModelClient(
        AgentModelClientConfig(
            mode="api",
            enabled=True,
            base_url="http://127.0.0.1:1",
            model="gpt-4.1",
            api_key=f"{secret}\r\nX-Injected: leaked",
            provider_display_name="OpenAI",
            timeout_seconds=0.01,
        )
    )

    with pytest.raises(ModelRuntimeRequestFailed) as error:
        list(client.stream_chat([ChatMessage(role="user", content="hello")]))

    assert secret not in str(error.value)
    assert error.value.__cause__ is None or secret not in str(error.value.__cause__)


def test_openai_compatible_client_rejects_done_only_stream() -> None:
    def stream_transport(url: str, payload: dict, timeout: float, headers: dict[str, str]):
        return [b"data: [DONE]\n\n"]

    client = OpenAICompatibleModelClient(
        AgentModelClientConfig(
            mode="api",
            enabled=True,
            base_url="https://api.openai.com/v1",
            model="gpt-4.1",
            api_key="sk-test",
            provider_display_name="OpenAI",
        ),
        stream_transport=stream_transport,
    )

    with pytest.raises(
        ModelRuntimeRequestFailed,
        match="OpenAI-compatible API returned an empty streaming chat response",
    ):
        list(client.stream_chat([ChatMessage(role="user", content="hello")]))


def test_openai_compatible_client_rejects_stream_without_data_lines() -> None:
    def stream_transport(url: str, payload: dict, timeout: float, headers: dict[str, str]):
        return [b": keepalive\n\n", b"event: ping\n\n"]

    client = OpenAICompatibleModelClient(
        AgentModelClientConfig(
            mode="api",
            enabled=True,
            base_url="https://api.openai.com/v1",
            model="gpt-4.1",
            api_key="sk-test",
            provider_display_name="OpenAI",
        ),
        stream_transport=stream_transport,
    )

    with pytest.raises(
        ModelRuntimeRequestFailed,
        match="OpenAI-compatible API returned an empty streaming chat response",
    ):
        list(client.stream_chat([ChatMessage(role="user", content="hello")]))


def test_openai_compatible_client_rejects_missing_api_key() -> None:
    client = OpenAICompatibleModelClient(
        AgentModelClientConfig(
            mode="api",
            enabled=True,
            base_url="https://api.openai.com/v1",
            model="gpt-4.1",
            api_key=None,
            provider_display_name="OpenAI",
        )
    )

    with pytest.raises(ModelRuntimeDisabled, match="API key is not configured"):
        client.chat([ChatMessage(role="user", content="hello")])


def test_openai_compatible_client_rejects_missing_api_base_url() -> None:
    client = OpenAICompatibleModelClient(
        AgentModelClientConfig(
            mode="api",
            enabled=True,
            base_url="",
            model="gpt-4.1",
            api_key="sk-test",
            provider_display_name="OpenAI",
        )
    )

    with pytest.raises(ModelRuntimeDisabled, match="API base URL is not configured"):
        client.chat([ChatMessage(role="user", content="hello")])


def test_openai_compatible_client_rejects_missing_api_model() -> None:
    client = OpenAICompatibleModelClient(
        AgentModelClientConfig(
            mode="api",
            enabled=True,
            base_url="https://api.openai.com/v1",
            model="",
            api_key="sk-test",
            provider_display_name="OpenAI",
        )
    )

    with pytest.raises(ModelRuntimeDisabled, match="API model is not configured"):
        client.chat([ChatMessage(role="user", content="hello")])


def test_create_model_client_returns_api_client_for_api_config() -> None:
    client = create_model_client(
        AgentModelClientConfig(
            mode="api",
            enabled=True,
            base_url="https://api.openai.com/v1",
            model="gpt-4.1",
            api_key="sk-test",
            provider_display_name="OpenAI",
        )
    )

    assert isinstance(client, OpenAICompatibleModelClient)
