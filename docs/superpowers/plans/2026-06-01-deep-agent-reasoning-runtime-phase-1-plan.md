# Deep Agent Reasoning Runtime Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every user message through a LangGraph-backed Agent Reasoning Gate, and route execution-graph requests into Deep Planning where graph nodes are compiled from a model-produced `PlanDraft` and are traceable to plan steps.

**Architecture:** Add a new Deep Agent Runtime graph that begins with a model-backed Reasoning Gate for every request. The graph follows LangGraph's official `StateGraph` pattern: nodes return partial state updates, routing is represented as graph edges or `Command`, clarification uses interrupt-compatible state, and streaming/UI events are emitted from real graph transitions. Legacy template planners are not used by the deep-planning path.

**Tech Stack:** Python 3.12, LangGraph `1.1.10`, Pydantic v2, FastAPI SSE event contracts, React/TypeScript canvas metadata rendering, pytest, Vitest.

---

## Official LangGraph Guidance To Follow

Read these official docs before editing code:

- Graph API and `StateGraph`: `https://docs.langchain.com/oss/python/langgraph/graph-api`
- Thinking in LangGraph: `https://docs.langchain.com/oss/python/langgraph/thinking-in-langgraph`
- Interrupts: `https://docs.langchain.com/oss/python/langgraph/interrupts`
- Persistence: `https://docs.langchain.com/oss/python/langgraph/persistence`
- Streaming: `https://docs.langchain.com/oss/python/langgraph/streaming`
- Frontend integration patterns: `https://docs.langchain.com/oss/javascript/langgraph/use-stream-react`

Implementation constraints derived from the docs:

- Use `StateGraph` as the control-flow owner, not manual `if/else` orchestration around the graph.
- Nodes return state updates; they do not mutate shared state in place.
- Use conditional edges or `Command(goto=..., update=...)` for decisions that both update state and route.
- Compile with a checkpointer once interrupt/resume is introduced. Phase 1 records clarification state and events, but full human resume can be added in Phase 2.
- Stream real graph events and state changes; the UI must not invent fake planning progress.

## Scope Check

The approved spec includes reasoning, planning, graph compile, graph review, execution, result verification, repair, and finalization. This plan implements the first working slice:

```text
User Message
  -> Reasoning Gate
  -> simple/bounded requests continue to existing answer/tool handling after the reasoning event
  -> graph_task requests:
       -> Build Context
       -> Deep Plan
       -> Review Plan
       -> Compile Agent Plan Graph
       -> Review Graph
       -> Present Graph
```

Execution repair and checkpoint-aware result correction are intentionally deferred to a later plan. This plan still keeps the design compatible with that later phase by recording plan provenance on the graph.

## File Structure

Create:

- `python/agent_service/deep_agent_models.py`
  Pydantic models for `ReasoningDecision`, `ThinkingStatus`, `PlanDraft`, `PlanReview`, `GraphReview`, and related step objects.

- `python/agent_service/deep_agent_planner.py`
  Model prompt assembly, JSON parsing, model-backed `ReasoningDecision`, bounded plan revision, deterministic plan review, and thinking-status normalization.

- `python/agent_service/deep_agent_graph_compile.py`
  Compiler from approved `PlanDraft` to `RunGraph`, plus graph review that proves graph nodes trace to plan steps.

- `python/agent_service/deep_agent_runtime_graph.py`
  LangGraph `StateGraph` wiring for reasoning, context, deep planning, review, compile, review graph, and present graph.

- `python/tests/test_deep_agent_models.py`
- `python/tests/test_deep_agent_planner.py`
- `python/tests/test_deep_agent_graph_compile.py`
- `python/tests/test_deep_agent_runtime_graph.py`
- `python/tests/test_agent_runtime_engine_deep_agent.py`

Modify:

- `python/agent_service/model_client.py`
  Add diagnostics for whether deep-thinking request parameters were sent and whether fallback was used.

- `python/agent_service/agent_runtime_engine.py`
  Route graph-task requests through `DeepAgentRuntimeGraph` instead of legacy task graph creation.

- `python/agent_service/schemas.py`
  Add optional per-node `metadata` field so plan-step provenance can be carried without overloading `summary`.

- `python/agent_service/app.py`
  Ensure planning events are not stripped from public API responses.

- `src/shared/types.ts`
  Add `AgentNode.metadata` and typed `PlanNodeProvenance` helpers.

- `src/shared/events.ts`
  Add planning event variants.

- `src/features/canvas/NodePopover.tsx`
  Render node plan provenance.

- `src/features/canvas/NodePopover.test.tsx`

Do not modify:

- `python/agent_service/task_planner.py` as a fallback.
- `python/agent_service/planner_chain.py` as a fallback.
- existing document/research execution internals in `execution.py`.

## Task 1: Structured Deep Agent Models

**Files:**

- Create: `python/agent_service/deep_agent_models.py`
- Test: `python/tests/test_deep_agent_models.py`

- [ ] **Step 1: Write failing model tests**

Create `python/tests/test_deep_agent_models.py`:

```python
import pytest
from pydantic import ValidationError

from agent_service.deep_agent_models import (
    GraphReview,
    PlanDraft,
    PlanReview,
    PlanStep,
    ReasoningDecision,
    ThinkingStatus,
)


def test_reasoning_decision_requires_explanation_and_next_action() -> None:
    decision = ReasoningDecision(
        task_id="task-1",
        task_understanding="User wants a contract risk report.",
        intent="task",
        complexity="graph_task",
        why_this_path="The request requires reading an attachment and producing a report.",
        confidence=0.91,
        needs_clarification=False,
        required_capabilities=["document.read", "model.reasoning"],
        next_action="deep_planning",
    )

    assert decision.next_action == "deep_planning"
    assert decision.required_capabilities == ["document.read", "model.reasoning"]


def test_plan_draft_requires_steps_and_success_criteria() -> None:
    draft = PlanDraft(
        plan_draft_id="plan-1",
        task_understanding="Analyze contract risk.",
        success_criteria=["Risks are grouped by severity.", "Final report has actions."],
        inputs=[{"kind": "attachment", "name": "contract.docx"}],
        assumptions=["The attached document is the contract to review."],
        missing_information=[],
        candidate_strategies=[
            {
                "strategyId": "strategy-risk-review",
                "summary": "Extract clauses, identify risks, and write a report.",
                "tradeoffs": ["Focused on legal/business risk, not legal advice."],
            }
        ],
        recommended_strategy="strategy-risk-review",
        steps=[
            PlanStep(
                step_id="step-read",
                title="Read contract",
                objective="Extract readable text from the uploaded contract.",
                rationale="Risk review requires clause-level text.",
                inputs=["contract.docx"],
                required_capabilities=["document.read"],
                expected_output="Normalized contract text.",
                verification_criteria=["Text output is non-empty."],
                depends_on=[],
            )
        ],
        required_capabilities=["document.read", "model.reasoning"],
        risks=["The contract may be scanned or unreadable."],
        verification_plan=["Confirm every risk cites a source clause."],
    )

    assert draft.steps[0].step_id == "step-read"
    assert draft.success_criteria[0] == "Risks are grouped by severity."


def test_plan_draft_rejects_empty_steps() -> None:
    with pytest.raises(ValidationError):
        PlanDraft(
            plan_draft_id="plan-empty",
            task_understanding="Analyze a document.",
            success_criteria=["Report exists."],
            inputs=[],
            assumptions=[],
            missing_information=[],
            candidate_strategies=[],
            recommended_strategy="",
            steps=[],
            required_capabilities=[],
            risks=[],
            verification_plan=[],
        )


def test_thinking_status_records_degraded_mode() -> None:
    status = ThinkingStatus(
        requested=True,
        model_policy="deep_reasoning",
        request_payload_had_thinking_params=True,
        enable_thinking_sent=True,
        preserve_thinking_sent=True,
        fallback_used="unsupported_request_body",
        effective_mode="degraded",
        raw_provider_status="HTTP 422",
    )

    assert status.effective_mode == "degraded"
    assert status.fallback_used == "unsupported_request_body"


def test_reviews_have_status_values() -> None:
    plan_review = PlanReview(
        status="approved",
        coverage_findings=[],
        missing_inputs=[],
        unsupported_capabilities=[],
        risk_findings=[],
        suggested_clarifying_question=None,
        revision_instructions=[],
    )
    graph_review = GraphReview(
        status="approved",
        findings=[],
        missing_plan_step_ids=[],
        extra_node_ids=[],
    )

    assert plan_review.status == "approved"
    assert graph_review.status == "approved"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_models.py -q
Pop-Location
```

Expected: fail with `ModuleNotFoundError: No module named 'agent_service.deep_agent_models'`.

- [ ] **Step 3: Add model implementation**

Create `python/agent_service/deep_agent_models.py`:

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


ReasoningComplexity = Literal["simple", "bounded_tool", "graph_task"]
ReasoningNextAction = Literal[
    "simple_answer",
    "tool_action",
    "clarification",
    "deep_planning",
]
ReviewStatus = Literal["approved", "needs_clarification", "invalid"]
GraphReviewStatus = Literal["approved", "invalid"]
ThinkingFallback = Literal[
    "none",
    "unsupported_request_body",
    "empty_reasoning_response",
    "provider_error",
]
ThinkingEffectiveMode = Literal["deep", "degraded", "unavailable"]


class ReasoningDecision(BaseModel):
    task_id: str
    task_understanding: str
    intent: str
    complexity: ReasoningComplexity
    why_this_path: str
    confidence: float = Field(ge=0.0, le=1.0)
    needs_clarification: bool
    required_capabilities: list[str] = Field(default_factory=list)
    next_action: ReasoningNextAction


class ThinkingStatus(BaseModel):
    requested: bool
    model_policy: str
    request_payload_had_thinking_params: bool
    enable_thinking_sent: bool
    preserve_thinking_sent: bool
    fallback_used: ThinkingFallback = "none"
    effective_mode: ThinkingEffectiveMode
    raw_provider_status: str | None = None


class CandidateStrategy(BaseModel):
    strategy_id: str = Field(alias="strategyId")
    summary: str
    tradeoffs: list[str] = Field(default_factory=list)


class PlanStep(BaseModel):
    step_id: str
    title: str
    objective: str
    rationale: str
    inputs: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    expected_output: str
    verification_criteria: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)


class PlanDraft(BaseModel):
    plan_draft_id: str
    task_understanding: str
    success_criteria: list[str]
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    candidate_strategies: list[CandidateStrategy] = Field(default_factory=list)
    recommended_strategy: str
    steps: list[PlanStep]
    required_capabilities: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    verification_plan: list[str] = Field(default_factory=list)

    @field_validator("success_criteria", "steps", "verification_plan")
    @classmethod
    def _must_not_be_empty(cls, value: list[Any]) -> list[Any]:
        if not value:
            raise ValueError("field must not be empty")
        return value


class PlanReview(BaseModel):
    status: ReviewStatus
    coverage_findings: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    unsupported_capabilities: list[str] = Field(default_factory=list)
    risk_findings: list[str] = Field(default_factory=list)
    suggested_clarifying_question: str | None = None
    revision_instructions: list[str] = Field(default_factory=list)


class GraphReview(BaseModel):
    status: GraphReviewStatus
    findings: list[str] = Field(default_factory=list)
    missing_plan_step_ids: list[str] = Field(default_factory=list)
    extra_node_ids: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run model tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_models.py -q
Pop-Location
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add python/agent_service/deep_agent_models.py python/tests/test_deep_agent_models.py
git commit -m "feat: add deep agent planning models"
```

## Task 2: Model Thinking Diagnostics

**Files:**

- Modify: `python/agent_service/model_client.py`
- Test: `python/tests/test_model_client.py`

- [ ] **Step 1: Add failing diagnostics tests**

Append to `python/tests/test_model_client.py`:

```python
def test_llama_chat_with_diagnostics_reports_deep_thinking_payload() -> None:
    calls: list[dict] = []

    def transport(url: str, payload: dict, timeout: float) -> dict:
        del url, timeout
        calls.append(payload)
        return {"choices": [{"message": {"content": "ok"}}]}

    client = LlamaCppModelClient(
        ModelClientConfig(enabled=True),
        transport=transport,
    )

    result = client.chat_with_diagnostics(
        [ChatMessage(role="user", content="Plan this deeply.")],
        policy=DEEP_REASONING_POLICY,
    )

    assert result.content == "ok"
    assert calls[0]["chat_template_kwargs"]["enable_thinking"] is True
    assert calls[0]["chat_template_kwargs"]["preserve_thinking"] is True
    assert result.diagnostics.request_payload_had_thinking_params is True
    assert result.diagnostics.fallback_used == "none"
    assert result.diagnostics.effective_mode == "deep"


def test_llama_chat_with_diagnostics_reports_unsupported_thinking_fallback() -> None:
    calls: list[dict] = []

    def transport(url: str, payload: dict, timeout: float) -> dict:
        del url, timeout
        calls.append(payload)
        if len(calls) == 1:
            raise ModelRuntimeRequestFailed("bad request", status_code=422)
        return {"choices": [{"message": {"content": "ok without thinking"}}]}

    client = LlamaCppModelClient(
        ModelClientConfig(enabled=True),
        transport=transport,
    )

    result = client.chat_with_diagnostics(
        [ChatMessage(role="user", content="Plan this deeply.")],
        policy=DEEP_REASONING_POLICY,
    )

    assert result.content == "ok without thinking"
    assert "chat_template_kwargs" in calls[0]
    assert "chat_template_kwargs" not in calls[1]
    assert result.diagnostics.request_payload_had_thinking_params is True
    assert result.diagnostics.fallback_used == "unsupported_request_body"
    assert result.diagnostics.effective_mode == "degraded"
    assert result.diagnostics.raw_provider_status == "bad request"
```

Add this import near the existing model-policy imports if it is not already present:

```python
from agent_service.model_policy import DEEP_REASONING_POLICY
```

- [ ] **Step 2: Run diagnostics tests to verify failure**

Run:

```powershell
Push-Location python
python -m pytest tests/test_model_client.py::test_llama_chat_with_diagnostics_reports_deep_thinking_payload tests/test_model_client.py::test_llama_chat_with_diagnostics_reports_unsupported_thinking_fallback -q
Pop-Location
```

Expected: fail because `LlamaCppModelClient` has no `chat_with_diagnostics`.

- [ ] **Step 3: Add diagnostics dataclasses and method**

Modify `python/agent_service/model_client.py`.

Add after `ChatWithToolsResponse`:

```python
@dataclass(frozen=True)
class ModelCallDiagnostics:
    request_payload_had_thinking_params: bool
    enable_thinking_sent: bool
    preserve_thinking_sent: bool
    fallback_used: Literal[
        "none",
        "unsupported_request_body",
        "empty_reasoning_response",
        "provider_error",
    ] = "none"
    effective_mode: Literal["deep", "degraded", "unavailable"] = "deep"
    raw_provider_status: str | None = None


@dataclass(frozen=True)
class ChatDiagnosticsResponse:
    content: str
    diagnostics: ModelCallDiagnostics
```

Add this method to `LlamaCppModelClient` immediately after `chat()`:

```python
    def chat_with_diagnostics(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ) -> ChatDiagnosticsResponse:
        if not self.config.enabled:
            raise ModelRuntimeDisabled("llama.cpp model runtime is not configured")

        payload = self._chat_payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            policy=policy,
        )
        extra_body = _policy_extra_body(policy) if policy is not None else {}
        endpoint = f"{self.config.base_url}/v1/chat/completions"
        try:
            response = self._transport(endpoint, payload, self.config.timeout_seconds)
            content = _extract_chat_content(response)
            if not content.strip():
                raise ModelRuntimeRequestFailed("llama.cpp returned an empty chat response")
            return ChatDiagnosticsResponse(
                content=content,
                diagnostics=_diagnostics_for_payload(
                    payload,
                    fallback_used="none",
                    raw_provider_status=None,
                ),
            )
        except ModelRuntimeRequestFailed as error:
            if not extra_body or not _should_retry_without_policy_extra_body(error):
                raise

            retry_payload = self._chat_payload(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
                policy=policy,
                include_policy_extra_body=False,
            )
            response = self._transport(endpoint, retry_payload, self.config.timeout_seconds)
            content = _extract_chat_content(response)
            if not content.strip():
                raise ModelRuntimeRequestFailed("llama.cpp returned an empty chat response")
            return ChatDiagnosticsResponse(
                content=content,
                diagnostics=_diagnostics_for_payload(
                    payload,
                    fallback_used="unsupported_request_body",
                    raw_provider_status=str(error),
                ),
            )
```

Add helper near `_policy_extra_body`:

```python
def _diagnostics_for_payload(
    payload: dict,
    *,
    fallback_used: Literal[
        "none",
        "unsupported_request_body",
        "empty_reasoning_response",
        "provider_error",
    ],
    raw_provider_status: str | None,
) -> ModelCallDiagnostics:
    chat_template_kwargs = payload.get("chat_template_kwargs")
    request_payload_had_thinking_params = isinstance(chat_template_kwargs, dict)
    enable_thinking_sent = bool(
        isinstance(chat_template_kwargs, dict)
        and chat_template_kwargs.get("enable_thinking") is True
    )
    preserve_thinking_sent = bool(
        isinstance(chat_template_kwargs, dict)
        and chat_template_kwargs.get("preserve_thinking") is True
    )
    effective_mode = "deep" if fallback_used == "none" else "degraded"
    return ModelCallDiagnostics(
        request_payload_had_thinking_params=request_payload_had_thinking_params,
        enable_thinking_sent=enable_thinking_sent,
        preserve_thinking_sent=preserve_thinking_sent,
        fallback_used=fallback_used,
        effective_mode=effective_mode,
        raw_provider_status=raw_provider_status,
    )
```

- [ ] **Step 4: Run diagnostics tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_model_client.py::test_llama_chat_with_diagnostics_reports_deep_thinking_payload tests/test_model_client.py::test_llama_chat_with_diagnostics_reports_unsupported_thinking_fallback -q
Pop-Location
```

Expected: both tests pass.

- [ ] **Step 5: Run model client suite**

Run:

```powershell
Push-Location python
python -m pytest tests/test_model_client.py -q
Pop-Location
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add python/agent_service/model_client.py python/tests/test_model_client.py
git commit -m "feat: record model thinking diagnostics"
```

## Task 3: Deep Planning Engine And Plan Review

**Files:**

- Create: `python/agent_service/deep_agent_planner.py`
- Test: `python/tests/test_deep_agent_planner.py`

- [ ] **Step 1: Write failing planner tests**

Create `python/tests/test_deep_agent_planner.py`:

```python
import json

import pytest

from agent_service.deep_agent_models import PlanDraft
from agent_service.deep_agent_planner import (
    DeepPlanningEngine,
    DeepPlanningError,
    ReasoningGateEngine,
    review_plan,
)
from agent_service.model_client import ChatDiagnosticsResponse, ModelCallDiagnostics
from agent_service.model_policy import ModelCallProfile
from agent_service.schemas import Attachment, UserMessage


class FakeDeepModel:
    def __init__(self, payload: dict | None = None, *, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls: list[dict] = []

    def chat_with_diagnostics(self, messages, *, policy=None, **kwargs):
        self.calls.append({"messages": messages, "policy": policy, "kwargs": kwargs})
        if self.error is not None:
            raise self.error
        return ChatDiagnosticsResponse(
            content=json.dumps(self.payload),
            diagnostics=ModelCallDiagnostics(
                request_payload_had_thinking_params=True,
                enable_thinking_sent=True,
                preserve_thinking_sent=True,
                fallback_used="none",
                effective_mode="deep",
            ),
        )


def _plan_payload(step_id: str = "step-read") -> dict:
    return {
        "plan_draft_id": "plan-contract-risk",
        "task_understanding": "Analyze the attached contract for risk.",
        "success_criteria": ["Risks are grouped by severity."],
        "inputs": [{"kind": "attachment", "name": "contract.docx"}],
        "assumptions": ["The attachment is the contract."],
        "missing_information": [],
        "candidate_strategies": [
            {
                "strategyId": "strategy-risk",
                "summary": "Read, analyze, and report risks.",
                "tradeoffs": ["Not legal advice."],
            }
        ],
        "recommended_strategy": "strategy-risk",
        "steps": [
            {
                "step_id": step_id,
                "title": "Read contract",
                "objective": "Extract contract text.",
                "rationale": "Risk analysis needs source text.",
                "inputs": ["contract.docx"],
                "required_capabilities": ["document.read"],
                "expected_output": "Contract text.",
                "verification_criteria": ["Text is non-empty."],
                "depends_on": [],
            }
        ],
        "required_capabilities": ["document.read", "model.reasoning"],
        "risks": ["Scanned PDFs may fail."],
        "verification_plan": ["Check risks cite source clauses."],
    }


def test_deep_planning_engine_calls_model_with_deep_reasoning_policy() -> None:
    model = FakeDeepModel(_plan_payload())
    engine = DeepPlanningEngine(model_client=model)

    result = engine.plan(
        UserMessage(
            task_id="task-contract",
            content="Analyze this contract for risk.",
            attachments=[
                Attachment(
                    attachment_id="att-1",
                    name="contract.docx",
                    path="D:/Docs/contract.docx",
                    size_bytes=100,
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            ],
        ),
        context_bundle={"tools": [{"toolId": "document.read_write"}]},
    )

    assert model.calls
    assert model.calls[0]["policy"].profile == ModelCallProfile.DEEP_REASONING
    assert result.plan_draft.steps[0].step_id == "step-read"
    assert result.thinking_status.effective_mode == "deep"


def test_reasoning_gate_engine_calls_model_and_parses_decision() -> None:
    model = FakeDeepModel(
        {
            "task_id": "task-gate",
            "task_understanding": "User wants a custom report.",
            "intent": "task",
            "complexity": "graph_task",
            "why_this_path": "The request requires a generated execution plan.",
            "confidence": 0.9,
            "needs_clarification": False,
            "required_capabilities": ["model.reasoning"],
            "next_action": "deep_planning",
        }
    )
    engine = ReasoningGateEngine(model_client=model)

    result = engine.decide(
        UserMessage(task_id="task-gate", content="Create a custom report."),
        context_bundle={"tools": []},
    )

    assert model.calls
    assert model.calls[0]["policy"].profile == ModelCallProfile.DEEP_REASONING
    assert result.intent == "task"
    assert result.next_action == "deep_planning"


def test_deep_planning_engine_rejects_invalid_json_without_template_fallback() -> None:
    model = FakeDeepModel({"not": "a plan"})
    engine = DeepPlanningEngine(model_client=model)

    with pytest.raises(DeepPlanningError, match="invalid_plan_json"):
        engine.plan(
            UserMessage(task_id="task-invalid", content="Analyze this document."),
            context_bundle={},
        )


def test_review_plan_blocks_missing_success_criteria() -> None:
    payload = _plan_payload()
    payload["success_criteria"] = []
    draft = PlanDraft.model_construct(**payload)

    review = review_plan(
        draft,
        available_capabilities={"document.read", "model.reasoning"},
    )

    assert review.status == "invalid"
    assert "missing_success_criteria" in review.coverage_findings


def test_review_plan_requests_clarification_for_declared_missing_information() -> None:
    payload = _plan_payload()
    payload["missing_information"] = ["preferred audience"]
    draft = PlanDraft.model_validate(payload)

    review = review_plan(
        draft,
        available_capabilities={"document.read", "model.reasoning"},
    )

    assert review.status == "needs_clarification"
    assert review.suggested_clarifying_question
    assert "preferred audience" in review.suggested_clarifying_question
```

- [ ] **Step 2: Run planner tests to verify failure**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_planner.py -q
Pop-Location
```

Expected: fail with `ModuleNotFoundError`.

- [ ] **Step 3: Implement planner**

Create `python/agent_service/deep_agent_planner.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError

from agent_service.deep_agent_models import (
    PlanDraft,
    PlanReview,
    ReasoningDecision,
    ThinkingStatus,
)
from agent_service.model_client import ChatMessage, ModelRuntimeRequestFailed
from agent_service.model_policy import DEEP_REASONING_POLICY
from agent_service.schemas import UserMessage


class DeepPlanningError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class DeepPlanningModel(Protocol):
    def chat_with_diagnostics(self, messages, *, policy=None, **kwargs):
        ...


class ReasoningGateEngine:
    def __init__(self, *, model_client: DeepPlanningModel) -> None:
        self._model_client = model_client

    def decide(
        self,
        message: UserMessage,
        *,
        context_bundle: dict[str, Any],
    ) -> ReasoningDecision:
        try:
            response = self._model_client.chat_with_diagnostics(
                [
                    ChatMessage(
                        role="system",
                        content=(
                            "You are Alita's reasoning gate. Return only strict JSON "
                            "matching the ReasoningDecision schema. Do not return markdown."
                        ),
                    ),
                    ChatMessage(
                        role="user",
                        content=_reasoning_prompt(message, context_bundle=context_bundle),
                    ),
                ],
                policy=DEEP_REASONING_POLICY,
            )
        except ModelRuntimeRequestFailed as error:
            raise DeepPlanningError("reasoning_unavailable", str(error)) from error

        try:
            payload = json.loads(response.content)
            return ReasoningDecision.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as error:
            raise DeepPlanningError("invalid_reasoning_json", str(error)) from error


@dataclass(frozen=True)
class DeepPlanningResult:
    plan_draft: PlanDraft
    thinking_status: ThinkingStatus
    raw_response: str


class DeepPlanningEngine:
    def __init__(self, *, model_client: DeepPlanningModel) -> None:
        self._model_client = model_client

    def plan(
        self,
        message: UserMessage,
        *,
        context_bundle: dict[str, Any],
        revision_instructions: list[str] | None = None,
    ) -> DeepPlanningResult:
        prompt = _planning_prompt(
            message,
            context_bundle=context_bundle,
            revision_instructions=revision_instructions or [],
        )
        try:
            response = self._model_client.chat_with_diagnostics(
                [
                    ChatMessage(
                        role="system",
                        content=(
                            "You are Alita's planning engine. Return only strict JSON "
                            "matching the PlanDraft schema. Do not return markdown."
                        ),
                    ),
                    ChatMessage(role="user", content=prompt),
                ],
                policy=DEEP_REASONING_POLICY,
            )
        except ModelRuntimeRequestFailed as error:
            raise DeepPlanningError("deep_planning_unavailable", str(error)) from error

        try:
            payload = json.loads(response.content)
            draft = PlanDraft.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as error:
            raise DeepPlanningError("invalid_plan_json", str(error)) from error

        diagnostics = response.diagnostics
        return DeepPlanningResult(
            plan_draft=draft,
            thinking_status=ThinkingStatus(
                requested=True,
                model_policy=DEEP_REASONING_POLICY.profile.value,
                request_payload_had_thinking_params=diagnostics.request_payload_had_thinking_params,
                enable_thinking_sent=diagnostics.enable_thinking_sent,
                preserve_thinking_sent=diagnostics.preserve_thinking_sent,
                fallback_used=diagnostics.fallback_used,
                effective_mode=diagnostics.effective_mode,
                raw_provider_status=diagnostics.raw_provider_status,
            ),
            raw_response=response.content,
        )


def review_plan(
    draft: PlanDraft,
    *,
    available_capabilities: set[str],
) -> PlanReview:
    coverage_findings: list[str] = []
    unsupported_capabilities = [
        capability
        for capability in draft.required_capabilities
        if capability not in available_capabilities
    ]
    if not draft.success_criteria:
        coverage_findings.append("missing_success_criteria")
    if not draft.steps:
        coverage_findings.append("missing_steps")
    for step in draft.steps:
        if not step.rationale.strip():
            coverage_findings.append(f"missing_rationale:{step.step_id}")
        if not step.expected_output.strip():
            coverage_findings.append(f"missing_expected_output:{step.step_id}")
        if not step.verification_criteria:
            coverage_findings.append(f"missing_verification:{step.step_id}")

    if draft.missing_information:
        return PlanReview(
            status="needs_clarification",
            coverage_findings=coverage_findings,
            missing_inputs=list(draft.missing_information),
            unsupported_capabilities=unsupported_capabilities,
            risk_findings=[],
            suggested_clarifying_question=(
                "请补充这些信息后我再生成执行图："
                + "；".join(draft.missing_information)
            ),
            revision_instructions=[],
        )

    if coverage_findings or unsupported_capabilities:
        return PlanReview(
            status="invalid",
            coverage_findings=coverage_findings,
            missing_inputs=[],
            unsupported_capabilities=unsupported_capabilities,
            risk_findings=[],
            suggested_clarifying_question=None,
            revision_instructions=[
                "Add concrete success criteria, step rationale, expected outputs, and verification criteria."
            ],
        )

    return PlanReview(
        status="approved",
        coverage_findings=[],
        missing_inputs=[],
        unsupported_capabilities=[],
        risk_findings=[],
        suggested_clarifying_question=None,
        revision_instructions=[],
    )


def _planning_prompt(
    message: UserMessage,
    *,
    context_bundle: dict[str, Any],
    revision_instructions: list[str],
) -> str:
    safe_attachments = [
        {
            "name": attachment.name,
            "mimeType": attachment.mime_type,
            "sizeBytes": attachment.size_bytes,
        }
        for attachment in message.attachments
    ]
    payload = {
        "taskId": message.task_id,
        "userMessage": message.content,
        "attachments": safe_attachments,
        "contextBundle": context_bundle,
        "revisionInstructions": revision_instructions,
        "requiredJsonKeys": [
            "plan_draft_id",
            "task_understanding",
            "success_criteria",
            "inputs",
            "assumptions",
            "missing_information",
            "candidate_strategies",
            "recommended_strategy",
            "steps",
            "required_capabilities",
            "risks",
            "verification_plan",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _reasoning_prompt(
    message: UserMessage,
    *,
    context_bundle: dict[str, Any],
) -> str:
    payload = {
        "taskId": message.task_id,
        "userMessage": message.content,
        "attachmentCount": len(message.attachments),
        "contextBundle": context_bundle,
        "allowedNextActions": [
            "simple_answer",
            "tool_action",
            "clarification",
            "deep_planning",
        ],
        "instruction": (
            "Classify the request and explain why. Use deep_planning only when an "
            "execution graph is needed. Use simple_answer for direct answers."
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: Run planner tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_planner.py -q
Pop-Location
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add python/agent_service/deep_agent_planner.py python/tests/test_deep_agent_planner.py
git commit -m "feat: add deep agent planning engine"
```

## Task 4: Agent Plan Graph Compiler And Review

**Files:**

- Modify: `python/agent_service/schemas.py`
- Create: `python/agent_service/deep_agent_graph_compile.py`
- Test: `python/tests/test_deep_agent_graph_compile.py`

- [ ] **Step 1: Write failing graph compile tests**

Create `python/tests/test_deep_agent_graph_compile.py`:

```python
from agent_service.deep_agent_graph_compile import (
    compile_agent_plan_graph,
    review_compiled_graph,
)
from agent_service.deep_agent_models import PlanDraft, PlanStep


def _draft(step_ids: list[str]) -> PlanDraft:
    return PlanDraft(
        plan_draft_id="plan-risk",
        task_understanding="Analyze contract risk.",
        success_criteria=["Report groups risks by severity."],
        inputs=[{"kind": "attachment", "name": "contract.docx"}],
        assumptions=[],
        missing_information=[],
        candidate_strategies=[],
        recommended_strategy="risk-review",
        steps=[
            PlanStep(
                step_id=step_id,
                title=f"Step {step_id}",
                objective=f"Objective {step_id}",
                rationale=f"Rationale {step_id}",
                inputs=[],
                required_capabilities=["model.reasoning"],
                expected_output=f"Output {step_id}",
                verification_criteria=[f"Verify {step_id}"],
                depends_on=step_ids[:index],
            )
            for index, step_id in enumerate(step_ids)
        ],
        required_capabilities=["model.reasoning"],
        risks=[],
        verification_plan=["Final report is non-empty."],
    )


def test_compile_agent_plan_graph_traces_every_node_to_plan_step() -> None:
    graph = compile_agent_plan_graph(
        _draft(["read", "analyze", "write"]),
        task_id="task-risk",
    )

    assert graph["metadata"]["generatedBy"] == "deep_agent_runtime"
    assert graph["metadata"]["sourcePlanDraftId"] == "plan-risk"
    assert [node["metadata"]["sourcePlanStepId"] for node in graph["nodes"]] == [
        "read",
        "analyze",
        "write",
    ]
    assert graph["nodes"][0]["metadata"]["rationale"] == "Rationale read"
    assert graph["nodes"][0]["metadata"]["expectedOutput"] == "Output read"
    assert graph["nodes"][0]["metadata"]["verificationCriteria"] == ["Verify read"]


def test_compile_agent_plan_graph_changes_when_plan_steps_change() -> None:
    first = compile_agent_plan_graph(_draft(["summary"]), task_id="task-summary")
    second = compile_agent_plan_graph(_draft(["extract", "compare"]), task_id="task-compare")

    assert [node["nodeId"] for node in first["nodes"]] == ["summary"]
    assert [node["nodeId"] for node in second["nodes"]] == ["extract", "compare"]


def test_review_compiled_graph_rejects_extra_node_without_plan_provenance() -> None:
    draft = _draft(["read"])
    graph = compile_agent_plan_graph(draft, task_id="task-risk")
    graph["nodes"].append(
        {
            "nodeId": "template-extra",
            "nodeType": "model",
            "displayName": "Template Extra",
            "status": "waiting",
            "inputPorts": [],
            "outputPorts": [],
            "dependencies": [],
            "modelRef": "local-task-reasoner",
            "summary": "Should not exist.",
            "createdBy": "agent",
            "artifactRefs": [],
            "retryCount": 0,
            "position": {"x": 100, "y": 0},
            "metadata": {},
        }
    )

    review = review_compiled_graph(draft, graph)

    assert review.status == "invalid"
    assert review.extra_node_ids == ["template-extra"]
```

- [ ] **Step 2: Run graph compile tests to verify failure**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_graph_compile.py -q
Pop-Location
```

Expected: fail with `ModuleNotFoundError`.

- [ ] **Step 3: Add optional node metadata schema**

Modify `GraphNode` in `python/agent_service/schemas.py` by adding this field after `position`:

```python
    metadata: dict[str, Any] = Field(default_factory=dict)
```

This is backward compatible because it has a default.

- [ ] **Step 4: Implement graph compiler**

Create `python/agent_service/deep_agent_graph_compile.py`:

```python
from __future__ import annotations

from agent_service.deep_agent_models import GraphReview, PlanDraft


def compile_agent_plan_graph(draft: PlanDraft, *, task_id: str) -> dict:
    nodes: list[dict] = []
    edges: list[dict] = []
    positions = _positions(len(draft.steps))
    step_ids = {step.step_id for step in draft.steps}

    for index, step in enumerate(draft.steps):
        dependencies = [dep for dep in step.depends_on if dep in step_ids]
        node_type = _node_type_for_capabilities(step.required_capabilities)
        node = {
            "nodeId": step.step_id,
            "nodeType": node_type,
            "displayName": step.title,
            "status": "waiting",
            "inputPorts": [],
            "outputPorts": [{"id": "output", "label": "输出", "dataType": "text"}],
            "dependencies": dependencies,
            "toolRef": _tool_ref_for_capabilities(step.required_capabilities),
            "modelRef": "local-task-reasoner" if node_type == "model" else None,
            "summary": step.objective,
            "createdBy": "agent",
            "artifactRefs": [],
            "retryCount": 0,
            "position": positions[index],
            "metadata": {
                "sourcePlanDraftId": draft.plan_draft_id,
                "sourcePlanStepId": step.step_id,
                "rationale": step.rationale,
                "expectedOutput": step.expected_output,
                "verificationCriteria": list(step.verification_criteria),
                "requiredCapabilities": list(step.required_capabilities),
            },
        }
        nodes.append({key: value for key, value in node.items() if value is not None})
        for dependency in dependencies:
            edges.append(
                {
                    "id": f"{dependency}->{step.step_id}",
                    "source": dependency,
                    "target": step.step_id,
                }
            )

    return {
        "graphId": f"{task_id}-agent-plan-graph",
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "generatedBy": "deep_agent_runtime",
            "sourcePlanDraftId": draft.plan_draft_id,
            "planningTraceId": f"{task_id}:{draft.plan_draft_id}",
            "modelPolicy": "deep_reasoning",
            "successCriteria": list(draft.success_criteria),
            "verificationPlan": list(draft.verification_plan),
        },
    }


def review_compiled_graph(draft: PlanDraft, graph: dict) -> GraphReview:
    step_ids = {step.step_id for step in draft.steps}
    represented_step_ids: set[str] = set()
    extra_node_ids: list[str] = []
    findings: list[str] = []

    for node in graph.get("nodes", []):
        metadata = node.get("metadata") or {}
        source_step_id = metadata.get("sourcePlanStepId")
        if source_step_id not in step_ids:
            extra_node_ids.append(str(node.get("nodeId") or "unknown"))
            continue
        represented_step_ids.add(str(source_step_id))
        if not metadata.get("rationale"):
            findings.append(f"missing_rationale:{node.get('nodeId')}")
        if not metadata.get("expectedOutput"):
            findings.append(f"missing_expected_output:{node.get('nodeId')}")
        if not metadata.get("verificationCriteria"):
            findings.append(f"missing_verification:{node.get('nodeId')}")

    missing_step_ids = sorted(step_ids - represented_step_ids)
    status = "approved" if not findings and not missing_step_ids and not extra_node_ids else "invalid"
    return GraphReview(
        status=status,
        findings=findings,
        missing_plan_step_ids=missing_step_ids,
        extra_node_ids=extra_node_ids,
    )


def _positions(count: int) -> list[dict[str, float]]:
    return [{"x": float(index * 260), "y": float((index % 2) * 120)} for index in range(count)]


def _node_type_for_capabilities(capabilities: list[str]) -> str:
    return "fixed_tool" if any(capability.startswith("document.") for capability in capabilities) else "model"


def _tool_ref_for_capabilities(capabilities: list[str]) -> str | None:
    if "document.read" in capabilities:
        return "document.read_write"
    if "document.convert.markdown" in capabilities:
        return "document.markitdown_convert"
    if "document.render.typst_pdf" in capabilities:
        return "document.typst_compile"
    return None
```

- [ ] **Step 5: Run graph compile tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_graph_compile.py -q
Pop-Location
```

Expected: all tests pass.

- [ ] **Step 6: Run schema-adjacent tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_graph.py tests/test_execution_graph.py -q
Pop-Location
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```powershell
git add python/agent_service/schemas.py python/agent_service/deep_agent_graph_compile.py python/tests/test_deep_agent_graph_compile.py
git commit -m "feat: compile agent plan graphs from plan drafts"
```

## Task 5: LangGraph Deep Agent Runtime Graph

**Files:**

- Create: `python/agent_service/deep_agent_runtime_graph.py`
- Test: `python/tests/test_deep_agent_runtime_graph.py`

- [ ] **Step 1: Write failing LangGraph runtime tests**

Create `python/tests/test_deep_agent_runtime_graph.py`:

```python
import json

from agent_service.deep_agent_runtime_graph import run_deep_agent_runtime
from agent_service.model_client import ChatDiagnosticsResponse, ModelCallDiagnostics
from agent_service.schemas import UserMessage


class FakeModel:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = payloads
        self.calls = 0

    def chat_with_diagnostics(self, messages, *, policy=None, **kwargs):
        del messages, policy, kwargs
        self.calls += 1
        payload = self.payloads[self.calls - 1]
        return ChatDiagnosticsResponse(
            content=json.dumps(payload),
            diagnostics=ModelCallDiagnostics(
                request_payload_had_thinking_params=True,
                enable_thinking_sent=True,
                preserve_thinking_sent=True,
                fallback_used="none",
                effective_mode="deep",
            ),
        )


def _reasoning_payload(next_action: str = "deep_planning") -> dict:
    return {
        "task_id": "task-deep",
        "task_understanding": "User wants a tailored report.",
        "intent": "task",
        "complexity": "graph_task" if next_action == "deep_planning" else "simple",
        "why_this_path": "The request should be reasoned before any action.",
        "confidence": 0.9,
        "needs_clarification": False,
        "required_capabilities": ["model.reasoning"],
        "next_action": next_action,
    }


def _payload(step_ids: list[str]) -> dict:
    return {
        "plan_draft_id": "plan-dynamic",
        "task_understanding": "Create a custom document report.",
        "success_criteria": ["The report matches the requested structure."],
        "inputs": [],
        "assumptions": [],
        "missing_information": [],
        "candidate_strategies": [],
        "recommended_strategy": "custom-plan",
        "steps": [
            {
                "step_id": step_id,
                "title": f"Step {step_id}",
                "objective": f"Do {step_id}",
                "rationale": f"Because {step_id} is needed.",
                "inputs": [],
                "required_capabilities": ["model.reasoning"],
                "expected_output": f"Output {step_id}",
                "verification_criteria": [f"Verify {step_id}"],
                "depends_on": step_ids[:index],
            }
            for index, step_id in enumerate(step_ids)
        ],
        "required_capabilities": ["model.reasoning"],
        "risks": [],
        "verification_plan": ["Check final answer."],
    }


def test_deep_agent_runtime_calls_model_and_emits_graph_from_plan() -> None:
    model = FakeModel([_reasoning_payload(), _payload(["understand", "write"])])

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-deep", content="Write a tailored report."),
        project_path="D:/Project/demo.alita",
        model_client=model,
    )

    assert model.calls == 2
    assert [event.type for event in events] == [
        "reasoning.decision_created",
        "planning.started",
        "planning.thinking_status",
        "planning.draft_created",
        "planning.review_completed",
        "planning.graph_compiled",
        "planning.graph_review_completed",
        "node_graph.created",
    ]
    graph = events[-1].payload["graph"]
    assert [node["nodeId"] for node in graph["nodes"]] == ["understand", "write"]
    assert graph["nodes"][0]["metadata"]["sourcePlanStepId"] == "understand"


def test_deep_agent_runtime_returns_clarification_without_graph() -> None:
    payload = _payload(["clarify"])
    payload["missing_information"] = ["target audience"]
    model = FakeModel([_reasoning_payload(), payload])

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-clarify", content="Make this into a report."),
        project_path="D:/Project/demo.alita",
        model_client=model,
    )

    assert model.calls == 2
    assert [event.type for event in events][-1] == "planning.clarification_required"
    assert all(event.type != "node_graph.created" for event in events)


def test_deep_agent_runtime_records_simple_reasoning_without_graph() -> None:
    model = FakeModel([_reasoning_payload("simple_answer")])

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-simple", content="Say hello."),
        project_path="D:/Project/demo.alita",
        model_client=model,
    )

    assert model.calls == 1
    assert [event.type for event in events] == [
        "reasoning.decision_created",
        "reasoning.completed",
    ]
    assert all(event.type != "node_graph.created" for event in events)
```

- [ ] **Step 2: Run runtime graph tests to verify failure**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_runtime_graph.py -q
Pop-Location
```

Expected: fail with `ModuleNotFoundError`.

- [ ] **Step 3: Implement LangGraph runtime graph**

Create `python/agent_service/deep_agent_runtime_graph.py`:

```python
from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Command

from agent_service.context_manager import build_context_bundle
from agent_service.deep_agent_graph_compile import (
    compile_agent_plan_graph,
    review_compiled_graph,
)
from agent_service.deep_agent_models import (
    GraphReview,
    PlanDraft,
    PlanReview,
    ReasoningDecision,
    ThinkingStatus,
)
from agent_service.deep_agent_planner import (
    DeepPlanningEngine,
    ReasoningGateEngine,
    review_plan,
)
from agent_service.goal_spec import parse_goal_spec
from agent_service.model_client import LlamaCppModelClient
from agent_service.schemas import AgentEvent, UserMessage
from agent_service.tool_execution import default_tool_packages_root
from agent_service.tool_registry import ToolRegistry


class DeepAgentRuntimeState(TypedDict, total=False):
    message: UserMessage
    project_path: str
    model_client: Any
    reasoning_decision: ReasoningDecision
    context_bundle: dict[str, Any]
    available_capabilities: set[str]
    plan_draft: PlanDraft
    thinking_status: ThinkingStatus
    plan_review: PlanReview
    compiled_graph: dict
    graph_review: GraphReview
    events: list[AgentEvent]


def run_deep_agent_runtime(
    message: UserMessage,
    *,
    project_path: str,
    model_client: Any | None = None,
) -> list[AgentEvent]:
    app = build_deep_agent_runtime_graph()
    result = app.invoke(
        {
            "message": message,
            "project_path": project_path,
            "model_client": model_client or LlamaCppModelClient(),
            "events": [],
        }
    )
    return list(result.get("events") or [])


def build_deep_agent_runtime_graph():
    graph = StateGraph(DeepAgentRuntimeState)
    graph.add_node("reasoning_gate", reasoning_gate)
    graph.add_node("build_context", build_context)
    graph.add_node("deep_plan", deep_plan)
    graph.add_node("review_plan", review_plan_node)
    graph.add_node("compile_agent_plan_graph", compile_agent_plan_graph_node)
    graph.add_node("review_graph", review_graph_node)
    graph.add_node("present_plan", present_plan)
    graph.add_node("clarify_required", clarify_required)
    graph.add_node("simple_reasoning_final", simple_reasoning_final)
    graph.set_entry_point("reasoning_gate")
    graph.add_edge("build_context", "deep_plan")
    graph.add_edge("deep_plan", "review_plan")
    graph.add_edge("compile_agent_plan_graph", "review_graph")
    graph.add_edge("review_graph", "present_plan")
    graph.add_edge("present_plan", END)
    graph.add_edge("clarify_required", END)
    graph.add_edge("simple_reasoning_final", END)
    return graph.compile()


def reasoning_gate(
    state: DeepAgentRuntimeState,
) -> Command[Literal["build_context", "clarify_required", "simple_reasoning_final"]]:
    decision = ReasoningGateEngine(model_client=state["model_client"]).decide(
        state["message"],
        context_bundle={},
    )
    events = [
        *state.get("events", []),
        AgentEvent(
            type="reasoning.decision_created",
            payload={"decision": decision.model_dump()},
        ),
    ]
    if decision.next_action == "clarification":
        return Command(
            update={
                "reasoning_decision": decision,
                "events": events,
                "pending_question": decision.why_this_path,
            },
            goto="clarify_required",
        )
    if decision.next_action != "deep_planning":
        return Command(
            update={"reasoning_decision": decision, "events": events},
            goto="simple_reasoning_final",
        )
    return Command(
        update={"reasoning_decision": decision, "events": events},
        goto="build_context",
    )


def build_context(state: DeepAgentRuntimeState) -> dict[str, Any]:
    message = state["message"]
    tool_registry = ToolRegistry.from_packages_root(default_tool_packages_root())
    goal_spec = parse_goal_spec(message)
    context = build_context_bundle(
        message=message,
        goal_spec=goal_spec,
        project_path=state["project_path"],
        tool_registry=tool_registry,
        memory_records=[],
        memory_store=None,
    )
    available_capabilities = {"model.reasoning", "document.read", "document.convert.markdown", "document.render.typst_pdf"}
    return {
        "context_bundle": context.model_dump() if hasattr(context, "model_dump") else dict(context),
        "available_capabilities": available_capabilities,
    }


def deep_plan(state: DeepAgentRuntimeState) -> dict[str, Any]:
    result = DeepPlanningEngine(model_client=state["model_client"]).plan(
        state["message"],
        context_bundle=state.get("context_bundle") or {},
    )
    return {
        "plan_draft": result.plan_draft,
        "thinking_status": result.thinking_status,
        "events": [
            *state.get("events", []),
            AgentEvent(
                type="planning.started",
                payload={"taskId": state["message"].task_id},
            ),
            AgentEvent(
                type="planning.thinking_status",
                payload={"thinkingStatus": result.thinking_status.model_dump()},
            ),
            AgentEvent(
                type="planning.draft_created",
                payload={"planDraft": result.plan_draft.model_dump()},
            ),
        ],
    }


def review_plan_node(
    state: DeepAgentRuntimeState,
) -> Command[Literal["compile_agent_plan_graph", "clarify_required"]]:
    review = review_plan(
        state["plan_draft"],
        available_capabilities=state.get("available_capabilities") or {"model.reasoning"},
    )
    events = [
        *state.get("events", []),
        AgentEvent(
            type="planning.review_completed",
            payload={"review": review.model_dump()},
        ),
    ]
    if review.status == "needs_clarification":
        return Command(
            update={"plan_review": review, "events": events},
            goto="clarify_required",
        )
    if review.status != "approved":
        return Command(
            update={
                "plan_review": review,
                "events": [
                    *events,
                    AgentEvent(
                        type="planning.failed",
                        payload={"reason": "plan_review_invalid", "review": review.model_dump()},
                    ),
                ],
            },
            goto="clarify_required",
        )
    return Command(
        update={"plan_review": review, "events": events},
        goto="compile_agent_plan_graph",
    )


def compile_agent_plan_graph_node(state: DeepAgentRuntimeState) -> dict[str, Any]:
    graph = compile_agent_plan_graph(
        state["plan_draft"],
        task_id=state["message"].task_id,
    )
    return {
        "compiled_graph": graph,
        "events": [
            *state.get("events", []),
            AgentEvent(
                type="planning.graph_compiled",
                payload={"graph": graph},
            ),
        ],
    }


def review_graph_node(state: DeepAgentRuntimeState) -> dict[str, Any]:
    review = review_compiled_graph(state["plan_draft"], state["compiled_graph"])
    return {
        "graph_review": review,
        "events": [
            *state.get("events", []),
            AgentEvent(
                type="planning.graph_review_completed",
                payload={"review": review.model_dump()},
            ),
        ],
    }


def present_plan(state: DeepAgentRuntimeState) -> dict[str, Any]:
    return {
        "events": [
            *state.get("events", []),
            AgentEvent(
                type="node_graph.created",
                payload={"graph": state["compiled_graph"]},
            ),
        ]
    }


def clarify_required(state: DeepAgentRuntimeState) -> dict[str, Any]:
    review = state.get("plan_review")
    prompt = (
        review.suggested_clarifying_question
        if review is not None and review.suggested_clarifying_question
        else "请补充任务目标或输入信息后我再生成执行图。"
    )
    return {
        "events": [
            *state.get("events", []),
            AgentEvent(
                type="planning.clarification_required",
                payload={"taskId": state["message"].task_id, "prompt": prompt},
            ),
        ]
    }


def simple_reasoning_final(state: DeepAgentRuntimeState) -> dict[str, Any]:
    return {
        "events": [
            *state.get("events", []),
            AgentEvent(
                type="reasoning.completed",
                payload={
                    "taskId": state["message"].task_id,
                    "nextAction": state["reasoning_decision"].next_action,
                },
            ),
        ]
    }
```

- [ ] **Step 4: Run runtime graph tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_runtime_graph.py -q
Pop-Location
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add python/agent_service/deep_agent_runtime_graph.py python/tests/test_deep_agent_runtime_graph.py
git commit -m "feat: add deep agent runtime graph"
```

## Task 6: Route All Messages Through Reasoning Gate

**Files:**

- Modify: `python/agent_service/agent_runtime_engine.py`
- Test: `python/tests/test_agent_runtime_engine_deep_agent.py`

- [ ] **Step 1: Write failing integration tests**

Create `python/tests/test_agent_runtime_engine_deep_agent.py`:

```python
import json

from agent_service.agent_run_state import AgentRunState
from agent_service.agent_runtime_engine import AgentRuntimeEngine
from agent_service.model_client import ChatDiagnosticsResponse, ModelCallDiagnostics
from agent_service.schemas import AgentEvent, UserMessage


class FakeDeepModel:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = payloads
        self.calls = 0

    def chat_with_diagnostics(self, messages, *, policy=None, **kwargs):
        del messages, policy, kwargs
        self.calls += 1
        payload = self.payloads[self.calls - 1]
        return ChatDiagnosticsResponse(
            content=json.dumps(payload),
            diagnostics=ModelCallDiagnostics(
                request_payload_had_thinking_params=True,
                enable_thinking_sent=True,
                preserve_thinking_sent=True,
                fallback_used="none",
                effective_mode="deep",
            ),
        )


def _reasoning_payload(next_action: str) -> dict:
    return {
        "task_id": "task-engine",
        "task_understanding": "Reason about the user request before acting.",
        "intent": "task",
        "complexity": "graph_task" if next_action == "deep_planning" else "simple",
        "why_this_path": "The request must pass through the Agent reasoning gate.",
        "confidence": 0.9,
        "needs_clarification": False,
        "required_capabilities": ["model.reasoning"],
        "next_action": next_action,
    }


def _plan_payload() -> dict:
    return {
        "plan_draft_id": "plan-engine",
        "task_understanding": "Create a custom report.",
        "success_criteria": ["Report is structured."],
        "inputs": [],
        "assumptions": [],
        "missing_information": [],
        "candidate_strategies": [],
        "recommended_strategy": "custom",
        "steps": [
            {
                "step_id": "draft",
                "title": "Draft report",
                "objective": "Write report.",
                "rationale": "The user requested a report.",
                "inputs": [],
                "required_capabilities": ["model.reasoning"],
                "expected_output": "Report draft.",
                "verification_criteria": ["Report has sections."],
                "depends_on": [],
            }
        ],
        "required_capabilities": ["model.reasoning"],
        "risks": [],
        "verification_plan": ["Check report sections."],
    }


def test_runtime_engine_task_request_uses_deep_agent_runtime_not_legacy_runner() -> None:
    legacy_calls: list[AgentRunState] = []

    def legacy_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_calls.append(run_state)
        raise AssertionError("legacy runner must not be used for task graph creation")

    model = FakeDeepModel([_reasoning_payload("deep_planning"), _plan_payload()])
    engine = AgentRuntimeEngine(route_runner=legacy_runner)
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-engine-deep",
            content="Create a structured report from my project notes.",
        )
    ).model_copy(update={"project_path": "D:/Project/demo.alita", "run_id": "run-deep"})

    result = engine.run_from_state(run_state, model_client=model)

    assert legacy_calls == []
    assert model.calls == 2
    assert [event.type for event in result.events][-1] == "node_graph.created"
    graph = result.events[-1].payload["graph"]
    assert graph["metadata"]["generatedBy"] == "deep_agent_runtime"
    assert graph["nodes"][0]["metadata"]["sourcePlanStepId"] == "draft"


def test_runtime_engine_simple_request_passes_reasoning_gate_before_legacy_answer() -> None:
    legacy_calls: list[AgentRunState] = []

    def legacy_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_calls.append(run_state)
        return [
            AgentEvent(
                type="message.created",
                payload={"message": {"content": "hello"}},
            )
        ]

    model = FakeDeepModel([_reasoning_payload("simple_answer")])
    engine = AgentRuntimeEngine(route_runner=legacy_runner)
    run_state = AgentRunState.from_user_message(
        UserMessage(task_id="task-simple-gate", content="Say hello.")
    ).model_copy(update={"project_path": "D:/Project/demo.alita", "run_id": "run-simple"})

    result = engine.run_from_state(run_state, model_client=model)

    assert model.calls == 1
    assert len(legacy_calls) == 1
    assert [event.type for event in result.events] == [
        "runtime.run_started",
        "reasoning.decision_created",
        "reasoning.completed",
        "runtime.state_delta",
        "message.created",
    ]
```

- [ ] **Step 2: Run integration test to verify failure**

Run:

```powershell
Push-Location python
python -m pytest tests/test_agent_runtime_engine_deep_agent.py -q
Pop-Location
```

Expected: fail because `AgentRuntimeEngine` does not yet call the Deep Agent Runtime reasoning gate before legacy handling.

- [ ] **Step 3: Modify engine task path**

In `python/agent_service/agent_runtime_engine.py`, import:

```python
from agent_service.deep_agent_runtime_graph import run_deep_agent_runtime
```

Update `run_from_state()` before `_legacy_route_and_plan(...)`:

```python
        deep_events = run_deep_agent_runtime(
            run_state.message,
            project_path=run_state.project_path or "project.alita",
            model_client=model_client,
        )
        if _deep_agent_finished_without_legacy(deep_events):
            next_state = started.state.model_copy(update={"stage": "plan"})
            self._write_state(next_state)
            return RuntimeEngineResult(
                state=next_state,
                events=[*started.events, *deep_events],
            )
        route_events, next_state = self._legacy_route_and_plan(
            started.state,
            run_state,
            model_client=model_client,
            search_provider=search_provider,
            weather_provider=weather_provider,
        )
        return RuntimeEngineResult(
            state=next_state,
            events=[*started.events, *deep_events, *route_events],
        )
```

Update `stream_from_state()` before streaming legacy runner:

```python
        deep_events = run_deep_agent_runtime(
            run_state.message,
            project_path=run_state.project_path or "project.alita",
            model_client=model_client,
        )
        for event in deep_events:
            yield event
        if _deep_agent_finished_without_legacy(deep_events):
            return
```

Add helper near `_message_from_state`:

```python
def _deep_agent_finished_without_legacy(events: list[AgentEvent]) -> bool:
    terminal_event_types = {
        "node_graph.created",
        "planning.clarification_required",
        "planning.failed",
    }
    return any(event.type in terminal_event_types for event in events)
```

Remove the old `route_events, next_state = self._legacy_route_and_plan(...)` block from its previous location in `run_from_state()` after adding the new block above. The method must call the deep runtime exactly once per user message.

- [ ] **Step 4: Run integration test**

Run:

```powershell
Push-Location python
python -m pytest tests/test_agent_runtime_engine_deep_agent.py -q
Pop-Location
```

Expected: pass.

- [ ] **Step 5: Run app and engine regression tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_agent_runtime_engine.py tests/test_app.py tests/test_graph.py -q
Pop-Location
```

Expected: existing tests pass after task-graph assertions are updated from legacy planner metadata to `graph["metadata"]["generatedBy"] == "deep_agent_runtime"` for user task graph creation cases. Do not change assertions for chat, web simple inquiry, weather, research choice, or graph execution.

- [ ] **Step 6: Commit**

```powershell
git add python/agent_service/agent_runtime_engine.py python/tests/test_agent_runtime_engine_deep_agent.py python/tests/test_agent_runtime_engine.py python/tests/test_app.py python/tests/test_graph.py
git commit -m "feat: route messages through deep agent reasoning gate"
```

## Task 7: Planning Event Contracts

**Files:**

- Modify: `src/shared/events.ts`
- Test: `src/app/backendEvents.test.ts`

- [ ] **Step 1: Add frontend event type tests**

Append to `src/app/backendEvents.test.ts`:

```ts
it("ignores planning events without dropping node graph events", () => {
  const state = reduceBackendEvents(
    {
      messages: [],
      graph: null,
      dirty: false,
      pendingResearchChoice: null,
      pendingGraphOverwriteChoice: null,
      activeRunId: null,
      runHistory: [],
      pendingRuntimeNotices: [],
      artifacts: [],
    },
    [
      {
        type: "planning.draft_created",
        payload: {
          planDraft: {
            plan_draft_id: "plan-1",
            task_understanding: "Write a report",
            steps: [],
          },
        },
      },
      {
        type: "node_graph.created",
        payload: {
          graph: {
            graphId: "graph-1",
            nodes: [],
            edges: [],
            metadata: {
              generatedBy: "deep_agent_runtime",
              sourcePlanDraftId: "plan-1",
            },
          },
        },
      },
    ] as BackendEvent[],
    createAssistantMessage,
  );

  expect(state.graph?.graphId).toBe("graph-1");
});
```

- [ ] **Step 2: Run frontend event test to verify failure**

Run:

```powershell
npm run frontend:test -- src/app/backendEvents.test.ts
```

Expected: TypeScript or Vitest fails because `planning.draft_created` is not part of `BackendEvent`.

- [ ] **Step 3: Add planning event union**

Modify `src/shared/events.ts` by adding these variants before `node_graph.created`:

```ts
  | {
      type: "reasoning.decision_created";
      payload: {
        decision: Record<string, unknown>;
      };
    }
  | {
      type: "planning.started";
      payload: {
        taskId: string;
      };
    }
  | {
      type: "planning.thinking_status";
      payload: {
        thinkingStatus: Record<string, unknown>;
      };
    }
  | {
      type: "planning.draft_created";
      payload: {
        planDraft: Record<string, unknown>;
      };
    }
  | {
      type: "planning.review_completed";
      payload: {
        review: Record<string, unknown>;
      };
    }
  | {
      type: "planning.graph_compiled";
      payload: {
        graph: NodeGraph;
      };
    }
  | {
      type: "planning.graph_review_completed";
      payload: {
        review: Record<string, unknown>;
      };
    }
  | {
      type: "planning.clarification_required";
      payload: {
        taskId: string;
        prompt: string;
      };
    }
  | {
      type: "planning.failed";
      payload: {
        reason: string;
        review?: Record<string, unknown>;
      };
    }
```

`backendEvents.ts` already returns `current` for unknown events, so no reducer branch is required for this phase.

- [ ] **Step 4: Run frontend event tests**

Run:

```powershell
npm run frontend:test -- src/app/backendEvents.test.ts
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add src/shared/events.ts src/app/backendEvents.test.ts
git commit -m "feat: add deep planning event contracts"
```

## Task 8: Canvas Node Provenance UI

**Files:**

- Modify: `src/shared/types.ts`
- Modify: `src/features/canvas/NodePopover.tsx`
- Test: `src/features/canvas/NodePopover.test.tsx`

- [ ] **Step 1: Add failing NodePopover provenance test**

Append to `src/features/canvas/NodePopover.test.tsx`:

```tsx
it("renders plan-step provenance when node metadata includes it", () => {
  const markup = renderPopover({
    ...toolNode,
    metadata: {
      sourcePlanDraftId: "plan-1",
      sourcePlanStepId: "step-risk",
      rationale: "Risk extraction is required by the user goal.",
      expectedOutput: "A severity-ranked risk list.",
      verificationCriteria: ["Every risk has a source clause."],
      requiredCapabilities: ["model.reasoning"],
    },
  });

  expect(markup).toContain("计划来源");
  expect(markup).toContain("step-risk");
  expect(markup).toContain("Risk extraction is required by the user goal.");
  expect(markup).toContain("A severity-ranked risk list.");
  expect(markup).toContain("Every risk has a source clause.");
});
```

- [ ] **Step 2: Run NodePopover test to verify failure**

Run:

```powershell
npm run frontend:test -- src/features/canvas/NodePopover.test.tsx
```

Expected: fail because provenance is not rendered.

- [ ] **Step 3: Add metadata type**

Modify `src/shared/types.ts` by adding:

```ts
export type PlanNodeProvenance = {
  sourcePlanDraftId?: string;
  sourcePlanStepId?: string;
  rationale?: string;
  expectedOutput?: string;
  verificationCriteria?: string[];
  requiredCapabilities?: string[];
};
```

Add to `AgentNode`:

```ts
  metadata?: Record<string, unknown> & PlanNodeProvenance;
```

- [ ] **Step 4: Render provenance in NodePopover**

Add helper in `src/features/canvas/NodePopover.tsx`:

```tsx
function renderStringList(values: unknown) {
  if (!Array.isArray(values) || values.length === 0) {
    return <span className="nodePopoverEmpty">无</span>;
  }

  return (
    <ul className="nodePopoverPortList">
      {values.map((value) => (
        <li key={String(value)}>{String(value)}</li>
      ))}
    </ul>
  );
}
```

Inside `<dl className="nodePopoverDetails">`, after the "AI 调用目的" block, add:

```tsx
        {node.metadata?.sourcePlanStepId ? (
          <>
            <div>
              <dt>计划来源</dt>
              <dd>{node.metadata.sourcePlanStepId}</dd>
            </div>
            {node.metadata.rationale ? (
              <div>
                <dt>推理依据</dt>
                <dd>{node.metadata.rationale}</dd>
              </div>
            ) : null}
            {node.metadata.expectedOutput ? (
              <div>
                <dt>预期输出</dt>
                <dd>{node.metadata.expectedOutput}</dd>
              </div>
            ) : null}
            <div>
              <dt>验证标准</dt>
              <dd>{renderStringList(node.metadata.verificationCriteria)}</dd>
            </div>
          </>
        ) : null}
```

- [ ] **Step 5: Run NodePopover test**

Run:

```powershell
npm run frontend:test -- src/features/canvas/NodePopover.test.tsx
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add src/shared/types.ts src/features/canvas/NodePopover.tsx src/features/canvas/NodePopover.test.tsx
git commit -m "feat: show agent plan provenance on canvas nodes"
```

## Task 9: Regression Gates And Template Bypass Audit

**Files:**

- Modify: `python/tests/test_agent_runtime_engine_deep_agent.py`

- [ ] **Step 1: Add explicit no-template monkeypatch test**

Append to `python/tests/test_agent_runtime_engine_deep_agent.py`:

```python
def test_deep_agent_runtime_does_not_call_legacy_task_planner(monkeypatch) -> None:
    import agent_service.task_planner as task_planner

    def blocked(*args, **kwargs):
        del args, kwargs
        raise AssertionError("legacy task planner must not be called")

    monkeypatch.setattr(task_planner, "analyze_task", blocked)

    model = FakeDeepModel([_reasoning_payload("deep_planning"), _plan_payload()])
    engine = AgentRuntimeEngine()
    run_state = AgentRunState.from_user_message(
        UserMessage(task_id="task-no-template", content="Analyze this document into a custom report.")
    ).model_copy(update={"project_path": "D:/Project/demo.alita", "run_id": "run-no-template"})

    result = engine.run_from_state(run_state, model_client=model)

    assert result.events[-1].type == "node_graph.created"
```

- [ ] **Step 2: Run backend focused gate**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_models.py tests/test_deep_agent_planner.py tests/test_deep_agent_graph_compile.py tests/test_deep_agent_runtime_graph.py tests/test_agent_runtime_engine_deep_agent.py -q
Pop-Location
```

Expected: all tests pass.

- [ ] **Step 3: Run broader backend gate**

Run:

```powershell
Push-Location python
python -m pytest tests/test_agent_runtime_engine.py tests/test_app.py tests/test_graph.py tests/test_model_client.py -q
Pop-Location
```

Expected: all tests pass. Task graph creation assertions should expect `generatedBy == "deep_agent_runtime"`; non-task assertions should remain unchanged.

- [ ] **Step 4: Run frontend focused gate**

Run:

```powershell
npm run frontend:test -- src/app/backendEvents.test.ts src/features/canvas/NodePopover.test.tsx
npm run frontend:typecheck
```

Expected: pass.

- [ ] **Step 5: Run full quick verification**

Run:

```powershell
git diff --check
Push-Location python
python -m pytest tests/test_deep_agent_models.py tests/test_deep_agent_planner.py tests/test_deep_agent_graph_compile.py tests/test_deep_agent_runtime_graph.py tests/test_agent_runtime_engine_deep_agent.py -q
Pop-Location
npm run frontend:typecheck
```

Expected: all commands pass.

- [ ] **Step 6: Commit**

```powershell
git add python/tests/test_agent_runtime_engine_deep_agent.py
git commit -m "test: guard deep agent planning against template fallback"
```

## Final Verification

Run:

```powershell
git diff --check
Push-Location python
python -m pytest tests/test_deep_agent_models.py tests/test_deep_agent_planner.py tests/test_deep_agent_graph_compile.py tests/test_deep_agent_runtime_graph.py tests/test_agent_runtime_engine_deep_agent.py tests/test_agent_runtime_engine.py tests/test_app.py tests/test_graph.py tests/test_model_client.py -q
Pop-Location
npm run frontend:typecheck
npm run frontend:test -- src/app/backendEvents.test.ts src/features/canvas/NodePopover.test.tsx
```

Expected:

- No whitespace errors.
- All Python focused and regression tests pass.
- TypeScript typecheck passes.
- Frontend focused tests pass.

## Definition Of Done

This phase is complete only when:

- Task graph creation through `AgentRuntimeEngine` calls deep planning model code.
- Every user message handled by `AgentRuntimeEngine.run_from_state()` calls the model-backed Reasoning Gate before legacy answer/tool handling or deep planning.
- A task graph is not produced if `PlanDraft` is invalid or clarification is needed.
- The generated graph has `metadata.generatedBy == "deep_agent_runtime"`.
- Every generated graph node has plan-step provenance metadata.
- Tests prove that changing `PlanDraft.steps` changes the graph.
- Tests prove legacy `task_planner` is not called by the Deep Agent Runtime path.
- Canvas node details show plan-step rationale, expected output, and verification criteria.

## Handoff Notes For Next Plan

The next implementation plan should add:

- LangGraph checkpointer-backed interrupt/resume for clarifications and user confirmation;
- execution connection from Agent Plan Graph to `run_graph_events()`;
- runtime-level final verification and bounded repair.
