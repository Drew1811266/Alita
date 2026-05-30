from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from typing import Any

from agent_service.harness_errors import HarnessError
from agent_service.tool_registry import ToolManifestSpec


ToolAdapterKey = tuple[str, str]
ToolRuntime = Callable[[Any], Any]


class ToolRuntimeLoader:
    def __init__(
        self,
        *,
        adapters: Mapping[ToolAdapterKey, ToolRuntime] | None = None,
    ) -> None:
        self.adapters = dict(adapters or {})

    def run(self, manifest: ToolManifestSpec, invocation: Any) -> Any:
        runtime = self._runtime_for(manifest, invocation)
        return runtime(invocation)

    def _runtime_for(self, manifest: ToolManifestSpec, invocation: Any) -> ToolRuntime:
        if manifest.entrypoint and ":" in manifest.entrypoint:
            return _load_python_function_entrypoint(manifest.entrypoint)

        adapter_key = (manifest.tool_id, str(invocation.operation))
        adapter = self.adapters.get(adapter_key)
        if adapter is not None:
            return adapter

        raise HarnessError(
            "unsupported_tool",
            f"unsupported tool operation: {manifest.tool_id} {invocation.operation}",
        )


def _load_python_function_entrypoint(entrypoint: str) -> ToolRuntime:
    module_name, function_name = entrypoint.split(":", 1)
    if not module_name or not function_name:
        raise HarnessError(
            "unsupported_tool",
            f"invalid tool entrypoint: {entrypoint}",
        )
    try:
        module = importlib.import_module(module_name)
        runtime = getattr(module, function_name)
    except (ImportError, AttributeError) as error:
        raise HarnessError(
            "unsupported_tool",
            f"cannot load tool entrypoint: {entrypoint}",
        ) from error
    if not callable(runtime):
        raise HarnessError(
            "unsupported_tool",
            f"tool entrypoint is not callable: {entrypoint}",
        )
    return runtime
