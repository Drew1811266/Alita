from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from agent_service.model_client import ChatMessage, LlamaCppModelClient, ModelClientConfig


class FakeOpenAIHTTPServer(ThreadingHTTPServer):
    request_bodies: list[dict[str, Any]]


class FakeOpenAIChatHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        request_body = json.loads(body.decode("utf-8"))
        self.server.request_bodies.append(request_body)  # type: ignore[attr-defined]

        if request_body.get("stream") is True:
            self._send_stream_response()
            return

        self._send_json_response(
            {
                "choices": [
                    {
                        "message": {
                            "content": "fake server reply",
                        }
                    }
                ]
            }
        )

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json_response(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_stream_response(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        for content in ("hel", "lo"):
            chunk = {
                "choices": [
                    {
                        "delta": {
                            "content": content,
                        }
                    }
                ]
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
            self.wfile.flush()

        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def _start_fake_openai_server() -> tuple[FakeOpenAIHTTPServer, threading.Thread]:
    server = FakeOpenAIHTTPServer(("127.0.0.1", 0), FakeOpenAIChatHandler)
    server.request_bodies = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _client_for_server(server: FakeOpenAIHTTPServer) -> LlamaCppModelClient:
    return LlamaCppModelClient(
        ModelClientConfig(
            enabled=True,
            base_url=f"http://127.0.0.1:{server.server_port}",
            model="fake-model",
            timeout_seconds=3.0,
        )
    )


def test_llama_client_works_against_fake_openai_http_server() -> None:
    server, thread = _start_fake_openai_server()
    try:
        client = _client_for_server(server)

        response = client.chat(
            [
                ChatMessage(role="system", content="You are concise."),
                ChatMessage(role="user", content="Say hello."),
            ],
            temperature=0.4,
            max_tokens=42,
        )

        assert response == "fake server reply"
        assert server.request_bodies == [
            {
                "model": "fake-model",
                "messages": [
                    {"role": "system", "content": "You are concise."},
                    {"role": "user", "content": "Say hello."},
                ],
                "temperature": 0.4,
                "max_tokens": 42,
                "stream": False,
            }
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_llama_client_streams_against_fake_openai_http_server() -> None:
    server, thread = _start_fake_openai_server()
    try:
        client = _client_for_server(server)

        chunks = list(
            client.stream_chat(
                [ChatMessage(role="user", content="Stream hello.")],
                temperature=0.1,
                max_tokens=7,
            )
        )

        assert chunks == ["hel", "lo"]
        assert server.request_bodies == [
            {
                "model": "fake-model",
                "messages": [{"role": "user", "content": "Stream hello."}],
                "temperature": 0.1,
                "max_tokens": 7,
                "stream": True,
            }
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
