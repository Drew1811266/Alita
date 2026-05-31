from __future__ import annotations

from itertools import count
import json
from queue import Empty, Queue
import subprocess
from threading import Thread
import time
from typing import Any

from agent_service.tool_providers.mcp import McpProviderConfig, McpToolSpec


class UnavailableMcpClient:
    def __init__(self, *, error_code: str, message: str) -> None:
        self.error_code = error_code
        self.message = message

    def list_tools(self) -> list[McpToolSpec]:
        return []

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        return {
            "isError": True,
            "content": [{"type": "text", "text": self.message}],
        }

    def health(self) -> dict[str, Any]:
        return {
            "ok": False,
            "errorCode": self.error_code,
            "message": self.message,
        }

    def stop(self) -> None:
        return None


class StdioMcpClient:
    def __init__(self, config: McpProviderConfig) -> None:
        self.config = config
        self.timeout_seconds = config.timeout_seconds
        self.process: subprocess.Popen[str] | None = None
        self._responses: Queue[dict[str, Any]] = Queue()
        self._request_ids = count(1)
        self._reader: Thread | None = None
        self._initialized = False
        self._last_error: str | None = None

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        if not self.config.command:
            raise RuntimeError("MCP stdio command is required")
        self.process = subprocess.Popen(
            self.config.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            shell=True,
        )
        self._reader = Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "alita", "version": "0.35.1"},
            },
        )
        self._initialized = True

    def list_tools(self) -> list[McpToolSpec]:
        self.start()
        result = self._request("tools/list", {})
        return [
            McpToolSpec(
                name=str(tool.get("name") or ""),
                description=str(tool.get("description") or ""),
                input_schema=dict(tool.get("inputSchema") or {}),
                output_schema=(
                    dict(tool.get("outputSchema"))
                    if isinstance(tool.get("outputSchema"), dict)
                    else None
                ),
            )
            for tool in result.get("tools") or []
            if isinstance(tool, dict)
        ]

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        self.start()
        return self._request(
            "tools/call",
            {"name": name, "arguments": dict(arguments)},
            timeout_seconds=(
                timeout_ms / 1000 if timeout_ms is not None else self.timeout_seconds
            ),
        )

    def health(self) -> dict[str, Any]:
        process_ok = self.process is not None and self.process.poll() is None
        return {
            "ok": bool(process_ok and self._initialized),
            "transport": "stdio",
            "errorCode": None if process_ok else self._last_error,
        }

    def stop(self) -> None:
        process = self.process
        self.process = None
        self._initialized = False
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1.0)

    def _read_stdout(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                self._responses.put(payload)

    def _request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        process = self.process
        if process is None or process.stdin is None:
            raise RuntimeError("MCP stdio process is not running")
        request_id = next(self._request_ids)
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        process.stdin.flush()

        deadline = time.monotonic() + (timeout_seconds or self.timeout_seconds)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._last_error = "timeout"
                raise TimeoutError(f"MCP stdio request timed out: {method}")
            try:
                response = self._responses.get(timeout=remaining)
            except Empty as error:
                self._last_error = "timeout"
                raise TimeoutError(f"MCP stdio request timed out: {method}") from error
            if response.get("id") != request_id:
                continue
            if response.get("error"):
                self._last_error = "json_rpc_error"
                error_payload = dict(response.get("error") or {})
                raise RuntimeError(str(error_payload.get("message") or "MCP error"))
            return dict(response.get("result") or {})


def create_mcp_client(config: McpProviderConfig):
    if config.transport == "stdio" and not config.command:
        return UnavailableMcpClient(
            error_code="missing_command",
            message="MCP stdio command is required",
        )
    if config.transport == "http" and not config.url:
        return UnavailableMcpClient(
            error_code="missing_url",
            message="MCP HTTP URL is required",
        )
    if config.transport == "stdio":
        return StdioMcpClient(config)
    return UnavailableMcpClient(
        error_code="unsupported_transport_runtime",
        message="Real MCP client runtime is not enabled yet",
    )
