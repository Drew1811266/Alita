# Agent Runtime Phase D Structured Router V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a structured Router V2 layer that keeps Alita's deterministic routing behavior stable while making route decisions typed, inspectable, confidence-scored, and ready for model-assisted fallback.

**Architecture:** Preserve the public endpoint schemas, frontend event types, existing `AgentIntent` values, and current deterministic fast paths. Introduce `router_v2.py` as an internal adapter above `intent.py` and `goal_spec.py`; it converts existing route/goal signals into `RouterV2Decision`, optionally calls a model JSON router behind `ALITA_STRUCTURED_ROUTER=1`, and feeds the existing graph dispatcher through a legacy-compatible payload. Phase D does not add Planner Chain, dynamic tool execution, MCP planning, ReAct, memory, or frontend state refactors.

**Tech Stack:** Python 3.12, Pydantic v2, LangGraph `StateGraph`, pytest, existing `AgentRunState`, existing `UserMessage` / `RunGraph` schemas, existing model client `chat()` protocol.

---

## Current Baseline

Phase C is complete on branch `codex/agent-runtime-phase-a-security-hygiene`:

- `python/agent_service/agent_run_state.py` carries message, graph feedback context, run graph context, and routing metadata.
- `python/agent_service/execution.py` routes fixed tool execution through `UnifiedToolGateway`.
- `python/agent_service/tool_gateway.py` supports default gateway construction from injected `ToolRegistry`.
- `python/agent_service/graph.py` still routes with `classify_route()` plus `_compatible_intent()`.
- `python/agent_service/intent.py` still owns deterministic keyword/regex classification.
- `python/agent_service/goal_spec.py` still owns heuristic task typing and missing-input detection.
- Full verification passed before this plan was written: `.\scripts\verify-mvp.ps1` with `560 passed` Python tests plus frontend typecheck and Rust tests.

## Non-Goals

- Do not change FastAPI request/response schemas.
- Do not change frontend event type names.
- Do not change the visible `RunGraph` node/edge shape.
- Do not replace deterministic weather, empty-input, document-attachment, graph-feedback, or research-choice behavior.
- Do not let a model execute tools, select MCP tools, or create dynamic plans.
- Do not remove `intent.py`; Router V2 wraps it and gradually reduces direct graph coupling.
- Do not require a local/API model for routing when `ALITA_STRUCTURED_ROUTER` is unset.

## Files

### Create

- `python/agent_service/router_v2.py`
  - Typed `RouterV2Decision`.
  - Deterministic route adapter from current `classify_route()` and `parse_goal_spec()`.
  - Feature-flagged model JSON route fallback.
  - Confidence threshold handling and legacy payload conversion.
- `python/tests/test_router_v2.py`
  - Contract, deterministic parity, model fallback, malformed JSON, confidence, and privacy tests.

### Modify

- `python/agent_service/agent_run_state.py`
  - Add internal `structured_route_decision` field.
  - Extend `with_routing()` so `graph.py` can store both the legacy route payload and Router V2 payload.
- `python/agent_service/graph.py`
  - Replace direct `classify_route()` / `_compatible_intent()` routing with `route_message()`.
  - Keep `_classify_message()` and existing event behavior compatible.
  - Add structured route metadata to task/research graph payload metadata.
  - Preserve graph-feedback pre-routing guard.
- `python/tests/test_graph.py`
  - Update existing route metadata assertions.
  - Add graph payload route metadata tests.
  - Add streaming route tests for medium-confidence clarification.
- `python/tests/test_agent_run_state.py`
  - Add state copy tests for `structured_route_decision`.
- `python/tests/test_agent_routing_integration.py`
  - Add route metadata compatibility assertions without requiring frontend changes.

### Read-Only Regression Targets

- `python/tests/test_intent.py`
- `python/tests/test_app.py`
- `python/tests/test_execution.py`
- `python/tests/test_tool_gateway.py`
- `python/tests/test_model_tool_adapter.py`
- `src/features/task/useTaskEvents.test.ts`
- `src/app/backendEvents.test.ts`

---

## Design Contracts

### Router V2 Decision

`RouterV2Decision` is the new internal route contract. It should not replace public endpoint schemas.

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AgentRouteIntent = Literal[
    "chat",
    "local_inquiry",
    "web_simple_inquiry",
    "web_complex_choice",
    "web_complex_research_flow",
    "task",
    "missing_input",
]

RouteSource = Literal["deterministic", "model", "fallback"]


class RouterV2Decision(BaseModel):
    intent: AgentRouteIntent
    confidence: float = Field(ge=0.0, le=1.0)
    task_type: str = "unknown"
    missing_inputs: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    tool_candidates: list[str] = Field(default_factory=list)
    reason: str
    source: RouteSource = "deterministic"
    should_clarify: bool = False
    clarification_prompt: str | None = None
    legacy_route: dict[str, Any] = Field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "taskType": self.task_type,
            "missingInputs": list(self.missing_inputs),
            "requiredPermissions": list(self.required_permissions),
            "toolCandidates": list(self.tool_candidates),
            "reason": self.reason,
            "source": self.source,
            "shouldClarify": self.should_clarify,
            "clarificationPrompt": self.clarification_prompt,
        }
```

### Legacy Route Payload Compatibility

Existing code and tests expect this shape in `run_state.route_decision` and `state["route_decision"]`:

```python
{
    "intent": {"kind": "inquiry"},
    "inquiry": {"mode": "web_simple", "requires_web": True},
    "reason": "question requests current or external factual data",
    "missing_inputs": [],
}
```

Router V2 must continue to provide that shape through `RouterV2Decision.legacy_route`. New structured metadata is stored separately in `AgentRunState.structured_route_decision` and graph metadata.

### Confidence Thresholds

Use these constants in `router_v2.py`:

```python
HIGH_CONFIDENCE_THRESHOLD = 0.75
LOW_CONFIDENCE_THRESHOLD = 0.45
STRUCTURED_ROUTER_ENV = "ALITA_STRUCTURED_ROUTER"
```

Routing rules:

- `confidence >= 0.75`: proceed with the decision.
- `0.45 <= confidence < 0.75`: ask for clarification by routing as `missing_input` with `missing_inputs=["clarification"]`.
- `confidence < 0.45`: fallback to the deterministic decision.
- If model routing is disabled, always use deterministic behavior.
- Deterministic fast paths should have high confidence and must not call the model.

### Model Router Feature Flag

Only call model routing when:

```text
ALITA_STRUCTURED_ROUTER=1
```

and the deterministic decision is not a protected fast path.

Protected deterministic fast paths:

- Empty message with no attachment.
- Empty message with attachment.
- Weather tool route.
- Document attachment processing.
- Missing document attachment.
- Explicit research choice (`quick_answer` / `research_flow`).
- Graph feedback handled before routing in `graph.py`.

### Model Router JSON Contract

The model router must return JSON only:

```json
{
  "intent": "task",
  "confidence": 0.82,
  "task_type": "code_task",
  "missing_inputs": [],
  "required_permissions": ["read_project_files"],
  "tool_candidates": [],
  "reason": "User asks to implement a code change."
}
```

Parser rules:

- Accept snake_case keys from the model.
- Convert invalid intent to fallback.
- Clamp or reject invalid confidence; prefer fallback for invalid values.
- Never include raw attachment paths in `reason`, `tool_candidates`, or graph metadata.
- Do not use model output directly to execute tools.

---

## Task 0: Baseline Verification

**Files:**
- Read: `python/agent_service/graph.py`
- Read: `python/agent_service/intent.py`
- Read: `python/agent_service/goal_spec.py`
- Read: `python/agent_service/agent_run_state.py`
- Read: `python/tests/test_graph.py`
- Read: `python/tests/test_intent.py`

- [ ] **Step 1: Confirm branch and clean worktree**

Run:

```powershell
git status --short --branch
```

Expected:

```text
## codex/agent-runtime-phase-a-security-hygiene
```

- [ ] **Step 2: Run focused router baseline**

Run:

```powershell
python -m pytest -q python\tests\test_intent.py python\tests\test_graph.py python\tests\test_agent_routing_integration.py
```

Expected:

```text
... passed
```

- [ ] **Step 3: Run event compatibility baseline**

Run:

```powershell
npm run frontend:test -- src\features\task\useTaskEvents.test.ts src\app\backendEvents.test.ts
```

Expected:

```text
Test Files  2 passed
```

- [ ] **Step 4: Commit status**

Do not commit in Task 0.

---

## Task 1: Router V2 Contract And Deterministic Adapter

**Files:**
- Create: `python/agent_service/router_v2.py`
- Create: `python/tests/test_router_v2.py`

- [ ] **Step 1: Write failing tests for the Router V2 decision schema**

Create `python/tests/test_router_v2.py` with:

```python
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_service.router_v2 import (
    RouterV2Decision,
    deterministic_route,
    route_message,
)
from agent_service.schemas import Attachment, UserMessage


def test_router_v2_decision_payload_uses_frontend_safe_keys() -> None:
    decision = RouterV2Decision(
        intent="web_simple_inquiry",
        confidence=0.9,
        task_type="research",
        missing_inputs=[],
        required_permissions=["network"],
        tool_candidates=["weather.current"],
        reason="message routes to weather tool",
        source="deterministic",
        legacy_route={
            "intent": {"kind": "inquiry"},
            "inquiry": {"mode": "web_simple", "requires_web": True},
            "reason": "message routes to weather tool",
            "missing_inputs": [],
        },
    )

    assert decision.to_payload() == {
        "intent": "web_simple_inquiry",
        "confidence": 0.9,
        "taskType": "research",
        "missingInputs": [],
        "requiredPermissions": ["network"],
        "toolCandidates": ["weather.current"],
        "reason": "message routes to weather tool",
        "source": "deterministic",
        "shouldClarify": False,
        "clarificationPrompt": None,
    }


def test_router_v2_decision_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        RouterV2Decision(
            intent="chat",
            confidence=1.2,
            reason="invalid confidence",
        )
```

- [ ] **Step 2: Add deterministic parity tests**

Append to `python/tests/test_router_v2.py`:

```python
@pytest.mark.parametrize(
    ("content", "expected_intent", "expected_task_type"),
    [
        ("hello, thanks for your help", "chat", "chat"),
        ("What files are attached to this conversation?", "local_inquiry", "chat"),
        ("What is the latest Python release?", "web_simple_inquiry", "research"),
        (
            "Research and compare current Python packaging tools",
            "web_complex_choice",
            "research",
        ),
        ("Create a Python script that counts rows in a CSV file.", "task", "chat"),
        ("请总结这个文档", "missing_input", "document_processing"),
    ],
)
def test_deterministic_route_matches_current_route_behavior(
    content: str,
    expected_intent: str,
    expected_task_type: str,
) -> None:
    decision = deterministic_route(UserMessage(task_id="route", content=content))

    assert decision.intent == expected_intent
    assert decision.task_type == expected_task_type
    assert decision.source == "deterministic"
    assert decision.confidence >= 0.75
    assert decision.legacy_route["reason"]


def test_deterministic_route_preserves_quick_answer_research_choice() -> None:
    decision = deterministic_route(
        UserMessage(
            task_id="route",
            content="Research and compare current Python packaging tools",
        ),
        inquiry_choice="quick_answer",
    )

    assert decision.intent == "web_simple_inquiry"
    assert decision.legacy_route["inquiry"]["mode"] == "web_simple"


def test_deterministic_route_preserves_research_flow_choice() -> None:
    decision = deterministic_route(
        UserMessage(
            task_id="route",
            content="Research and compare current Python packaging tools",
        ),
        inquiry_choice="research_flow",
    )

    assert decision.intent == "web_complex_research_flow"
    assert decision.legacy_route["inquiry"]["mode"] == "web_complex"


def test_deterministic_weather_route_includes_tool_candidate() -> None:
    decision = deterministic_route(
        UserMessage(task_id="weather", content="What's the weather in Seattle today?")
    )

    assert decision.intent == "web_simple_inquiry"
    assert decision.tool_candidates == ["weather.current"]
    assert "weather" in decision.reason.lower()


def test_attached_document_route_does_not_leak_attachment_path() -> None:
    attachment_path = r"C:\Users\Drew\Desktop\notes.docx"
    decision = deterministic_route(
        UserMessage(
            task_id="doc",
            content="请整理这个文档",
            attachments=[
                Attachment(
                    attachment_id="a1",
                    name="notes.docx",
                    path=attachment_path,
                    size_bytes=128,
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            ],
        )
    )

    assert decision.intent == "task"
    assert attachment_path not in repr(decision.to_payload())
    assert attachment_path not in repr(decision.legacy_route)
```

- [ ] **Step 3: Run tests and verify import failure**

Run:

```powershell
python -m pytest -q python\tests\test_router_v2.py
```

Expected:

```text
ModuleNotFoundError: No module named 'agent_service.router_v2'
```

- [ ] **Step 4: Create `router_v2.py` with schema and deterministic route**

Create `python/agent_service/router_v2.py` with:

```python
from __future__ import annotations

import json
import os
import re
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from agent_service.goal_spec import GoalSpec, parse_goal_spec
from agent_service.intent import (
    IntentKind,
    InquiryMode,
    RouteDecision,
    classify_route,
)
from agent_service.model_client import ChatMessage
from agent_service.schemas import UserMessage
from agent_service.tool_router import route_tool_for_message


AgentRouteIntent = Literal[
    "chat",
    "local_inquiry",
    "web_simple_inquiry",
    "web_complex_choice",
    "web_complex_research_flow",
    "task",
    "missing_input",
]
InquiryChoice = Literal["quick_answer", "research_flow"]
RouteSource = Literal["deterministic", "model", "fallback"]
STRUCTURED_ROUTER_ENV = "ALITA_STRUCTURED_ROUTER"
HIGH_CONFIDENCE_THRESHOLD = 0.75
LOW_CONFIDENCE_THRESHOLD = 0.45
LOCAL_PATH_PATTERN = re.compile(
    r"(?:[A-Za-z]:)?[\\/](?:[^\\/\s]+[\\/])+[^\\/\s]+"
)


class RouterModelClient(Protocol):
    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy=None,
    ) -> str:
        ...


class RouterV2Decision(BaseModel):
    intent: AgentRouteIntent
    confidence: float = Field(ge=0.0, le=1.0)
    task_type: str = "unknown"
    missing_inputs: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    tool_candidates: list[str] = Field(default_factory=list)
    reason: str
    source: RouteSource = "deterministic"
    should_clarify: bool = False
    clarification_prompt: str | None = None
    legacy_route: dict[str, Any] = Field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "taskType": self.task_type,
            "missingInputs": list(self.missing_inputs),
            "requiredPermissions": list(self.required_permissions),
            "toolCandidates": list(self.tool_candidates),
            "reason": self.reason,
            "source": self.source,
            "shouldClarify": self.should_clarify,
            "clarificationPrompt": self.clarification_prompt,
        }


def structured_router_enabled() -> bool:
    return os.getenv(STRUCTURED_ROUTER_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def deterministic_route(
    message: UserMessage,
    *,
    inquiry_choice: InquiryChoice | None = None,
) -> RouterV2Decision:
    route_decision = classify_route(message)
    goal_spec = parse_goal_spec(message)
    intent = compatible_intent(
        message,
        route_decision,
        inquiry_choice=inquiry_choice,
        goal_spec=goal_spec,
    )
    legacy_route = effective_legacy_route_payload(route_decision, intent)
    tool_candidates = _deterministic_tool_candidates(message)
    return RouterV2Decision(
        intent=intent,
        confidence=_deterministic_confidence(intent, route_decision),
        task_type=goal_spec.task_type,
        missing_inputs=list(route_decision.missing_inputs),
        required_permissions=list(goal_spec.permissions_required),
        tool_candidates=tool_candidates,
        reason=legacy_route["reason"],
        source="deterministic",
        legacy_route=legacy_route,
    )
```

- [ ] **Step 5: Add compatibility helpers to `router_v2.py`**

Append:

```python
def route_message(
    message: UserMessage,
    *,
    inquiry_choice: InquiryChoice | None = None,
    model_client: RouterModelClient | None = None,
) -> RouterV2Decision:
    deterministic = deterministic_route(message, inquiry_choice=inquiry_choice)
    if not structured_router_enabled() or _is_protected_fast_path(
        deterministic,
        inquiry_choice=inquiry_choice,
    ):
        return deterministic
    if model_client is None:
        return deterministic

    model_decision = model_route(
        message,
        deterministic_decision=deterministic,
        model_client=model_client,
    )
    if model_decision.confidence >= HIGH_CONFIDENCE_THRESHOLD:
        return model_decision
    if model_decision.confidence >= LOW_CONFIDENCE_THRESHOLD:
        clarification_prompt = _clarification_prompt(model_decision)
        return model_decision.model_copy(
            update={
                "intent": "missing_input",
                "missing_inputs": ["clarification"],
                "should_clarify": True,
                "clarification_prompt": clarification_prompt,
                "legacy_route": _legacy_route_for_router_decision(
                    intent="missing_input",
                    reason=model_decision.reason,
                    missing_inputs=["clarification"],
                ),
            }
        )
    return deterministic


def compatible_intent(
    message: UserMessage,
    decision: RouteDecision,
    *,
    inquiry_choice: InquiryChoice | None = None,
    goal_spec: GoalSpec | None = None,
) -> AgentRouteIntent:
    if (
        goal_spec is not None
        and goal_spec.task_type == "document_processing"
        and not _looks_like_external_web_request(message.content)
    ):
        if goal_spec.missing_inputs:
            return "missing_input"
        return "task"

    if decision.intent.kind == IntentKind.NEED_INPUT:
        return "missing_input"
    if decision.intent.kind == IntentKind.TASK:
        return "task"
    if decision.intent.kind == IntentKind.INQUIRY and decision.inquiry is not None:
        if decision.inquiry.mode == InquiryMode.LOCAL:
            return "local_inquiry"
        if decision.inquiry.mode == InquiryMode.WEB_SIMPLE:
            return "web_simple_inquiry"
        if decision.inquiry.mode == InquiryMode.WEB_COMPLEX:
            if inquiry_choice == "quick_answer":
                return "web_simple_inquiry"
            if inquiry_choice == "research_flow":
                return "web_complex_research_flow"
            return "web_complex_choice"
    return "chat"


def effective_legacy_route_payload(
    decision: RouteDecision,
    intent: AgentRouteIntent,
) -> dict[str, Any]:
    route_decision = decision.to_payload()
    if (
        intent == "web_simple_inquiry"
        and route_decision.get("inquiry", {}).get("mode") == InquiryMode.WEB_COMPLEX.value
    ):
        route_decision = {
            **route_decision,
            "inquiry": {
                **route_decision["inquiry"],
                "mode": InquiryMode.WEB_SIMPLE.value,
                "requires_web": True,
            },
        }
    return route_decision


def _legacy_route_for_router_decision(
    *,
    intent: AgentRouteIntent,
    reason: str,
    missing_inputs: list[str] | None = None,
) -> dict[str, Any]:
    missing = list(missing_inputs or [])
    if intent == "missing_input":
        return {
            "intent": {"kind": IntentKind.NEED_INPUT.value},
            "inquiry": None,
            "reason": reason,
            "missing_inputs": missing,
        }
    if intent == "task":
        return {
            "intent": {"kind": IntentKind.TASK.value},
            "inquiry": None,
            "reason": reason,
            "missing_inputs": missing,
        }
    if intent == "local_inquiry":
        return {
            "intent": {"kind": IntentKind.INQUIRY.value},
            "inquiry": {"mode": InquiryMode.LOCAL.value, "requires_web": False},
            "reason": reason,
            "missing_inputs": missing,
        }
    if intent == "web_simple_inquiry":
        return {
            "intent": {"kind": IntentKind.INQUIRY.value},
            "inquiry": {"mode": InquiryMode.WEB_SIMPLE.value, "requires_web": True},
            "reason": reason,
            "missing_inputs": missing,
        }
    if intent in {"web_complex_choice", "web_complex_research_flow"}:
        return {
            "intent": {"kind": IntentKind.INQUIRY.value},
            "inquiry": {"mode": InquiryMode.WEB_COMPLEX.value, "requires_web": True},
            "reason": reason,
            "missing_inputs": missing,
        }
    return {
        "intent": {"kind": IntentKind.CHAT.value},
        "inquiry": None,
        "reason": reason,
        "missing_inputs": missing,
    }


def _deterministic_tool_candidates(message: UserMessage) -> list[str]:
    tool_route = route_tool_for_message(message)
    if tool_route is None:
        return []
    return [tool_route.tool_name]


def _deterministic_confidence(
    intent: AgentRouteIntent,
    decision: RouteDecision,
) -> float:
    if decision.intent.kind == IntentKind.NEED_INPUT:
        return 0.95
    if intent in {"web_simple_inquiry", "web_complex_choice", "web_complex_research_flow"}:
        return 0.9
    if intent == "task":
        return 0.88
    return 0.82


def _is_protected_fast_path(
    decision: RouterV2Decision,
    *,
    inquiry_choice: InquiryChoice | None = None,
) -> bool:
    return (
        bool(decision.missing_inputs)
        or bool(decision.tool_candidates)
        or inquiry_choice is not None
        or decision.task_type == "document_processing"
        or decision.intent == "web_complex_research_flow"
    )


def _looks_like_external_web_request(content: str) -> bool:
    normalized = content.lower()
    return any(
        keyword in normalized
        for keyword in (
            "github",
            "search",
            "website",
            "web site",
            "网站",
            "查询",
            "搜索",
            "热门项目",
            "联网",
        )
    )
```

- [ ] **Step 6: Add model route parser stubs that fallback safely**

Append:

```python
def model_route(
    message: UserMessage,
    *,
    deterministic_decision: RouterV2Decision,
    model_client: RouterModelClient,
) -> RouterV2Decision:
    try:
        raw = model_client.chat(
            _router_model_messages(message, deterministic_decision),
            temperature=0.0,
            max_tokens=512,
        )
        payload = json.loads(raw)
        parsed = _decision_from_model_payload(
            payload,
            deterministic_decision=deterministic_decision,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, ValidationError):
        return deterministic_decision.model_copy(update={"source": "fallback"})
    return parsed


def _decision_from_model_payload(
    payload: dict[str, Any],
    *,
    deterministic_decision: RouterV2Decision,
) -> RouterV2Decision:
    intent = payload["intent"]
    missing_inputs = [str(value) for value in payload.get("missing_inputs", [])]
    reason = _safe_reason(str(payload.get("reason") or deterministic_decision.reason))
    decision = RouterV2Decision(
        intent=intent,
        confidence=float(payload["confidence"]),
        task_type=str(payload.get("task_type") or deterministic_decision.task_type),
        missing_inputs=missing_inputs,
        required_permissions=[
            str(value) for value in payload.get("required_permissions", [])
        ],
        tool_candidates=[
            _safe_reason(str(value)) for value in payload.get("tool_candidates", [])
        ],
        reason=reason,
        source="model",
        legacy_route=_legacy_route_for_router_decision(
            intent=intent,
            reason=reason,
            missing_inputs=missing_inputs,
        ),
    )
    return decision


def _router_model_messages(
    message: UserMessage,
    deterministic_decision: RouterV2Decision,
) -> list[ChatMessage]:
    attachment_names = [attachment.name for attachment in message.attachments]
    return [
        ChatMessage(
            role="system",
            content=(
                "You are Alita's structured router. Return only JSON with keys: "
                "intent, confidence, task_type, missing_inputs, required_permissions, "
                "tool_candidates, reason. Do not include local file paths. "
                "Allowed intents: chat, local_inquiry, web_simple_inquiry, "
                "web_complex_choice, web_complex_research_flow, task, missing_input."
            ),
        ),
        ChatMessage(
            role="user",
            content=json.dumps(
                {
                    "content": _safe_reason(message.content),
                    "attachments": attachment_names,
                    "deterministic": deterministic_decision.to_payload(),
                },
                ensure_ascii=False,
            ),
        ),
    ]


def _safe_reason(reason: str) -> str:
    sanitized = LOCAL_PATH_PATTERN.sub("[local path]", reason)
    return sanitized.replace("\\", "/")[:240]


def _clarification_prompt(decision: RouterV2Decision) -> str:
    return (
        "我需要再确认一下你的目标：你是想让我直接回答问题，"
        "还是创建一个可执行的任务流程？"
    )
```

- [ ] **Step 7: Run Router V2 tests**

Run:

```powershell
python -m pytest -q python\tests\test_router_v2.py
```

Expected:

```text
... passed
```

- [ ] **Step 8: Commit**

Run:

```powershell
git add python/agent_service/router_v2.py python/tests/test_router_v2.py
git commit -m "feat: add structured router v2 contract"
```

---

## Task 2: Integrate Router V2 Into Graph Routing

**Files:**
- Modify: `python/agent_service/agent_run_state.py`
- Modify: `python/agent_service/graph.py`
- Modify: `python/tests/test_agent_run_state.py`
- Modify: `python/tests/test_graph.py`

- [ ] **Step 1: Add failing AgentRunState structured route tests**

Append to `python/tests/test_agent_run_state.py`:

```python
def test_with_routing_can_store_structured_route_decision() -> None:
    state = AgentRunState.from_user_message(
        UserMessage(task_id="task-structured-route", content="hello")
    )
    goal_spec = GoalSpec(
        goal="hello",
        task_type="chat",
        deliverable="chat_answer",
        success_criteria=["回答用户的问题"],
        risk_level="read_only",
        confidence=0.7,
    )

    updated = state.with_routing(
        intent="chat",
        route_decision={
            "intent": {"kind": "chat"},
            "inquiry": None,
            "reason": "conversation",
            "missing_inputs": [],
        },
        goal_spec=goal_spec,
        structured_route_decision={
            "intent": "chat",
            "confidence": 0.82,
            "taskType": "chat",
            "missingInputs": [],
            "requiredPermissions": [],
            "toolCandidates": [],
            "reason": "conversation",
            "source": "deterministic",
            "shouldClarify": False,
            "clarificationPrompt": None,
        },
    )

    assert state.structured_route_decision is None
    assert updated.structured_route_decision["intent"] == "chat"
    assert updated.structured_route_decision["confidence"] == 0.82
```

- [ ] **Step 2: Add failing graph tests for Router V2 state**

In `python/tests/test_graph.py`, add:

```python
def test_graph_state_records_router_v2_decision_payload() -> None:
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-router-v2",
            content="What is the latest Python release?",
        )
    )
    app = build_graph(
        search_provider=FakeSearchProvider(
            SearchResponse(
                results=[
                    SearchResult(
                        title="Python release",
                        url="https://www.python.org/downloads/",
                        snippet="Latest release.",
                    )
                ]
            )
        )
    )

    result = app.invoke(
        {
            "run_state": run_state,
            "message": run_state.message,
            "events": [],
        }
    )

    updated = result["run_state"]
    assert updated.intent == "web_simple_inquiry"
    assert updated.route_decision["inquiry"]["mode"] == "web_simple"
    assert updated.structured_route_decision["intent"] == "web_simple_inquiry"
    assert updated.structured_route_decision["source"] == "deterministic"
    assert updated.structured_route_decision["confidence"] >= 0.75
```

- [ ] **Step 3: Run new tests and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_agent_run_state.py::test_with_routing_can_store_structured_route_decision python\tests\test_graph.py::test_graph_state_records_router_v2_decision_payload
```

Expected:

```text
FAILED ... unexpected keyword argument 'structured_route_decision'
```

- [ ] **Step 4: Extend `AgentRunState`**

In `python/agent_service/agent_run_state.py`, add this field:

```python
    structured_route_decision: dict[str, Any] | None = None
```

Change `with_routing()` signature:

```python
    def with_routing(
        self,
        *,
        intent: str,
        route_decision: dict[str, Any],
        goal_spec: GoalSpec,
        structured_route_decision: dict[str, Any] | None = None,
    ) -> "AgentRunState":
```

Change the update dict:

```python
        update = {
            "intent": intent,
            "route_decision": route_decision,
            "goal_spec": goal_spec,
        }
        if structured_route_decision is not None:
            update["structured_route_decision"] = structured_route_decision
        return self.model_copy(update=update)
```

- [ ] **Step 5: Replace direct route helpers in `graph.py`**

In `python/agent_service/graph.py`, change imports:

```python
from agent_service.intent import IntentKind, InquiryMode, RouteDecision, classify_route
```

to:

```python
from agent_service.intent import IntentKind, RouteDecision, classify_route
from agent_service.router_v2 import (
    RouterV2Decision,
    compatible_intent,
    effective_legacy_route_payload,
    route_message,
)
```

Then change `classify_intent()`:

```python
def classify_intent(
    state: AgentState,
    *,
    model_client: ModelClient | None = None,
) -> AgentState:
    run_state = _run_state_from_agent_state(state)
    routed_run_state = _route_run_state(
        run_state,
        inquiry_choice=state.get("inquiry_choice") or run_state.inquiry_choice,
        model_client=model_client,
    )
    return {
        **state,
        "run_state": routed_run_state,
        "message": routed_run_state.message,
        "intent": routed_run_state.intent,
        "route_decision": routed_run_state.route_decision,
        "goal_spec": routed_run_state.goal_spec,
    }
```

- [ ] **Step 6: Update `_route_run_state()` in `graph.py`**

Replace `_route_run_state()` with:

```python
def _route_run_state(
    run_state: AgentRunState,
    *,
    inquiry_choice: InquiryChoice | None = None,
    model_client: ModelClient | None = None,
) -> AgentRunState:
    effective_inquiry_choice = inquiry_choice or run_state.inquiry_choice
    message = run_state.message
    router_decision = route_message(
        message,
        inquiry_choice=effective_inquiry_choice,
        model_client=model_client,
    )
    goal_spec = parse_goal_spec(message)
    routed_run_state = run_state
    if effective_inquiry_choice != run_state.inquiry_choice:
        routed_run_state = routed_run_state.model_copy(
            update={"inquiry_choice": effective_inquiry_choice}
        )
    return routed_run_state.with_routing(
        intent=router_decision.intent,
        route_decision=router_decision.legacy_route,
        goal_spec=goal_spec,
        structured_route_decision=router_decision.to_payload(),
    )
```

- [ ] **Step 7: Keep legacy helper names compatible**

Replace `_effective_route_payload()` in `graph.py` with a wrapper:

```python
def _effective_route_payload(
    decision: RouteDecision,
    intent: AgentIntent,
) -> dict:
    return effective_legacy_route_payload(decision, intent)
```

Replace `_compatible_intent()` with:

```python
def _compatible_intent(
    message: UserMessage,
    decision: RouteDecision,
    *,
    inquiry_choice: InquiryChoice | None = None,
    goal_spec: GoalSpec | None = None,
) -> AgentIntent:
    return compatible_intent(
        message,
        decision,
        inquiry_choice=inquiry_choice,
        goal_spec=goal_spec,
    )
```

These wrappers keep existing direct tests and private imports stable for Phase D.

- [ ] **Step 8: Pass model client into the LangGraph classifier**

In `build_graph()`, change the classify node:

```python
    graph.add_node(
        "classify_intent",
        lambda state: classify_intent(
            {
                **state,
                "inquiry_choice": state.get("inquiry_choice") or inquiry_choice,
            },
            model_client=model_client,
        ),
    )
```

In `stream_agent_events_from_state()`, change:

```python
    run_state = _route_run_state(run_state)
```

to:

```python
    run_state = _route_run_state(run_state, model_client=model_client)
```

- [ ] **Step 9: Run state and graph tests**

Run:

```powershell
python -m pytest -q python\tests\test_agent_run_state.py python\tests\test_graph.py python\tests\test_router_v2.py
```

Expected:

```text
... passed
```

- [ ] **Step 10: Commit**

Run:

```powershell
git add python/agent_service/agent_run_state.py python/agent_service/graph.py python/tests/test_agent_run_state.py python/tests/test_graph.py
git commit -m "refactor: route graph decisions through router v2"
```

---

## Task 3: Feature-Flagged Model Router And Clarification Thresholds

**Files:**
- Modify: `python/agent_service/router_v2.py`
- Modify: `python/agent_service/graph.py`
- Modify: `python/tests/test_router_v2.py`
- Modify: `python/tests/test_graph.py`

- [ ] **Step 1: Add fake model client tests for high-confidence model route**

Append to `python/tests/test_router_v2.py`:

```python
class FakeRouterModelClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = []

    def chat(
        self,
        messages,
        *,
        temperature=None,
        max_tokens=None,
        policy=None,
    ):
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "policy": policy,
            }
        )
        return self.reply


def test_model_router_runs_only_when_feature_flag_enabled(monkeypatch) -> None:
    client = FakeRouterModelClient(
        json.dumps(
            {
                "intent": "task",
                "confidence": 0.86,
                "task_type": "code_task",
                "missing_inputs": [],
                "required_permissions": ["read_project_files"],
                "tool_candidates": [],
                "reason": "User asks for an implementation task.",
            }
        )
    )
    message = UserMessage(
        task_id="model-route",
        content="Can you turn this idea into code?",
    )

    disabled = route_message(message, model_client=client)
    assert client.calls == []
    assert disabled.source == "deterministic"

    monkeypatch.setenv("ALITA_STRUCTURED_ROUTER", "1")
    enabled = route_message(message, model_client=client)

    assert client.calls
    assert enabled.intent == "task"
    assert enabled.source == "model"
    assert enabled.confidence == 0.86
    assert enabled.required_permissions == ["read_project_files"]
```

- [ ] **Step 2: Add model parser fallback and clarification tests**

Append:

```python
def test_model_router_malformed_json_falls_back_to_deterministic(monkeypatch) -> None:
    monkeypatch.setenv("ALITA_STRUCTURED_ROUTER", "1")
    client = FakeRouterModelClient("not-json")
    message = UserMessage(task_id="bad-json", content="Can you improve this?")

    decision = route_message(message, model_client=client)

    assert decision.source == "fallback"
    assert decision.intent in {"task", "chat", "local_inquiry"}


def test_model_router_medium_confidence_asks_for_clarification(monkeypatch) -> None:
    monkeypatch.setenv("ALITA_STRUCTURED_ROUTER", "1")
    client = FakeRouterModelClient(
        json.dumps(
            {
                "intent": "task",
                "confidence": 0.62,
                "task_type": "unknown",
                "missing_inputs": [],
                "required_permissions": [],
                "tool_candidates": [],
                "reason": "Ambiguous between answer and task.",
            }
        )
    )

    decision = route_message(
        UserMessage(task_id="ambiguous", content="Can you help with this idea?"),
        model_client=client,
    )

    assert decision.intent == "missing_input"
    assert decision.should_clarify is True
    assert decision.missing_inputs == ["clarification"]
    assert decision.clarification_prompt is not None


def test_model_router_low_confidence_uses_deterministic_fallback(monkeypatch) -> None:
    monkeypatch.setenv("ALITA_STRUCTURED_ROUTER", "1")
    client = FakeRouterModelClient(
        json.dumps(
            {
                "intent": "task",
                "confidence": 0.2,
                "task_type": "unknown",
                "missing_inputs": [],
                "required_permissions": [],
                "tool_candidates": [],
                "reason": "Low confidence guess.",
            }
        )
    )

    decision = route_message(
        UserMessage(task_id="low-confidence", content="hello"),
        model_client=client,
    )

    assert decision.source == "deterministic"
    assert decision.intent == "chat"
```

- [ ] **Step 3: Add graph-level clarification test**

Append to `python/tests/test_graph.py`:

```python
def test_medium_confidence_model_route_emits_clarification_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALITA_STRUCTURED_ROUTER", "1")
    client = FakeModelClient(
        json.dumps(
            {
                "intent": "task",
                "confidence": 0.61,
                "task_type": "unknown",
                "missing_inputs": [],
                "required_permissions": [],
                "tool_candidates": [],
                "reason": "Ambiguous between answer and task.",
            }
        )
    )

    events = run_agent(
        UserMessage(task_id="clarify-route", content="Can you help with this idea?"),
        model_client=client,
    )

    assert [event.type for event in events] == ["input.required"]
    assert events[0].payload["missing"] == ["clarification"]
    assert "确认" in events[0].payload["prompt"]
```

Add `import json` to the top of `python/tests/test_graph.py` if it is not already present.

- [ ] **Step 4: Run new tests and verify current behavior**

Run:

```powershell
python -m pytest -q python\tests\test_router_v2.py::test_model_router_runs_only_when_feature_flag_enabled python\tests\test_router_v2.py::test_model_router_malformed_json_falls_back_to_deterministic python\tests\test_router_v2.py::test_model_router_medium_confidence_asks_for_clarification python\tests\test_router_v2.py::test_model_router_low_confidence_uses_deterministic_fallback python\tests\test_graph.py::test_medium_confidence_model_route_emits_clarification_prompt
```

Expected:

```text
... passed
```

If the graph-level test returns `message.created`, inspect whether `_is_protected_fast_path()` is too broad for the ambiguous prompt and adjust only that helper.

- [ ] **Step 5: Update `request_required_inputs()` for clarification**

In `python/agent_service/graph.py`, replace the prompt selection block in `request_required_inputs()` with:

```python
    route_decision = state.get("route_decision", {})
    missing_inputs = route_decision.get("missing_inputs", [])
    structured = state.get("run_state").structured_route_decision if state.get("run_state") else None
    if "document_file" in missing_inputs:
        prompt = "请把需要处理的文件添加到聊天框里。"
    elif "clarification" in missing_inputs and structured:
        prompt = structured.get(
            "clarificationPrompt",
            "我需要再确认一下你的目标：你是想直接提问，还是创建可执行任务？",
        )
    else:
        prompt = "请先输入你想让我处理的问题或任务。"
```

Keep the event type as `input.required`.

- [ ] **Step 6: Run routing tests**

Run:

```powershell
python -m pytest -q python\tests\test_router_v2.py python\tests\test_graph.py python\tests\test_intent.py
```

Expected:

```text
... passed
```

- [ ] **Step 7: Commit**

Run:

```powershell
git add python/agent_service/router_v2.py python/agent_service/graph.py python/tests/test_router_v2.py python/tests/test_graph.py
git commit -m "feat: add feature-flagged structured model router"
```

---

## Task 4: Structured Route Metadata On Graph Payloads

**Files:**
- Modify: `python/agent_service/graph.py`
- Modify: `python/tests/test_graph.py`
- Modify: `python/tests/test_agent_routing_integration.py`
- Read: `src/app/backendEvents.test.ts`

- [ ] **Step 1: Add failing test for task graph route metadata**

Append to `python/tests/test_graph.py`:

```python
def test_task_graph_records_structured_route_decision_metadata() -> None:
    events = run_agent(
        UserMessage(
            task_id="task-route-metadata",
            content="Create a Python script that counts rows in a CSV file.",
        )
    )

    assert events[0].type == "node_graph.created"
    graph = events[0].payload["graph"]
    route = graph["metadata"]["routeDecision"]
    assert route["intent"] == "task"
    assert route["source"] == "deterministic"
    assert route["confidence"] >= 0.75
    assert route["taskType"] == "chat"
```

- [ ] **Step 2: Add failing test for research graph route metadata**

Append:

```python
def test_research_graph_records_structured_route_decision_metadata() -> None:
    events = run_agent(
        UserMessage(
            task_id="research-route-metadata",
            content="Research and compare current Python packaging tools",
        ),
        inquiry_choice="research_flow",
    )

    assert events[0].type == "node_graph.created"
    graph = events[0].payload["graph"]
    route = graph["metadata"]["routeDecision"]
    assert route["intent"] == "web_complex_research_flow"
    assert route["source"] == "deterministic"
    assert route["taskType"] == "research"
    assert graph["metadata"]["kind"] == "research"
```

- [ ] **Step 3: Add integration assertion that frontend receives compatible graph**

In `python/tests/test_agent_routing_integration.py`, update `test_task_message_creates_graph_with_planning_and_executable_nodes()` by adding:

```python
    assert graph["metadata"]["routeDecision"]["intent"] == "task"
    assert graph["metadata"]["routeDecision"]["source"] == "deterministic"
```

Do not change event type expectations.

- [ ] **Step 4: Run metadata tests and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_graph.py::test_task_graph_records_structured_route_decision_metadata python\tests\test_graph.py::test_research_graph_records_structured_route_decision_metadata python\tests\test_agent_routing_integration.py::test_task_message_creates_graph_with_planning_and_executable_nodes
```

Expected before implementation:

```text
KeyError: 'routeDecision'
```

- [ ] **Step 5: Add route metadata helper in `graph.py`**

Add:

```python
def _with_route_decision_metadata(
    graph_payload: dict,
    run_state: AgentRunState | None,
) -> dict:
    if run_state is None or run_state.structured_route_decision is None:
        return graph_payload
    metadata = dict(graph_payload.get("metadata") or {})
    metadata["routeDecision"] = dict(run_state.structured_route_decision)
    return {**graph_payload, "metadata": metadata}
```

- [ ] **Step 6: Thread run-state into graph payload builders**

Change `plan_task_graph()`:

```python
def plan_task_graph(state: AgentState) -> AgentState:
    message = state["message"]
    graph_payload = _graph_payload_for_task(
        message,
        goal_spec=state.get("goal_spec"),
    )
    graph_payload = _with_route_decision_metadata(
        graph_payload,
        state.get("run_state"),
    )
    return {
        **state,
        "events": [
            AgentEvent(
                type="node_graph.created",
                payload={"graph": graph_payload},
            )
        ],
    }
```

Change `_research_graph_payload()`:

```python
def _research_graph_payload(state: AgentState) -> dict:
    graph_payload = _with_model_policy_metadata(
        build_research_graph(
            state["message"],
            state.get("route_decision", {}),
        ),
        DEEP_REASONING_POLICY.profile.value,
    )
    return _with_route_decision_metadata(graph_payload, state.get("run_state"))
```

Change the task branch in `stream_agent_events_from_state()`:

```python
        graph_payload = _with_route_decision_metadata(graph_payload, run_state)
```

immediately before emitting `node_graph.created`.

- [ ] **Step 7: Run metadata and frontend reducer tests**

Run:

```powershell
python -m pytest -q python\tests\test_graph.py::test_task_graph_records_structured_route_decision_metadata python\tests\test_graph.py::test_research_graph_records_structured_route_decision_metadata python\tests\test_agent_routing_integration.py::test_task_message_creates_graph_with_planning_and_executable_nodes
npm run frontend:test -- src\app\backendEvents.test.ts
```

Expected:

```text
... passed
Test Files  1 passed
```

- [ ] **Step 8: Commit**

Run:

```powershell
git add python/agent_service/graph.py python/tests/test_graph.py python/tests/test_agent_routing_integration.py
git commit -m "feat: attach structured route metadata to graphs"
```

---

## Task 5: Router V2 Compatibility And Privacy Regression

**Files:**
- Modify: `python/tests/test_router_v2.py`
- Modify: `python/tests/test_graph.py`
- Modify: `python/tests/test_agent_routing_integration.py`
- Read: `python/agent_service/router_v2.py`
- Read: `python/agent_service/graph.py`

- [ ] **Step 1: Add route parity tests for existing edge cases**

Append to `python/tests/test_router_v2.py`:

```python
def test_how_to_question_with_task_verb_remains_local_inquiry() -> None:
    decision = deterministic_route(
        UserMessage(task_id="how-to", content="Can you explain how to update Python?")
    )

    assert decision.intent == "local_inquiry"
    assert decision.legacy_route["inquiry"]["mode"] == "local"


def test_markdown_conversion_with_attachment_remains_task() -> None:
    decision = deterministic_route(
        UserMessage(
            task_id="markdown-convert",
            content="Please convert this document to Markdown.",
            attachments=[
                Attachment(
                    attachment_id="a1",
                    name="input.docx",
                    path=r"D:\Project\input.docx",
                    size_bytes=64,
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            ],
        )
    )

    assert decision.intent == "task"
    assert decision.task_type == "document_processing"


def test_route_payload_does_not_include_raw_local_paths() -> None:
    local_path = r"C:\Users\Drew\Projects\Alita\python\agent_service\graph.py"
    decision = deterministic_route(
        UserMessage(
            task_id="path-privacy",
            content=f"Using {local_path}, what is the latest official Python release?",
        )
    )

    assert decision.intent == "web_simple_inquiry"
    assert local_path not in repr(decision.to_payload())
    assert local_path not in repr(decision.legacy_route)


def test_model_route_payload_does_not_include_raw_local_paths(monkeypatch) -> None:
    monkeypatch.setenv("ALITA_STRUCTURED_ROUTER", "1")
    local_path = r"C:\Users\Drew\Projects\Alita\python\agent_service\graph.py"
    client = FakeRouterModelClient(
        json.dumps(
            {
                "intent": "task",
                "confidence": 0.86,
                "task_type": "code_task",
                "missing_inputs": [],
                "required_permissions": ["read_project_files"],
                "tool_candidates": [local_path],
                "reason": f"Need to inspect {local_path}.",
            }
        )
    )

    decision = route_message(
        UserMessage(task_id="model-path-privacy", content="Can you improve this code?"),
        model_client=client,
    )

    assert decision.source == "model"
    assert client.calls
    assert local_path not in repr(client.calls)
    assert local_path not in repr(decision.to_payload())
    assert local_path not in repr(decision.legacy_route)
```

- [ ] **Step 2: Add integration test that model router is disabled by default**

Append to `python/tests/test_graph.py`:

```python
def test_structured_model_router_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALITA_STRUCTURED_ROUTER", raising=False)
    client = FakeModelClient(
        json.dumps(
            {
                "intent": "task",
                "confidence": 0.99,
                "task_type": "code_task",
                "missing_inputs": [],
                "required_permissions": [],
                "tool_candidates": [],
                "reason": "Would be task if model router were enabled.",
            }
        )
    )

    events = run_agent(
        UserMessage(task_id="default-router-off", content="hello"),
        model_client=client,
    )

    assert [event.type for event in events] == ["message.created"]
    assert client.calls
    assert events[0].payload["message"]["content"].startswith("{")
```

This proves the model client is used only for chat response, not for routing, when the feature flag is off.

- [ ] **Step 3: Add endpoint integration test for route metadata stability**

In `python/tests/test_agent_routing_integration.py`, add:

```python
def test_route_metadata_does_not_change_graph_created_event_shape() -> None:
    response = TestClient(app).post(
        "/agent/message",
        json={
            "task_id": "route-metadata-shape",
            "content": "Create a Python script that counts rows in a CSV file.",
            "attachments": [],
        },
    )

    assert response.status_code == 200
    events = response.json()
    assert [event["type"] for event in events] == ["node_graph.created"]
    graph = events[0]["payload"]["graph"]
    assert "routeDecision" in graph["metadata"]
    assert "graph" in events[0]["payload"]
    assert set(events[0].keys()) == {"type", "payload"}
```

- [ ] **Step 4: Run compatibility tests**

Run:

```powershell
python -m pytest -q python\tests\test_router_v2.py python\tests\test_intent.py python\tests\test_graph.py python\tests\test_agent_routing_integration.py
```

Expected:

```text
... passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/tests/test_router_v2.py python/tests/test_graph.py python/tests/test_agent_routing_integration.py
git commit -m "test: cover structured router compatibility"
```

---

## Task 6: Final Regression And Review

**Files:**
- Read: `python/agent_service/router_v2.py`
- Read: `python/agent_service/graph.py`
- Read: `python/agent_service/intent.py`
- Read: `python/agent_service/agent_run_state.py`
- Read: `python/tests/test_router_v2.py`
- Read: `python/tests/test_graph.py`

- [ ] **Step 1: Run Phase D focused Python tests**

Run:

```powershell
python -m pytest -q python\tests\test_router_v2.py python\tests\test_intent.py python\tests\test_graph.py python\tests\test_agent_routing_integration.py python\tests\test_app.py
```

Expected:

```text
... passed
```

- [ ] **Step 2: Run runtime boundary regression**

Run:

```powershell
python -m pytest -q python\tests\test_agent_run_state.py python\tests\test_execution.py python\tests\test_tool_gateway.py python\tests\test_execution_gateway_integration.py
```

Expected:

```text
... passed
```

- [ ] **Step 3: Run frontend event regression**

Run:

```powershell
npm run frontend:test -- src\features\task\useTaskEvents.test.ts src\app\backendEvents.test.ts
```

Expected:

```text
Test Files  2 passed
```

- [ ] **Step 4: Run full MVP verification**

Run:

```powershell
.\scripts\verify-mvp.ps1
```

Expected:

```text
MVP verification passed.
```

- [ ] **Step 5: Confirm no Phase E/G scope leaked in**

Run:

```powershell
rg -n "PlannerChain|ExecutionGraph|ReAct|react_controller|tool_calls|ToolCall|mcp" python\agent_service\router_v2.py python\agent_service\graph.py
```

Expected:

```text
```

No matches should appear except existing comments or import paths that predate Phase D. Do not implement planner chain, execution graph, ReAct, or MCP dynamic planning in Phase D.

- [ ] **Step 6: Confirm worktree cleanliness**

Run:

```powershell
git status --short --branch
```

Expected:

```text
## codex/agent-runtime-phase-a-security-hygiene
```

- [ ] **Step 7: Final code review**

Dispatch a final code review over the Phase D commit range. Use this prompt:

```text
Review Phase D Structured Router V2 implementation. Prioritize deterministic route parity, public API and event compatibility, feature-flag behavior for model routing, confidence threshold behavior, privacy of route metadata, graph feedback preservation, and whether the implementation avoids Planner Chain, dynamic tool calling, MCP planning, or ReAct scope.
```

Expected: reviewer returns no blocking findings. Fix any critical or important finding before finishing.

---

## Acceptance Criteria

Phase D is complete when all statements are true:

- `python/agent_service/router_v2.py` exists and is covered by `python/tests/test_router_v2.py`.
- `RouterV2Decision` provides typed intent, confidence, task type, missing inputs, permissions, tool candidates, reason, source, clarification state, and a legacy route payload.
- Existing deterministic behavior remains stable for chat, local inquiry, simple web inquiry, complex web inquiry, document tasks, weather, and missing inputs.
- Explicit research choices still convert complex web inquiry to quick answer or research graph exactly as before.
- Graph feedback remains handled before route planning and does not become a new task by accident.
- `AgentRunState` stores `structured_route_decision` without changing public endpoint schemas.
- `graph.py` dispatches by Router V2 decision while keeping old `AgentIntent` values and old event types.
- Task and research graph metadata includes `metadata.routeDecision` with safe structured route metadata.
- `ALITA_STRUCTURED_ROUTER` is off by default.
- When `ALITA_STRUCTURED_ROUTER=1`, valid high-confidence model JSON can override ambiguous deterministic routing.
- Medium-confidence model routes produce `input.required` with `missing=["clarification"]`.
- Low-confidence or malformed model output falls back to deterministic routing.
- Route metadata does not include raw local file paths or attachment paths.
- No tool calls, MCP calls, ReAct loops, planner chain, or execution graph are introduced in this phase.
- `.\scripts\verify-mvp.ps1` passes.

## Handoff Notes For Phase E

Phase E can now build a Planner Chain using `RouterV2Decision.task_type`, `tool_candidates`, `required_permissions`, and `confidence` as inputs. Phase E should not parse user text from scratch when Router V2 already produced structured routing metadata; it should consume the structured decision from `AgentRunState` and produce a validated graph through a planner protocol.
