# Semantic Router Agent Judgment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace natural-language keyword routing with an LLM Semantic Router while keeping deterministic checks limited to product state, capability validation, and schema safety.

**Architecture:** Add a focused `semantic_router.py` module that builds a compact routing envelope, calls the model for schema-valid JSON, repairs malformed JSON once, and returns a typed route decision without keyword fallback. Adapt `router_v2.py`, `AgentRuntimeEngine`, and legacy graph dispatch to consume semantic decisions while preserving existing public event shapes. Add a small Capability Gate so model route decisions are checked against tool and runtime availability before Deep Agent planning or execution.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, existing `AgentRunState`, `UserMessage`, `RunGraph`, `ModelClient`, `AgentRuntimeEngine`, and existing FastAPI sidecar endpoints.

---

## File Structure

Create:

- `python/agent_service/semantic_router.py`
  - Owns Semantic Router data models, prompt construction, model call, JSON parsing, repair retry, and no-model/no-schema failure decisions.
- `python/agent_service/capability_gate.py`
  - Owns non-language capability checks for route decisions: tool availability, required attachments, web access, and file output availability.
- `python/tests/test_semantic_router.py`
  - Contract tests for schema, model calls, malformed JSON repair, model failure, no keyword fallback, language preservation, and context-sensitive routing.
- `python/tests/test_capability_gate.py`
  - Capability checks that block unavailable tools without changing natural-language intent.

Modify:

- `python/agent_service/router_v2.py`
  - Keep `RouterV2Decision` as compatibility payload.
  - Change `route_message()` to use `semantic_router.route_semantically()` as the default route source.
  - Keep `deterministic_route()` only as a legacy compatibility helper for explicitly named tests and migration references.
  - Remove keyword fallback from the main `route_message()` path.
- `python/agent_service/agent_runtime_engine.py`
  - Replace `_run_state_for_pre_deep_response()` deterministic route call with semantic route + capability gate.
  - Preserve State Guard for empty input, missing required attachment when state already proves it, pending choice, and model/runtime availability.
  - Route `response_only`, `local_answer`, `simple_tool_answer`, and `web_answer` to response-only paths.
  - Route `deep_planning` and `research_planning` to Deep Agent.
- `python/agent_service/graph.py`
  - Stop using `classify_route()` as a natural-language fallback in runtime paths.
  - Consume `RouterV2Decision` supplied by `AgentRunState` whenever possible.
  - Keep legacy direct graph APIs compatible by requiring a semantic model decision or returning a structured clarification.
- `python/agent_service/agent_run_state.py`
  - Add optional semantic router context fields only if needed by RuntimeEngine.
- `python/tests/test_router_v2.py`
  - Replace deterministic parity tests with compatibility tests and no-keyword-fallback tests.
- `python/tests/test_agent_runtime_engine_deep_agent.py`
  - Update greeting and simple-answer tests so fake Semantic Router decisions drive dispatch.
  - Add tests proving `classify_route()` is not called for natural-language routing.
- `python/tests/test_graph.py`
  - Update route tests to inject semantic model decisions.
- `python/tests/test_app.py`
  - Add API-level regression for Chinese greeting routed through semantic model.
- `python/tests/test_human_task_smoke.py`
  - Add natural-language variants to prove no keyword dependence.
- `README.md`
  - Update Agent routing section to describe Semantic Router as default.
- `docs/agent-development-optimization-2026-06-07-human-agent-test.md`
  - Mark keyword route replacement as planned implementation scope.

---

### Task 1: Add Semantic Router Data Contract

**Files:**
- Create: `python/agent_service/semantic_router.py`
- Test: `python/tests/test_semantic_router.py`

- [ ] **Step 1: Write the failing schema contract tests**

Add this file:

```python
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_service.schemas import UserMessage
from agent_service.semantic_router import (
    SemanticRoute,
    SemanticRouteDecision,
    build_semantic_router_messages,
    parse_semantic_route_response,
)


def test_semantic_route_decision_payload_is_frontend_safe() -> None:
    decision = SemanticRouteDecision(
        route="response_only",
        intent="greeting",
        complexity="simple",
        requires_graph=False,
        requires_tools=False,
        requires_web=False,
        requires_files=False,
        requires_clarification=False,
        language="zh",
        confidence=0.97,
        context_used=["current_message"],
        missing_inputs=[],
        required_capabilities=[],
        tool_candidates=[],
        reason="用户是在问候。",
    )

    assert decision.to_payload() == {
        "route": "response_only",
        "intent": "greeting",
        "complexity": "simple",
        "requiresGraph": False,
        "requiresTools": False,
        "requiresWeb": False,
        "requiresFiles": False,
        "requiresClarification": False,
        "language": "zh",
        "confidence": 0.97,
        "contextUsed": ["current_message"],
        "missingInputs": [],
        "requiredCapabilities": [],
        "toolCandidates": [],
        "reason": "用户是在问候。",
        "clarificationPrompt": None,
    }


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_semantic_route_decision_rejects_invalid_confidence(confidence: float) -> None:
    with pytest.raises(ValidationError):
        SemanticRouteDecision(
            route="response_only",
            intent="greeting",
            complexity="simple",
            requires_graph=False,
            requires_tools=False,
            requires_web=False,
            requires_files=False,
            requires_clarification=False,
            language="zh",
            confidence=confidence,
            reason="invalid",
        )


def test_parse_semantic_route_response_accepts_camel_and_snake_case() -> None:
    response = json.dumps(
        {
            "route": "deep_planning",
            "intent": "document_report",
            "complexity": "multi_step",
            "requiresGraph": True,
            "requiresTools": True,
            "requiresWeb": False,
            "requiresFiles": True,
            "requiresClarification": False,
            "language": "zh",
            "confidence": 0.91,
            "contextUsed": ["current_message", "attachments"],
            "missingInputs": [],
            "requiredCapabilities": ["document.read", "output.pdf"],
            "toolCandidates": ["document.read_write", "output.pdf"],
            "reason": "用户要求处理附件并导出报告。",
        }
    )

    decision = parse_semantic_route_response(response)

    assert decision.route == "deep_planning"
    assert decision.requires_graph is True
    assert decision.required_capabilities == ["document.read", "output.pdf"]
    assert decision.context_used == ["current_message", "attachments"]


def test_router_prompt_does_not_include_raw_local_paths() -> None:
    local_path = r"D:\Software Project\Alita\python\agent_service\graph.py"
    message = UserMessage(task_id="semantic-scrub", content=f"请看看 {local_path}")

    prompt_dump = repr(build_semantic_router_messages(message))

    assert local_path not in prompt_dump
    assert "Software Project\\Alita" not in prompt_dump
    assert "agent_service" not in prompt_dump
```

- [ ] **Step 2: Run the schema tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python\tests\test_semantic_router.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_service.semantic_router'`.

- [ ] **Step 3: Implement the semantic router data contract**

Create `python/agent_service/semantic_router.py`:

```python
from __future__ import annotations

import json
import re
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from agent_service.model_client import ChatMessage as ModelChatMessage
from agent_service.model_policy import ModelCallPolicy
from agent_service.schemas import RunGraph, UserMessage


SemanticRoute = Literal[
    "response_only",
    "local_answer",
    "simple_tool_answer",
    "web_answer",
    "graph_feedback",
    "clarification_required",
    "deep_planning",
    "research_planning",
]

SemanticComplexity = Literal["simple", "bounded_tool", "multi_step", "research"]

LOCAL_PATH_PATTERN = re.compile(
    r"(?ix)"
    r"(?:"
    r"\b[a-z]:[\\/](?:[^\\/:\r\n,;<>\"|?*]+[\\/])+[^\\/\s:\r\n,;<>\"|?*]+"
    r"|"
    r"/(?:[^/\r\n,;<>\"|?*]+/){2,}[^/\s\r\n,;<>\"|?*]+"
    r")"
)


class SemanticRouterModelClient(Protocol):
    def chat(
        self,
        messages: list[ModelChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ) -> str:
        raise NotImplementedError


class SemanticRouteDecision(BaseModel):
    route: SemanticRoute
    intent: str
    complexity: SemanticComplexity
    requires_graph: bool = Field(alias="requiresGraph")
    requires_tools: bool = Field(alias="requiresTools")
    requires_web: bool = Field(alias="requiresWeb")
    requires_files: bool = Field(alias="requiresFiles")
    requires_clarification: bool = Field(alias="requiresClarification")
    language: str
    confidence: float = Field(ge=0.0, le=1.0)
    context_used: list[str] = Field(default_factory=list, alias="contextUsed")
    missing_inputs: list[str] = Field(default_factory=list, alias="missingInputs")
    required_capabilities: list[str] = Field(
        default_factory=list,
        alias="requiredCapabilities",
    )
    tool_candidates: list[str] = Field(default_factory=list, alias="toolCandidates")
    reason: str
    clarification_prompt: str | None = Field(
        default=None,
        alias="clarificationPrompt",
    )

    model_config = {"populate_by_name": True}

    def to_payload(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "intent": _safe_text(self.intent),
            "complexity": self.complexity,
            "requiresGraph": self.requires_graph,
            "requiresTools": self.requires_tools,
            "requiresWeb": self.requires_web,
            "requiresFiles": self.requires_files,
            "requiresClarification": self.requires_clarification,
            "language": _safe_text(self.language),
            "confidence": self.confidence,
            "contextUsed": [_safe_text(item) for item in self.context_used],
            "missingInputs": [_safe_text(item) for item in self.missing_inputs],
            "requiredCapabilities": [
                _safe_text(item) for item in self.required_capabilities
            ],
            "toolCandidates": [_safe_text(item) for item in self.tool_candidates],
            "reason": _safe_text(self.reason),
            "clarificationPrompt": (
                _safe_text(self.clarification_prompt)
                if self.clarification_prompt is not None
                else None
            ),
        }


def parse_semantic_route_response(response: str) -> SemanticRouteDecision:
    raw = json.loads(_extract_json_object(response))
    if not isinstance(raw, dict):
        raise ValueError("semantic router response must be a JSON object")
    return SemanticRouteDecision.model_validate(_scrub_payload(raw))


def build_semantic_router_messages(
    message: UserMessage,
    *,
    current_graph: RunGraph | None = None,
    pending_choice: dict[str, Any] | None = None,
    available_capabilities: list[str] | None = None,
) -> list[ModelChatMessage]:
    envelope = {
        "currentMessage": _safe_text(message.content.strip()),
        "conversationHistory": [
            {
                "role": turn.role,
                "content": _safe_text(turn.content),
            }
            for turn in message.conversation_history[-5:]
        ],
        "attachments": [
            {
                "name": _safe_text(attachment.name),
                "mimeType": attachment.mime_type,
                "sizeBytes": attachment.size_bytes,
            }
            for attachment in message.attachments
        ],
        "currentGraph": _graph_summary(current_graph),
        "pendingChoice": _pending_choice_summary(pending_choice),
        "availableCapabilities": list(available_capabilities or []),
    }
    return [
        ModelChatMessage(
            role="system",
            content=(
                "You are Alita's Semantic Router. Decide the user's route from "
                "meaning and runtime context, not keywords. Return only JSON with "
                "route, intent, complexity, requiresGraph, requiresTools, "
                "requiresWeb, requiresFiles, requiresClarification, language, "
                "confidence, contextUsed, missingInputs, requiredCapabilities, "
                "toolCandidates, reason, clarificationPrompt. Use the user's "
                "language for reason and clarificationPrompt. Never include local paths."
            ),
        ),
        ModelChatMessage(role="user", content=json.dumps(envelope, ensure_ascii=False)),
    ]


def _graph_summary(current_graph: RunGraph | None) -> dict[str, Any] | None:
    if current_graph is None:
        return None
    return {
        "graphId": current_graph.graphId,
        "nodeCount": len(current_graph.nodes),
        "edgeCount": len(current_graph.edges),
        "nodes": [
            {
                "nodeId": node.nodeId,
                "nodeType": node.nodeType,
                "displayName": _safe_text(node.displayName),
                "status": node.status,
            }
            for node in current_graph.nodes[:12]
        ],
    }


def _pending_choice_summary(pending_choice: dict[str, Any] | None) -> dict[str, Any] | None:
    if not pending_choice:
        return None
    return {
        "kind": _safe_text(str(pending_choice.get("kind") or "")),
        "runId": _safe_text(str(pending_choice.get("runId") or "")),
        "threadId": _safe_text(str(pending_choice.get("threadId") or "")),
    }


def _extract_json_object(response: str) -> str:
    start = response.find("{")
    end = response.rfind("}")
    if start < 0 or end < start:
        raise ValueError("semantic router response did not contain a JSON object")
    return response[start : end + 1]


def _safe_text(value: str) -> str:
    return LOCAL_PATH_PATTERN.sub("[local_path]", value)


def _scrub_payload(value: Any) -> Any:
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, list):
        return [_scrub_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: _scrub_payload(item) for key, item in value.items()}
    return value
```

- [ ] **Step 4: Run the schema tests and verify they pass**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python\tests\test_semantic_router.py -q
```

Expected: PASS for the schema tests added in Step 1.

- [ ] **Step 5: Commit Task 1**

```powershell
git add python\agent_service\semantic_router.py python\tests\test_semantic_router.py
git commit -m "feat: add semantic router contract"
```

---

### Task 2: Add Model Call, Repair, and No-Keyword Fallback Behavior

**Files:**
- Modify: `python/agent_service/semantic_router.py`
- Test: `python/tests/test_semantic_router.py`

- [ ] **Step 1: Add failing tests for model routing, repair, and model failure**

Append to `python/tests/test_semantic_router.py`:

```python
from agent_service.semantic_router import route_semantically


class FakeSemanticRouterModel:
    def __init__(self, responses: list[str] | None = None, error: Exception | None = None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def chat(self, messages, *, temperature=None, max_tokens=None, policy=None) -> str:
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "policy": policy,
            }
        )
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


def _semantic_response(route: str, confidence: float = 0.95) -> str:
    return json.dumps(
        {
            "route": route,
            "intent": "greeting",
            "complexity": "simple",
            "requiresGraph": False,
            "requiresTools": False,
            "requiresWeb": False,
            "requiresFiles": False,
            "requiresClarification": False,
            "language": "zh",
            "confidence": confidence,
            "contextUsed": ["current_message"],
            "missingInputs": [],
            "requiredCapabilities": [],
            "toolCandidates": [],
            "reason": "用户是在问候。",
        }
    )


def test_route_semantically_uses_model_decision() -> None:
    model = FakeSemanticRouterModel([_semantic_response("response_only")])

    decision = route_semantically(
        UserMessage(task_id="semantic-greeting", content="早上好"),
        model_client=model,
    )

    assert decision.route == "response_only"
    assert decision.language == "zh"
    assert len(model.calls) == 1
    assert model.calls[0]["temperature"] == 0.0
    assert model.calls[0]["max_tokens"] == 2048


def test_route_semantically_repairs_malformed_json_once() -> None:
    model = FakeSemanticRouterModel(
        [
            "not json",
            _semantic_response("response_only"),
        ]
    )

    decision = route_semantically(
        UserMessage(task_id="semantic-repair", content="你好"),
        model_client=model,
    )

    assert decision.route == "response_only"
    assert len(model.calls) == 2
    assert "Repair this invalid Semantic Router response" in model.calls[1]["messages"][0].content


def test_route_semantically_model_failure_returns_clarification_without_keyword_guess() -> None:
    model = FakeSemanticRouterModel(error=TimeoutError("router timed out"))

    decision = route_semantically(
        UserMessage(task_id="semantic-timeout", content="帮我看看这个事情"),
        model_client=model,
    )

    assert decision.route == "clarification_required"
    assert decision.requires_clarification is True
    assert decision.confidence == 0.0
    assert decision.missing_inputs == ["router_decision"]
    assert "我需要确认你的目标" in (decision.clarification_prompt or "")


def test_route_semantically_without_model_returns_clarification_without_keyword_guess() -> None:
    decision = route_semantically(
        UserMessage(task_id="semantic-no-model", content="研究一下这个问题"),
        model_client=None,
    )

    assert decision.route == "clarification_required"
    assert decision.requires_clarification is True
    assert decision.required_capabilities == ["model.semantic_router"]
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python\tests\test_semantic_router.py -q
```

Expected: FAIL with `ImportError` or `AttributeError` for `route_semantically`.

- [ ] **Step 3: Implement model routing and repair**

Add to `python/agent_service/semantic_router.py`:

```python
SEMANTIC_ROUTER_MAX_TOKENS = 2048


def route_semantically(
    message: UserMessage,
    *,
    model_client: SemanticRouterModelClient | None,
    current_graph: RunGraph | None = None,
    pending_choice: dict[str, Any] | None = None,
    available_capabilities: list[str] | None = None,
) -> SemanticRouteDecision:
    if model_client is None:
        return _router_unavailable_decision(
            language=_infer_language(message.content),
            reason="semantic router model unavailable",
        )

    messages = build_semantic_router_messages(
        message,
        current_graph=current_graph,
        pending_choice=pending_choice,
        available_capabilities=available_capabilities,
    )
    try:
        response = model_client.chat(
            messages,
            temperature=0.0,
            max_tokens=SEMANTIC_ROUTER_MAX_TOKENS,
        )
        return parse_semantic_route_response(response)
    except Exception as first_error:
        try:
            repair_response = model_client.chat(
                _repair_messages(str(first_error), response if "response" in locals() else ""),
                temperature=0.0,
                max_tokens=SEMANTIC_ROUTER_MAX_TOKENS,
            )
            return parse_semantic_route_response(repair_response)
        except Exception:
            return _router_unavailable_decision(
                language=_infer_language(message.content),
                reason="semantic router failed",
            )


def _repair_messages(error: str, invalid_response: str) -> list[ModelChatMessage]:
    return [
        ModelChatMessage(
            role="system",
            content=(
                "Repair this invalid Semantic Router response. Return only one "
                "schema-valid JSON object. Do not explain."
            ),
        ),
        ModelChatMessage(
            role="user",
            content=json.dumps(
                {
                    "error": _safe_text(error),
                    "invalidResponse": _safe_text(invalid_response),
                },
                ensure_ascii=False,
            ),
        ),
    ]


def _router_unavailable_decision(*, language: str, reason: str) -> SemanticRouteDecision:
    prompt = (
        "我需要确认你的目标后再继续。请用一句话说明你希望我直接回答，"
        "还是希望我规划并执行一个任务。"
        if language == "zh"
        else "I need to confirm your goal before continuing. Please say whether you want a direct answer or a planned task."
    )
    return SemanticRouteDecision(
        route="clarification_required",
        intent="router_unavailable",
        complexity="simple",
        requiresGraph=False,
        requiresTools=False,
        requiresWeb=False,
        requiresFiles=False,
        requiresClarification=True,
        language=language,
        confidence=0.0,
        contextUsed=["current_message"],
        missingInputs=["router_decision"],
        requiredCapabilities=["model.semantic_router"],
        toolCandidates=[],
        reason=reason,
        clarificationPrompt=prompt,
    )


def _infer_language(content: str) -> str:
    return "zh" if re.search(r"[\u4e00-\u9fff]", content) else "en"
```

- [ ] **Step 4: Run the semantic router tests**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python\tests\test_semantic_router.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```powershell
git add python\agent_service\semantic_router.py python\tests\test_semantic_router.py
git commit -m "feat: route messages with semantic model router"
```

---

### Task 3: Adapt Router V2 Without Keyword Fallback

**Files:**
- Modify: `python/agent_service/router_v2.py`
- Test: `python/tests/test_router_v2.py`

- [ ] **Step 1: Add failing Router V2 tests that forbid `classify_route()` fallback**

Add to `python/tests/test_router_v2.py`:

```python
class FakeRouterModel:
    def __init__(self, response: dict):
        self.response = response
        self.calls = 0

    def chat(self, messages, *, temperature=None, max_tokens=None, policy=None) -> str:
        self.calls += 1
        return json.dumps(self.response)


def _semantic_router_payload(route: str, *, confidence: float = 0.94) -> dict:
    return {
        "route": route,
        "intent": "greeting",
        "complexity": "simple",
        "requiresGraph": False,
        "requiresTools": False,
        "requiresWeb": False,
        "requiresFiles": False,
        "requiresClarification": False,
        "language": "zh",
        "confidence": confidence,
        "contextUsed": ["current_message"],
        "missingInputs": [],
        "requiredCapabilities": [],
        "toolCandidates": [],
        "reason": "用户是在问候。",
    }


def test_route_message_uses_semantic_router_without_structured_router_env(monkeypatch) -> None:
    monkeypatch.delenv(STRUCTURED_ROUTER_ENV, raising=False)
    model = FakeRouterModel(_semantic_router_payload("response_only"))

    decision = route_message(
        UserMessage(task_id="semantic-router-v2", content="你好"),
        model_client=model,
    )

    assert decision.intent == "chat"
    assert decision.source == "model"
    assert decision.structured_route["route"] == "response_only"
    assert model.calls == 1


def test_route_message_does_not_call_classify_route_for_natural_language(monkeypatch) -> None:
    def fail_classify_route(message):
        raise AssertionError("classify_route must not be used by route_message")

    monkeypatch.setattr("agent_service.router_v2.classify_route", fail_classify_route)
    model = FakeRouterModel(_semantic_router_payload("response_only"))

    decision = route_message(
        UserMessage(task_id="no-keyword-router", content="可以跟我聊聊吗"),
        model_client=model,
    )

    assert decision.intent == "chat"
    assert model.calls == 1


def test_route_message_model_failure_returns_missing_input_not_keyword_guess() -> None:
    decision = route_message(
        UserMessage(task_id="router-model-missing", content="帮我做一下这个"),
        model_client=None,
    )

    assert decision.intent == "missing_input"
    assert decision.source == "fallback"
    assert decision.should_clarify is True
    assert decision.missing_inputs == ["router_decision"]
```

- [ ] **Step 2: Run the Router V2 tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python\tests\test_router_v2.py -q
```

Expected: FAIL because `route_message()` still returns `deterministic_route()` when `ALITA_STRUCTURED_ROUTER` is unset.

- [ ] **Step 3: Extend `RouterV2Decision` for semantic payload compatibility**

Modify `RouterV2Decision` in `python/agent_service/router_v2.py`:

```python
RouteSource = Literal["deterministic", "model", "fallback"]


class RouterV2Decision(BaseModel):
    intent: AgentRouteIntent
    confidence: float = Field(ge=0.0, le=1.0)
    task_type: TaskType
    missing_inputs: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    tool_candidates: list[str] = Field(default_factory=list)
    reason: str
    source: RouteSource
    should_clarify: bool = False
    clarification_prompt: str | None = None
    legacy_route: dict[str, Any] = Field(default_factory=dict)
    structured_route: dict[str, Any] = Field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "taskType": self.task_type,
            "missingInputs": _scrub_payload(list(self.missing_inputs)),
            "requiredPermissions": _scrub_payload(list(self.required_permissions)),
            "toolCandidates": _scrub_payload(list(self.tool_candidates)),
            "reason": _safe_reason(self.reason),
            "source": self.source,
            "shouldClarify": self.should_clarify,
            "clarificationPrompt": _safe_optional_text(self.clarification_prompt),
            "semanticRoute": _scrub_payload(dict(self.structured_route)),
        }
```

- [ ] **Step 4: Replace `route_message()` main path with Semantic Router**

Modify imports:

```python
from agent_service.semantic_router import (
    SemanticRouteDecision,
    route_semantically,
)
```

Replace `route_message()`:

```python
def route_message(
    message: UserMessage,
    *,
    inquiry_choice: InquiryChoice | None = None,
    model_client: RouterModelClient | None = None,
    current_graph: Any | None = None,
    pending_choice: dict[str, Any] | None = None,
    available_capabilities: list[str] | None = None,
) -> RouterV2Decision:
    semantic = route_semantically(
        message,
        model_client=model_client,
        current_graph=current_graph,
        pending_choice=pending_choice,
        available_capabilities=available_capabilities,
    )
    return _router_v2_from_semantic_decision(
        semantic,
        inquiry_choice=inquiry_choice,
    )
```

Add mapping helpers:

```python
def _router_v2_from_semantic_decision(
    semantic: SemanticRouteDecision,
    *,
    inquiry_choice: InquiryChoice | None,
) -> RouterV2Decision:
    intent = _intent_from_semantic_route(semantic.route, inquiry_choice=inquiry_choice)
    missing_inputs = list(semantic.missing_inputs)
    if semantic.requires_clarification and not missing_inputs:
        missing_inputs = ["clarification"]
    reason = _safe_reason(semantic.reason)
    return RouterV2Decision(
        intent=intent,
        confidence=semantic.confidence,
        task_type=_task_type_from_semantic(semantic),
        missing_inputs=missing_inputs,
        required_permissions=[],
        tool_candidates=list(semantic.tool_candidates),
        reason=reason,
        source="model" if semantic.confidence > 0 else "fallback",
        should_clarify=semantic.requires_clarification or intent == "missing_input",
        clarification_prompt=semantic.clarification_prompt,
        legacy_route=_legacy_route_for_router_decision(intent, reason, missing_inputs),
        structured_route=semantic.to_payload(),
    )


def _intent_from_semantic_route(
    route: str,
    *,
    inquiry_choice: InquiryChoice | None,
) -> AgentRouteIntent:
    if route in {"response_only", "local_answer"}:
        return "chat" if route == "response_only" else "local_inquiry"
    if route == "simple_tool_answer":
        return "web_simple_inquiry"
    if route == "web_answer":
        return "web_simple_inquiry"
    if route == "research_planning":
        if inquiry_choice == "quick_answer":
            return "web_simple_inquiry"
        return "web_complex_research_flow"
    if route == "deep_planning":
        return "task"
    if route == "graph_feedback":
        return "task"
    return "missing_input"


def _task_type_from_semantic(semantic: SemanticRouteDecision) -> TaskType:
    if semantic.requires_files:
        return "document_processing"
    if semantic.route in {"web_answer", "research_planning"}:
        return "research"
    if semantic.route in {"response_only", "local_answer"}:
        return "chat"
    if semantic.route == "deep_planning":
        return "unknown"
    return "chat"
```

- [ ] **Step 5: Keep `deterministic_route()` but mark it legacy**

Add this docstring to `deterministic_route()`:

```python
def deterministic_route(
    message: UserMessage,
    inquiry_choice: InquiryChoice | None = None,
) -> RouterV2Decision:
    """Legacy compatibility helper.

    This function must not be called by RuntimeEngine or route_message() for
    natural-language intent routing. It exists only for older tests and migration
    diagnostics while Semantic Router becomes the default route source.
    """
```

- [ ] **Step 6: Run Router V2 tests**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python\tests\test_router_v2.py -q
```

Expected: PASS after updating old deterministic parity tests to call `deterministic_route()` explicitly and new route tests to inject `FakeRouterModel`.

- [ ] **Step 7: Commit Task 3**

```powershell
git add python\agent_service\router_v2.py python\tests\test_router_v2.py
git commit -m "feat: make semantic router the route v2 default"
```

---

### Task 4: Add Capability Gate

**Files:**
- Create: `python/agent_service/capability_gate.py`
- Test: `python/tests/test_capability_gate.py`

- [ ] **Step 1: Write failing capability tests**

Create `python/tests/test_capability_gate.py`:

```python
from __future__ import annotations

from agent_service.capability_gate import CapabilityGateResult, evaluate_route_capabilities
from agent_service.schemas import UserMessage
from agent_service.semantic_router import SemanticRouteDecision


def _decision(**updates) -> SemanticRouteDecision:
    data = {
        "route": "web_answer",
        "intent": "latest_fact",
        "complexity": "simple",
        "requiresGraph": False,
        "requiresTools": True,
        "requiresWeb": True,
        "requiresFiles": False,
        "requiresClarification": False,
        "language": "zh",
        "confidence": 0.92,
        "contextUsed": ["current_message"],
        "missingInputs": [],
        "requiredCapabilities": ["web.search"],
        "toolCandidates": ["web.search.parallel"],
        "reason": "需要联网查询。",
    }
    data.update(updates)
    return SemanticRouteDecision.model_validate(data)


def test_capability_gate_allows_available_web_tool() -> None:
    result = evaluate_route_capabilities(
        _decision(),
        UserMessage(task_id="cap-ok", content="查一下最新版本"),
        available_capabilities=["web.search.parallel"],
    )

    assert result == CapabilityGateResult(allowed=True, reason="capabilities available")


def test_capability_gate_blocks_missing_web_tool_without_changing_intent() -> None:
    result = evaluate_route_capabilities(
        _decision(),
        UserMessage(task_id="cap-block", content="查一下最新版本"),
        available_capabilities=[],
    )

    assert result.allowed is False
    assert result.missing_capabilities == ["web.search.parallel"]
    assert "当前任务需要尚未接入的能力" in result.user_message


def test_capability_gate_blocks_required_file_without_attachment() -> None:
    result = evaluate_route_capabilities(
        _decision(
            route="deep_planning",
            requiresGraph=True,
            requiresTools=True,
            requiresWeb=False,
            requiresFiles=True,
            requiredCapabilities=["document.read"],
            toolCandidates=["document.read_write"],
            reason="需要处理附件。",
        ),
        UserMessage(task_id="cap-file", content="整理这个文档"),
        available_capabilities=["document.read_write"],
    )

    assert result.allowed is False
    assert result.missing_inputs == ["attachment"]
    assert result.user_message == "请先添加需要处理的文档。"
```

- [ ] **Step 2: Run the capability tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python\tests\test_capability_gate.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_service.capability_gate'`.

- [ ] **Step 3: Implement Capability Gate**

Create `python/agent_service/capability_gate.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, Field

from agent_service.schemas import UserMessage
from agent_service.semantic_router import SemanticRouteDecision


class CapabilityGateResult(BaseModel):
    allowed: bool
    reason: str
    missing_capabilities: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    user_message: str = ""


def evaluate_route_capabilities(
    decision: SemanticRouteDecision,
    message: UserMessage,
    *,
    available_capabilities: list[str],
) -> CapabilityGateResult:
    if decision.requires_files and not message.attachments:
        return CapabilityGateResult(
            allowed=False,
            reason="missing required file attachment",
            missing_inputs=["attachment"],
            user_message="请先添加需要处理的文档。",
        )

    missing = [
        tool
        for tool in decision.tool_candidates
        if tool and tool not in available_capabilities
    ]
    if missing:
        return CapabilityGateResult(
            allowed=False,
            reason="missing route capabilities",
            missing_capabilities=missing,
            user_message=(
                "当前任务需要尚未接入的能力："
                + "、".join(missing)
                + "。请调整任务目标或等待该能力接入后再执行。"
            ),
        )

    return CapabilityGateResult(allowed=True, reason="capabilities available")
```

- [ ] **Step 4: Run the capability tests**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python\tests\test_capability_gate.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```powershell
git add python\agent_service\capability_gate.py python\tests\test_capability_gate.py
git commit -m "feat: add semantic route capability gate"
```

---

### Task 5: Route RuntimeEngine Through Semantic Router

**Files:**
- Modify: `python/agent_service/agent_runtime_engine.py`
- Test: `python/tests/test_agent_runtime_engine_deep_agent.py`

- [ ] **Step 1: Add failing RuntimeEngine tests for semantic decisions**

Add to `python/tests/test_agent_runtime_engine_deep_agent.py`:

```python
import json


class FakeSemanticModel:
    def __init__(self, route: str):
        self.route = route
        self.calls = 0

    def chat(self, messages, *, temperature=None, max_tokens=None, policy=None):
        self.calls += 1
        return json.dumps(
            {
                "route": self.route,
                "intent": "runtime_test",
                "complexity": "simple" if self.route == "response_only" else "multi_step",
                "requiresGraph": self.route in {"deep_planning", "research_planning"},
                "requiresTools": self.route in {"web_answer", "deep_planning", "research_planning"},
                "requiresWeb": self.route in {"web_answer", "research_planning"},
                "requiresFiles": False,
                "requiresClarification": False,
                "language": "zh",
                "confidence": 0.94,
                "contextUsed": ["current_message"],
                "missingInputs": [],
                "requiredCapabilities": [],
                "toolCandidates": [],
                "reason": "语义路由测试。",
            }
        )


def test_plain_greeting_route_is_decided_by_semantic_model_not_keyword(monkeypatch) -> None:
    def fail_deterministic_route(*args, **kwargs):
        raise AssertionError("deterministic_route must not decide natural-language route")

    monkeypatch.setattr(
        "agent_service.agent_runtime_engine.deterministic_route",
        fail_deterministic_route,
        raising=False,
    )
    deep_calls: list[UserMessage] = []
    legacy_calls: list[AgentRunState] = []

    def deep_runtime(message: UserMessage, **kwargs):
        del kwargs
        deep_calls.append(message)
        raise AssertionError("semantic response_only must not enter Deep Agent")

    def legacy_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_calls.append(run_state)
        return [
            AgentEvent(
                type="message.created",
                payload={"message": {"content": "你好，我在。"}},
            )
        ]

    engine = AgentRuntimeEngine(route_runner=legacy_runner, deep_runtime_runner=deep_runtime)
    run_state = AgentRunState.from_user_message(
        UserMessage(task_id="semantic-runtime-hi", content="你好")
    ).model_copy(update={"project_path": "D:/Project/demo.alita", "run_id": "run-hi"})

    result = engine.run_from_state(run_state, model_client=FakeSemanticModel("response_only"))

    assert deep_calls == []
    assert len(legacy_calls) == 1
    assert legacy_calls[0].intent == "chat"
    assert result.state.stage == "plan"


def test_semantic_deep_planning_enters_deep_agent() -> None:
    deep_calls: list[UserMessage] = []

    def deep_runtime(message: UserMessage, **kwargs):
        del kwargs
        deep_calls.append(message)
        return [
            AgentEvent(
                type="node_graph.created",
                payload={
                    "graph": {
                        "graphId": "semantic-deep-plan",
                        "nodes": [],
                        "edges": [],
                        "metadata": {"generatedBy": "deep_agent_runtime"},
                    }
                },
            )
        ]

    engine = AgentRuntimeEngine(deep_runtime_runner=deep_runtime)
    run_state = AgentRunState.from_user_message(
        UserMessage(task_id="semantic-task", content="帮我生成一份调研报告")
    ).model_copy(update={"project_path": "D:/Project/demo.alita", "run_id": "run-task"})

    result = engine.run_from_state(run_state, model_client=FakeSemanticModel("deep_planning"))

    assert len(deep_calls) == 1
    assert [event.type for event in result.events] == [
        "runtime.run_started",
        "node_graph.created",
    ]
```

- [ ] **Step 2: Run RuntimeEngine tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python\tests\test_agent_runtime_engine_deep_agent.py::test_plain_greeting_route_is_decided_by_semantic_model_not_keyword python\tests\test_agent_runtime_engine_deep_agent.py::test_semantic_deep_planning_enters_deep_agent -q
```

Expected: FAIL because RuntimeEngine still uses `_run_state_for_pre_deep_response()` with deterministic routing and does not pass semantic route context.

- [ ] **Step 3: Replace pre-deep deterministic route helper**

In `python/agent_service/agent_runtime_engine.py`, remove the import:

```python
from agent_service.router_v2 import deterministic_route
```

Add imports:

```python
from agent_service.capability_gate import evaluate_route_capabilities
from agent_service.router_v2 import RouterV2Decision, route_message
```

Replace `_run_state_for_pre_deep_response()` with:

```python
def _run_state_for_pre_deep_response(
    run_state: AgentRunState,
    *,
    model_client: Any | None,
) -> AgentRunState | None:
    if run_state.current_graph is not None:
        return None
    if run_state.pending_choice is not None:
        return None
    if run_state.inquiry_choice == "research_flow":
        return None

    decision = route_message(
        run_state.message,
        inquiry_choice=run_state.inquiry_choice,
        model_client=model_client,
        current_graph=run_state.current_graph,
        pending_choice=run_state.pending_choice,
        available_capabilities=_runtime_available_capabilities(),
    )
    if decision.intent not in {"chat", "local_inquiry", "web_simple_inquiry", "missing_input"}:
        return None

    if _semantic_capability_blocked(run_state, decision):
        return run_state.model_copy(
            update={
                "intent": "missing_input",
                "route_decision": decision.legacy_route,
                "structured_route_decision": decision.to_payload(),
            }
        )

    return run_state.model_copy(
        update={
            "intent": decision.intent,
            "route_decision": decision.legacy_route,
            "structured_route_decision": decision.to_payload(),
        }
    )
```

Add helpers:

```python
def _runtime_available_capabilities() -> list[str]:
    return [
        "weather.current",
        "web.search.parallel",
        "web.fetch.sources",
        "document.read_write",
        "output.final_response",
        "output.pdf",
    ]


def _semantic_capability_blocked(
    run_state: AgentRunState,
    decision: RouterV2Decision,
) -> bool:
    semantic = decision.structured_route
    tool_candidates = semantic.get("toolCandidates") if isinstance(semantic, dict) else []
    requires_files = bool(semantic.get("requiresFiles")) if isinstance(semantic, dict) else False
    if requires_files and not run_state.message.attachments:
        return True
    if not isinstance(tool_candidates, list):
        return False
    available = set(_runtime_available_capabilities())
    return any(str(candidate) not in available for candidate in tool_candidates)
```

- [ ] **Step 4: Update pre-deep helper calls**

In `run_from_state()`:

```python
pre_deep_response_run_state = _run_state_for_pre_deep_response(
    run_state,
    model_client=model_client,
)
```

In `stream_from_state()`:

```python
pre_deep_response_run_state = _run_state_for_pre_deep_response(
    run_state,
    model_client=model_client,
)
```

- [ ] **Step 5: Run RuntimeEngine tests**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python\tests\test_agent_runtime_engine_deep_agent.py -q
```

Expected: PASS after updating old greeting tests to inject `FakeSemanticModel("response_only")`.

- [ ] **Step 6: Commit Task 5**

```powershell
git add python\agent_service\agent_runtime_engine.py python\tests\test_agent_runtime_engine_deep_agent.py
git commit -m "feat: route runtime engine through semantic router"
```

---

### Task 6: Remove Keyword Routing From Graph Compatibility Path

**Files:**
- Modify: `python/agent_service/graph.py`
- Test: `python/tests/test_graph.py`

- [ ] **Step 1: Add failing graph tests that reject `classify_route()` usage**

Add to `python/tests/test_graph.py`:

```python
import json


class FakeGraphSemanticModel:
    def __init__(self, route: str):
        self.route = route

    def chat(self, messages, *, temperature=None, max_tokens=None, policy=None):
        return json.dumps(
            {
                "route": self.route,
                "intent": "graph_test",
                "complexity": "simple",
                "requiresGraph": False,
                "requiresTools": False,
                "requiresWeb": False,
                "requiresFiles": False,
                "requiresClarification": False,
                "language": "zh",
                "confidence": 0.93,
                "contextUsed": ["current_message"],
                "missingInputs": [],
                "requiredCapabilities": [],
                "toolCandidates": [],
                "reason": "图兼容路径语义路由。",
            }
        )


def test_run_agent_from_state_uses_semantic_router_not_classify_route(monkeypatch) -> None:
    def fail_classify_route(message):
        raise AssertionError("classify_route must not run in graph route path")

    monkeypatch.setattr("agent_service.graph.classify_route", fail_classify_route)
    events = run_agent(
        UserMessage(task_id="graph-semantic", content="你好"),
        model_client=FakeGraphSemanticModel("response_only"),
    )

    assert events[0].type == "message.created"
```

- [ ] **Step 2: Run the graph test and verify it fails**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python\tests\test_graph.py::test_run_agent_from_state_uses_semantic_router_not_classify_route -q
```

Expected: FAIL while `graph.py` still imports and calls `classify_route()` in graph feedback and route compatibility paths.

- [ ] **Step 3: Make `_should_handle_graph_feedback()` non-semantic**

Replace `_should_handle_graph_feedback()` in `python/agent_service/graph.py` so it no longer calls `classify_route()`:

```python
def _should_handle_graph_feedback(
    message: UserMessage,
    current_graph: RunGraph | None,
    *,
    pending_choice: dict | None,
) -> bool:
    if current_graph is None:
        return False
    if pending_choice is not None:
        return True

    feedback_decision = classify_graph_feedback(message.content, current_graph)
    if feedback_decision.kind == GraphFeedbackKind.NEW_TASK:
        return False
    if feedback_decision.kind in {
        GraphFeedbackKind.LOCAL_MODIFICATION,
        GraphFeedbackKind.FULL_REPLAN,
        GraphFeedbackKind.CONSTRAINT_UPDATE,
    }:
        return True
    return False
```

This still uses `classify_graph_feedback()`, which is graph-state feedback handling, not main natural-language task routing. Later work can move graph feedback into Semantic Router when currentGraph route coverage is complete.

- [ ] **Step 4: Pass current graph context into `route_message()`**

Modify `_route_run_state()`:

```python
router_decision = route_message(
    message,
    inquiry_choice=effective_inquiry_choice,
    model_client=model_client,
    current_graph=run_state.current_graph,
    pending_choice=run_state.pending_choice,
)
```

- [ ] **Step 5: Run graph tests**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python\tests\test_graph.py -q
```

Expected: PASS after updating tests that relied on deterministic route to inject fake semantic model decisions.

- [ ] **Step 6: Commit Task 6**

```powershell
git add python\agent_service\graph.py python\tests\test_graph.py
git commit -m "feat: remove keyword route from graph dispatch"
```

---

### Task 7: Update API, Integration, and Human Smoke Coverage

**Files:**
- Modify: `python/tests/test_app.py`
- Modify: `python/tests/test_agent_routing_integration.py`
- Modify: `python/tests/test_human_task_smoke.py`
- Modify: `scripts/run-human-agent-smoke.ps1`

- [ ] **Step 1: Add API-level semantic greeting test**

Add to `python/tests/test_app.py`:

```python
def test_agent_message_greeting_uses_semantic_router(monkeypatch) -> None:
    model = FakeDeepModel(
        [
            {
                "route": "response_only",
                "intent": "greeting",
                "complexity": "simple",
                "requiresGraph": False,
                "requiresTools": False,
                "requiresWeb": False,
                "requiresFiles": False,
                "requiresClarification": False,
                "language": "zh",
                "confidence": 0.96,
                "contextUsed": ["current_message"],
                "missingInputs": [],
                "requiredCapabilities": [],
                "toolCandidates": [],
                "reason": "用户是在问候。",
            }
        ]
    )
    monkeypatch.setattr("agent_service.app.create_model_client", lambda *args, **kwargs: model)

    response = TestClient(app).post(
        "/agent/message",
        json={"task_id": "app-semantic-hi", "content": "你好", "attachments": []},
    )

    assert response.status_code == 200
    event_types = [event["type"] for event in response.json()]
    assert "planning.failed" not in event_types
    assert "node_graph.created" not in event_types
```

- [ ] **Step 2: Add human smoke natural-language variants**

Add cases to `python/tests/test_human_task_smoke.py`:

```python
def test_semantic_router_handles_non_keyword_greeting_and_task_forms() -> None:
    greeting_model = FakeHumanModel(route="response_only")
    greeting_events = run_agent_from_state(
        AgentRunState.from_user_message(
            UserMessage(task_id="human-semantic-greeting", content="早啊，今天状态怎么样")
        ),
        model_client=greeting_model,
    )
    assert greeting_events[0].type == "message.created"

    task_model = FakeHumanModel(route="deep_planning")
    task_events = run_agent_from_state(
        AgentRunState.from_user_message(
            UserMessage(
                task_id="human-semantic-task",
                content="我想把这件事整理成一个能交付给同事的结果",
            )
        ),
        model_client=task_model,
    )
    assert any(event.type == "node_graph.created" for event in task_events)
```

- [ ] **Step 3: Run integration and smoke tests**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python\tests\test_app.py python\tests\test_agent_routing_integration.py python\tests\test_human_task_smoke.py -q
```

Expected: PASS.

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run-human-agent-smoke.ps1
```

Expected: PASS.

- [ ] **Step 4: Commit Task 7**

```powershell
git add python\tests\test_app.py python\tests\test_agent_routing_integration.py python\tests\test_human_task_smoke.py scripts\run-human-agent-smoke.ps1
git commit -m "test: cover semantic router runtime paths"
```

---

### Task 8: Documentation and Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/agent-development-optimization-2026-06-07-human-agent-test.md`

- [ ] **Step 1: Update README routing section**

In `README.md`, replace the Agent routing description with:

```markdown
### 2. Agent 语义路由

Python sidecar 现在由 `AgentRuntimeEngine` 统一入口。用户自然语言意图不再由关键词、正则或模板判断；自然语言判断由 Semantic Router 模型输出结构化 JSON。程序只保留非语义状态守卫，例如空输入、pending choice、附件状态、权限状态和工具可用性。

路由顺序：

```text
UserMessage
  -> State Guard
  -> Semantic Router LLM
  -> Router Validator
  -> Capability Gate
  -> response / tool answer / graph feedback / Deep Agent planning
```

这保证“你好”这类普通输入不会进入任务规划器，也保证复杂任务不会因为缺少固定关键词而被当作普通问答。
```

- [ ] **Step 2: Update optimization document status**

In `docs/agent-development-optimization-2026-06-07-human-agent-test.md`, add this under P0-4:

```markdown
执行计划：`docs/superpowers/plans/2026-06-07-semantic-router-agent-judgment-implementation-plan.md`。

验收标准：

- `route_message()` 主路径不调用 `classify_route()`。
- RuntimeEngine 普通聊天由 Semantic Router 决策为 `response_only` 后直接回复。
- Semantic Router 模型失败时不回退关键词规则，而是进入中文澄清。
- Deep Agent 只接收 Semantic Router 判定为 `deep_planning` 或 `research_planning` 的请求。
```

- [ ] **Step 3: Run focused verification**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python\tests\test_semantic_router.py python\tests\test_router_v2.py python\tests\test_capability_gate.py python\tests\test_agent_runtime_engine_deep_agent.py -q
```

Expected: PASS.

- [ ] **Step 4: Run full Python verification**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python\tests -q
```

Expected: PASS.

- [ ] **Step 5: Run frontend typecheck and tests**

Run:

```powershell
npm run frontend:typecheck
npm run frontend:test
```

Expected: PASS for both commands.

- [ ] **Step 6: Run Rust tests after closing running Alita if DLL lock appears**

Run:

```powershell
cargo test --manifest-path src-tauri\Cargo.toml
```

Expected: PASS. If Windows reports `os error 32` for `src-tauri\target\debug\llama-cpp\cublas64_13.dll`, close the running Alita development app and rerun the same command.

- [ ] **Step 7: Commit Task 8**

```powershell
git add README.md docs\agent-development-optimization-2026-06-07-human-agent-test.md
git commit -m "docs: document semantic router runtime"
```

---

## Final Verification Checklist

- [ ] `rg -n "route_message\\(|deterministic_route\\(|classify_route\\(" python\agent_service` shows no RuntimeEngine or graph main route path using `classify_route()` for natural-language intent routing.
- [ ] `python\agent_service\intent.py` remains only as legacy compatibility code or is removed in a later cleanup plan.
- [ ] Semantic Router model failure produces `clarification_required`, not a guessed keyword route.
- [ ] Greeting and lightweight questions do not enter Deep Agent planning.
- [ ] Multi-step task requests enter Deep Agent planning when the Semantic Router returns `deep_planning`.
- [ ] Tool unavailable cases are blocked by Capability Gate before the Agent presents an impossible executable graph.
- [ ] Chinese user messages produce Chinese clarification text.

## Self-Review Notes

- Spec coverage: The plan covers model semantic routing, removal of keyword fallback, state guard boundaries, capability validation, runtime dispatch, graph compatibility, testing, and documentation.
- Scope control: This plan does not redesign Deep Agent planning internals or tool execution. It only decides how requests are routed before planning.
- Risk: Existing tests that call graph routes without a model client will need explicit fake Semantic Router models or will correctly receive clarification decisions.
