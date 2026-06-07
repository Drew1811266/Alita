from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from agent_service.agent_run_state import AgentRunState
from agent_service.agent_runtime_engine import (
    AgentRuntimeEngine,
    planning_resume_command_from_pending_choice,
)
from agent_service.runtime_store import RuntimeStore
from agent_service.model_client import ChatDiagnosticsResponse, ModelCallDiagnostics
from agent_service.schemas import AgentEvent, RunGraph, UserMessage


class FakeDeepModel:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.calls = 0

    def chat(self, messages, *, temperature=None, max_tokens=None, policy=None):
        del messages, temperature, max_tokens, policy
        return FakeSemanticModel("deep_planning").chat([])

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
                enable_thinking_value=True,
                preserve_thinking_value=True,
                fallback_used="none",
                effective_mode="deep",
            ),
        )


class FakeRouteCodeDeepModel(FakeDeepModel):
    def chat(self, messages, *, temperature=None, max_tokens=None, policy=None):
        del messages, temperature, max_tokens, policy
        return "G"


class FakeSemanticModel:
    def __init__(
        self,
        route: str,
        *,
        tool_candidates: list[str] | None = None,
        required_capabilities: list[str] | None = None,
    ):
        self.route = route
        self.tool_candidates = list(tool_candidates or [])
        self.required_capabilities = list(required_capabilities or [])
        self.calls = 0

    def chat(self, messages, *, temperature=None, max_tokens=None, policy=None):
        del messages, temperature, max_tokens, policy
        self.calls += 1
        return json.dumps(
            {
                "route": self.route,
                "intent": "runtime_test",
                "complexity": (
                    "simple" if self.route == "response_only" else "multi_step"
                ),
                "requiresGraph": self.route
                in {"graph_feedback", "deep_planning", "research_planning"},
                "requiresTools": self.route
                in {
                    "simple_tool_answer",
                    "web_answer",
                    "deep_planning",
                    "research_planning",
                },
                "requiresWeb": self.route in {"web_answer", "research_planning"},
                "requiresFiles": False,
                "requiresClarification": False,
                "language": "zh",
                "confidence": 0.94,
                "contextUsed": ["current_message"],
                "missingInputs": [],
                "requiredCapabilities": list(self.required_capabilities),
                "toolCandidates": list(self.tool_candidates),
                "reason": "语义路由测试。",
            }
        )


def _reasoning_payload(next_action: str) -> dict[str, Any]:
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


def _plan_payload() -> dict[str, Any]:
    return {
        "plan_draft_id": "plan-engine",
        "task_understanding": "Create a custom report.",
        "success_criteria": ["Report is structured."],
        "inputs": [],
        "assumptions": [],
        "missing_information": [],
        "candidate_strategies": [
            {
                "strategyId": "custom",
                "summary": "Create a dynamic report plan.",
                "tradeoffs": ["Requires model planning before graph creation."],
            }
        ],
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


def _existing_graph() -> RunGraph:
    return RunGraph(
        graphId="existing-graph",
        nodes=[
            {
                "nodeId": "task-analysis",
                "nodeType": "planning",
                "displayName": "Task Analysis",
                "status": "completed",
                "summary": "Existing plan.",
                "createdBy": "agent",
                "position": {"x": 0, "y": 0},
            }
        ],
        edges=[],
    )


def test_current_graph_feedback_bypasses_deep_agent_runtime() -> None:
    deep_calls: list[UserMessage] = []
    legacy_calls: list[AgentRunState] = []

    def deep_runtime(message: UserMessage, **kwargs):
        del kwargs
        deep_calls.append(message)
        raise AssertionError("graph feedback must be handled before Deep Agent")

    def legacy_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_calls.append(run_state)
        raise AssertionError("graph feedback must not use legacy response fallback")

    engine = AgentRuntimeEngine(
        route_runner=legacy_runner,
        deep_runtime_runner=deep_runtime,
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-engine-feedback",
            content="Add constraint: use only CSV sources.",
        ),
        current_graph=_existing_graph(),
    ).model_copy(
        update={
            "project_path": "D:/Project/demo.alita",
            "run_id": "run-feedback",
            "thread_id": "thread-feedback",
        }
    )

    result = engine.run_from_state(run_state)

    assert deep_calls == []
    assert legacy_calls == []
    assert [event.type for event in result.events] == [
        "runtime.run_started",
        "runtime.state_delta",
        "graph.replanned",
    ]
    assert result.events[1].payload["delta"]["decision"]["kind"] == "graph_feedback"
    assert result.state.stage == "plan"


def test_current_graph_question_does_not_preflight_as_graph_feedback() -> None:
    deep_calls: list[UserMessage] = []

    def deep_runtime(message: UserMessage, **kwargs):
        del kwargs
        deep_calls.append(message)
        return [
            AgentEvent(
                type="node_graph.created",
                payload={"graph": {"graphId": "deep-graph", "nodes": [], "edges": []}},
            )
        ]

    engine = AgentRuntimeEngine(deep_runtime_runner=deep_runtime)
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-engine-workflow-question",
            content="What workflow is best for this task?",
        ),
        current_graph=_existing_graph(),
    ).model_copy(
        update={
            "project_path": "D:/Project/demo.alita",
            "run_id": "run-workflow-question",
            "thread_id": "thread-workflow-question",
        }
    )

    result = engine.run_from_state(run_state)

    assert deep_calls == [run_state.message]
    assert [event.type for event in result.events] == [
        "runtime.run_started",
        "node_graph.created",
    ]


def test_semantic_graph_feedback_route_bypasses_deep_agent_runtime() -> None:
    deep_calls: list[UserMessage] = []

    def deep_runtime(message: UserMessage, **kwargs):
        del kwargs
        deep_calls.append(message)
        raise AssertionError("semantic graph_feedback must not enter Deep Agent")

    engine = AgentRuntimeEngine(deep_runtime_runner=deep_runtime)
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-semantic-graph-feedback",
            content="请把这个方案调整得更稳妥一些。",
        ),
        current_graph=_existing_graph(),
    ).model_copy(update={"project_path": "D:/Project/demo.alita"})

    result = engine.run_from_state(
        run_state,
        model_client=FakeSemanticModel("graph_feedback"),
    )

    assert deep_calls == []
    assert [event.type for event in result.events] == [
        "runtime.run_started",
        "runtime.state_delta",
        "graph.replanned",
    ]
    assert result.events[1].payload["delta"]["decision"]["kind"] == "graph_feedback"


def test_streaming_current_graph_feedback_bypasses_deep_agent_runtime(
    tmp_path,
) -> None:
    runtime_store = RuntimeStore(
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-stream-feedback-preflight",
    )
    deep_calls: list[UserMessage] = []
    legacy_calls: list[AgentRunState] = []

    def deep_stream(message: UserMessage, **kwargs):
        del kwargs
        deep_calls.append(message)
        raise AssertionError("graph feedback must be handled before Deep Agent")

    def legacy_stream(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_calls.append(run_state)
        raise AssertionError("graph feedback must not use legacy stream fallback")

    engine = AgentRuntimeEngine(
        deep_runtime_stream_runner=deep_stream,
        stream_runner=legacy_stream,
        runtime_store=runtime_store,
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-stream-feedback-preflight",
            content="Add constraint: use only CSV sources.",
        ),
        current_graph=_existing_graph(),
    ).model_copy(
        update={
            "project_path": str(tmp_path / "demo.alita"),
            "run_id": "run-stream-feedback-preflight",
            "thread_id": "thread-stream-feedback-preflight",
        }
    )

    events = list(engine.stream_from_state(run_state))

    assert deep_calls == []
    assert legacy_calls == []
    assert [event.type for event in events] == [
        "runtime.run_started",
        "runtime.state_delta",
        "graph.replanned",
    ]
    restored = runtime_store.read_state()
    assert restored is not None
    assert restored.stage == "plan"
    deltas = runtime_store.read_deltas()
    assert deltas[-1].decision["kind"] == "graph_feedback"


def test_empty_input_returns_deterministic_chinese_input_required() -> None:
    deep_calls: list[UserMessage] = []

    def deep_runtime(message: UserMessage, **kwargs):
        del kwargs
        deep_calls.append(message)
        raise AssertionError("empty input must not call Deep Agent")

    engine = AgentRuntimeEngine(deep_runtime_runner=deep_runtime)
    run_state = AgentRunState.from_user_message(
        UserMessage(task_id="task-empty", content="   ")
    ).model_copy(update={"project_path": "D:/Project/demo.alita", "run_id": "run-empty"})

    result = engine.run_from_state(run_state)

    assert deep_calls == []
    assert [event.type for event in result.events] == [
        "runtime.run_started",
        "runtime.state_delta",
        "input.required",
    ]
    assert result.events[-1].payload == {
        "prompt": "请先输入你想让我处理的问题或任务。",
        "missing": ["message"],
    }
    assert result.state.stage == "interrupted"


def test_missing_document_attachment_returns_deterministic_chinese_input_required() -> None:
    deep_calls: list[UserMessage] = []

    def deep_runtime(message: UserMessage, **kwargs):
        del kwargs
        deep_calls.append(message)
        raise AssertionError("missing document input must not call Deep Agent")

    engine = AgentRuntimeEngine(deep_runtime_runner=deep_runtime)
    run_state = AgentRunState.from_user_message(
        UserMessage(task_id="task-missing-doc", content="帮我把这个文档整理成中文报告")
    ).model_copy(
        update={"project_path": "D:/Project/demo.alita", "run_id": "run-missing-doc"}
    )

    result = engine.run_from_state(run_state)

    assert deep_calls == []
    assert [event.type for event in result.events] == [
        "runtime.run_started",
        "runtime.state_delta",
        "input.required",
    ]
    assert result.events[-1].payload == {
        "prompt": "请先添加需要处理的文档。",
        "missing": ["attachment"],
    }
    assert result.state.stage == "interrupted"


def test_plain_greeting_bypasses_deep_agent_and_uses_chat_route() -> None:
    deep_calls: list[UserMessage] = []
    legacy_calls: list[AgentRunState] = []

    def deep_runtime(message: UserMessage, **kwargs):
        del kwargs
        deep_calls.append(message)
        raise AssertionError("plain chat must not enter Deep Agent planning")

    def legacy_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_calls.append(run_state)
        return [
            AgentEvent(
                type="message.created",
                payload={
                    "message": {
                        "messageId": "assistant-hi",
                        "role": "assistant",
                        "content": "你好，有什么我可以帮你？",
                        "attachments": [],
                    }
                },
            )
        ]

    engine = AgentRuntimeEngine(
        route_runner=legacy_runner,
        deep_runtime_runner=deep_runtime,
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(task_id="task-greeting", content="你好")
    ).model_copy(
        update={"project_path": "D:/Project/demo.alita", "run_id": "run-greeting"}
    )

    result = engine.run_from_state(
        run_state,
        model_client=FakeSemanticModel("response_only"),
    )

    assert deep_calls == []
    assert len(legacy_calls) == 1
    assert legacy_calls[0].intent == "chat"
    assert [event.type for event in result.events] == [
        "runtime.run_started",
        "runtime.state_delta",
        "message.created",
    ]
    assert result.events[-1].payload["message"]["content"].startswith("你好")
    assert result.state.stage == "plan"


def test_streaming_plain_greeting_bypasses_deep_agent_and_uses_chat_route(
    tmp_path,
) -> None:
    runtime_store = RuntimeStore(
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-stream-greeting",
    )
    deep_calls: list[UserMessage] = []
    legacy_calls: list[AgentRunState] = []

    def deep_stream(message: UserMessage, **kwargs):
        del kwargs
        deep_calls.append(message)
        raise AssertionError("plain chat must not enter Deep Agent planning")

    def legacy_stream(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_calls.append(run_state)
        yield AgentEvent(
            type="message.created",
            payload={
                "message": {
                    "messageId": "assistant-hi",
                    "role": "assistant",
                    "content": "你好，有什么我可以帮你？",
                    "attachments": [],
                }
            },
        )

    engine = AgentRuntimeEngine(
        deep_runtime_stream_runner=deep_stream,
        stream_runner=legacy_stream,
        runtime_store=runtime_store,
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(task_id="task-stream-greeting", content="你好")
    ).model_copy(
        update={
            "project_path": str(tmp_path / "demo.alita"),
            "run_id": "run-stream-greeting",
            "thread_id": "thread-stream-greeting",
        }
    )

    events = list(
        engine.stream_from_state(
            run_state,
            model_client=FakeSemanticModel("response_only"),
        )
    )

    assert deep_calls == []
    assert len(legacy_calls) == 1
    assert legacy_calls[0].intent == "chat"
    assert [event.type for event in events] == [
        "runtime.run_started",
        "message.created",
        "runtime.state_delta",
    ]
    restored = runtime_store.read_state()
    assert restored is not None
    assert restored.stage == "plan"


def test_plain_greeting_route_is_decided_by_semantic_model_not_keyword(
    monkeypatch,
) -> None:
    def fail_deterministic_route(*args, **kwargs):
        del args, kwargs
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

    engine = AgentRuntimeEngine(
        route_runner=legacy_runner,
        deep_runtime_runner=deep_runtime,
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(task_id="semantic-runtime-hi", content="你好")
    ).model_copy(
        update={"project_path": "D:/Project/demo.alita", "run_id": "run-hi"}
    )

    result = engine.run_from_state(
        run_state,
        model_client=FakeSemanticModel("response_only"),
    )

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
    ).model_copy(
        update={"project_path": "D:/Project/demo.alita", "run_id": "run-task"}
    )

    result = engine.run_from_state(
        run_state,
        model_client=FakeSemanticModel("deep_planning"),
    )

    assert len(deep_calls) == 1
    assert [event.type for event in result.events] == [
        "runtime.run_started",
        "node_graph.created",
    ]


def test_semantic_research_planning_quick_answer_enters_deep_agent() -> None:
    deep_calls: list[UserMessage] = []
    legacy_calls: list[AgentRunState] = []

    def legacy_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_calls.append(run_state)
        raise AssertionError("semantic research_planning must not use legacy response")

    def deep_runtime(message: UserMessage, **kwargs):
        del kwargs
        deep_calls.append(message)
        return [
            AgentEvent(
                type="node_graph.created",
                payload={
                    "graph": {
                        "graphId": "semantic-research-plan",
                        "nodes": [],
                        "edges": [],
                        "metadata": {"generatedBy": "deep_agent_runtime"},
                    }
                },
            )
        ]

    engine = AgentRuntimeEngine(
        route_runner=legacy_runner,
        deep_runtime_runner=deep_runtime,
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(task_id="semantic-research", content="帮我快速调研这个主题"),
        inquiry_choice="quick_answer",
    ).model_copy(
        update={"project_path": "D:/Project/demo.alita", "run_id": "run-research"}
    )

    result = engine.run_from_state(
        run_state,
        model_client=FakeSemanticModel("research_planning"),
    )

    assert len(deep_calls) == 1
    assert legacy_calls == []
    assert [event.type for event in result.events] == [
        "runtime.run_started",
        "node_graph.created",
    ]


def test_semantic_response_only_missing_capability_routes_to_missing_input() -> None:
    deep_calls: list[UserMessage] = []

    def deep_runtime(message: UserMessage, **kwargs):
        del kwargs
        deep_calls.append(message)
        raise AssertionError("blocked semantic route must not enter Deep Agent")

    engine = AgentRuntimeEngine(deep_runtime_runner=deep_runtime)
    run_state = AgentRunState.from_user_message(
        UserMessage(task_id="semantic-capability-block", content="你好")
    ).model_copy(
        update={"project_path": "D:/Project/demo.alita", "run_id": "run-capability"}
    )

    result = engine.run_from_state(
        run_state,
        model_client=FakeSemanticModel(
            "response_only",
            tool_candidates=["unavailable.semantic.capability"],
        ),
    )

    assert deep_calls == []
    required_event = next(
        event for event in result.events if event.type == "input.required"
    )
    assert "当前任务需要尚未接入的能力" in required_event.payload["prompt"]
    assert required_event.payload["missing"] != ["message"]
    assert "clarification" in required_event.payload["missing"]
    assert "capability:unavailable.semantic.capability" in required_event.payload[
        "missing"
    ]
    assert result.state.stage == "plan"


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
    assert [event.type for event in result.events][-3:] == [
        "node_graph.created",
        "planning.confirmation_required",
        "planning.interrupted",
    ]
    graph_event = next(event for event in result.events if event.type == "node_graph.created")
    graph = graph_event.payload["graph"]
    assert graph["metadata"]["generatedBy"] == "deep_agent_runtime"
    assert graph["nodes"][0]["metadata"]["sourcePlanStepId"] == "draft"


def test_runtime_engine_reuses_semantic_deep_planning_decision_without_reasoning_gate() -> None:
    model = FakeRouteCodeDeepModel([_plan_payload()])
    engine = AgentRuntimeEngine()
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-semantic-direct-deep",
            content="帮我创建一个 Python 脚本，统计 CSV 文件的行数。",
        )
    ).model_copy(
        update={
            "project_path": "D:/Project/demo.alita",
            "run_id": "run-semantic-direct-deep",
        }
    )

    result = engine.run_from_state(run_state, model_client=model)

    assert model.calls == 1
    assert [event.type for event in result.events][:3] == [
        "runtime.run_started",
        "reasoning.decision_created",
        "planning.started",
    ]
    assert any(event.type == "node_graph.created" for event in result.events)


def test_runtime_engine_stream_uses_deep_agent_stream_runner_without_legacy_fallback(
    tmp_path,
) -> None:
    deep_stream_calls: list[dict[str, Any]] = []
    legacy_route_calls: list[AgentRunState] = []
    legacy_stream_calls: list[AgentRunState] = []
    runtime_store = RuntimeStore(
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-engine-stream",
    )

    def legacy_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_route_calls.append(run_state)
        raise AssertionError("legacy route runner must not be used")

    def legacy_stream_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_stream_calls.append(run_state)
        raise AssertionError("legacy stream runner must not be used")

    def deep_runtime_stream_runner(message: UserMessage, **kwargs):
        deep_stream_calls.append({"message": message, **kwargs})
        yield AgentEvent(
            type="reasoning.decision_created",
            payload={"decision": {"next_action": "deep_planning"}},
        )
        yield AgentEvent(
            type="node_graph.created",
            payload={
                "graph": {
                    "graphId": "graph-stream",
                    "nodes": [],
                    "edges": [],
                    "metadata": {"generatedBy": "deep_agent_runtime"},
                }
            },
        )

    engine = AgentRuntimeEngine(
        route_runner=legacy_runner,
        stream_runner=legacy_stream_runner,
        deep_runtime_stream_runner=deep_runtime_stream_runner,
        runtime_store=runtime_store,
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-engine-stream",
            content="Create a streamed deep planning graph.",
        )
    ).model_copy(
        update={
            "project_path": str(tmp_path / "demo.alita"),
            "run_id": "run-engine-stream",
            "thread_id": "thread-engine-stream",
        }
    )

    events = list(
        engine.stream_from_state(
            run_state,
            model_client=FakeSemanticModel("deep_planning"),
        )
    )

    assert legacy_route_calls == []
    assert legacy_stream_calls == []
    assert len(deep_stream_calls) == 1
    assert deep_stream_calls[0]["run_id"] == "run-engine-stream"
    assert deep_stream_calls[0]["thread_id"] == "thread-engine-stream"
    assert deep_stream_calls[0]["runtime_store"] is runtime_store
    assert deep_stream_calls[0]["resume_command"] is None
    assert [event.type for event in events] == [
        "runtime.run_started",
        "reasoning.decision_created",
        "node_graph.created",
    ]


def test_runtime_engine_forwards_disabled_tool_ids_to_deep_runtime() -> None:
    deep_calls: list[dict[str, Any]] = []

    def deep_runtime_runner(message: UserMessage, **kwargs):
        deep_calls.append({"message": message, **kwargs})
        return [
            AgentEvent(
                type="planning.failed",
                payload={
                    "taskId": message.task_id,
                    "errorCode": "plan_review_invalid",
                    "error": "disabled tool rejected",
                },
            )
        ]

    engine = AgentRuntimeEngine(deep_runtime_runner=deep_runtime_runner)
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-disabled-sync",
            content="Convert this document to markdown.",
        )
    ).model_copy(
        update={
            "project_path": "D:/Project/demo.alita",
            "run_id": "run-disabled-sync",
            "disabled_tool_ids": ["document.markitdown_convert"],
        }
    )

    result = engine.run_from_state(
        run_state,
        model_client=FakeSemanticModel("deep_planning"),
    )

    assert len(deep_calls) == 1
    assert deep_calls[0]["disabled_tool_ids"] == ["document.markitdown_convert"]
    assert result.events[-1].type == "planning.failed"


def test_runtime_engine_forwards_disabled_tool_ids_to_deep_stream_runtime() -> None:
    deep_stream_calls: list[dict[str, Any]] = []

    def deep_runtime_stream_runner(message: UserMessage, **kwargs):
        deep_stream_calls.append({"message": message, **kwargs})
        yield AgentEvent(
            type="planning.failed",
            payload={
                "taskId": message.task_id,
                "errorCode": "plan_review_invalid",
                "error": "disabled tool rejected",
            },
        )

    engine = AgentRuntimeEngine(
        deep_runtime_stream_runner=deep_runtime_stream_runner,
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-disabled-stream",
            content="Convert this document to markdown.",
        )
    ).model_copy(
        update={
            "project_path": "D:/Project/demo.alita",
            "run_id": "run-disabled-stream",
            "thread_id": "thread-disabled-stream",
            "disabled_tool_ids": ["internal:document.markitdown_convert"],
        }
    )

    events = list(
        engine.stream_from_state(
            run_state,
            model_client=FakeSemanticModel("deep_planning"),
        )
    )

    assert len(deep_stream_calls) == 1
    assert deep_stream_calls[0]["disabled_tool_ids"] == [
        "internal:document.markitdown_convert"
    ]
    assert events[-1].type == "planning.failed"


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
        UserMessage(
            task_id="task-simple-gate",
            content="Create a one sentence greeting for the user.",
        )
    ).model_copy(update={"project_path": "D:/Project/demo.alita", "run_id": "run-simple"})

    result = engine.run_from_state(run_state, model_client=model)

    assert model.calls == 1
    assert len(legacy_calls) == 1
    assert legacy_calls[0].intent == "chat"
    assert [event.type for event in result.events] == [
        "runtime.run_started",
        "reasoning.decision_created",
        "reasoning.completed",
        "runtime.state_delta",
        "message.created",
    ]


def test_deep_agent_incomplete_graph_task_stream_does_not_fall_back_to_legacy_graph() -> None:
    legacy_calls: list[AgentRunState] = []

    def legacy_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_calls.append(run_state)
        return [
            AgentEvent(
                type="node_graph.created",
                payload={
                    "graph": {
                        "graphId": "legacy-graph",
                        "nodes": [],
                        "edges": [],
                        "metadata": {"plannerChain": {"strategy": "legacy_task_planner"}},
                    }
                },
            )
        ]

    def incomplete_deep_runtime(message: UserMessage, **kwargs):
        del message, kwargs
        return [
            AgentEvent(
                type="reasoning.decision_created",
                payload={
                    "decision": {
                        "next_action": "deep_planning",
                        "complexity": "graph_task",
                    }
                },
            )
        ]

    engine = AgentRuntimeEngine(
        route_runner=legacy_runner,
        deep_runtime_runner=incomplete_deep_runtime,
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-incomplete-deep-agent",
            content="Create a multi-step project analysis graph.",
        )
    ).model_copy(
        update={"project_path": "D:/Project/demo.alita", "run_id": "run-incomplete"}
    )

    result = engine.run_from_state(
        run_state,
        model_client=FakeSemanticModel("deep_planning"),
    )

    assert legacy_calls == []
    assert [event.type for event in result.events] == [
        "runtime.run_started",
        "reasoning.decision_created",
        "runtime.state_delta",
        "runtime.deep_agent_product_path_blocked",
        "task.failed",
    ]
    failed = result.events[-1]
    assert failed.payload["errorCode"] == "deep_agent_product_path_incomplete"


def test_simple_answer_legacy_response_path_blocks_legacy_graph_events() -> None:
    legacy_calls: list[AgentRunState] = []

    def legacy_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_calls.append(run_state)
        return [
            AgentEvent(
                type="node_graph.created",
                payload={
                    "graph": {
                        "graphId": "legacy-simple-graph",
                        "nodes": [],
                        "edges": [],
                        "metadata": {"plannerChain": {"strategy": "legacy_task_planner"}},
                    }
                },
            )
        ]

    model = FakeDeepModel([_reasoning_payload("simple_answer")])
    engine = AgentRuntimeEngine(route_runner=legacy_runner)
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-simple-block-graph",
            content="Create a one sentence greeting for the user.",
        )
    ).model_copy(
        update={"project_path": "D:/Project/demo.alita", "run_id": "run-simple-block"}
    )

    result = engine.run_from_state(run_state, model_client=model)

    assert len(legacy_calls) == 1
    assert all(event.type != "node_graph.created" for event in result.events)
    assert result.events[-2].type == "runtime.legacy_graph_blocked"
    assert result.events[-1].type == "task.failed"
    assert result.events[-1].payload["errorCode"] == "legacy_graph_blocked"


def test_bounded_tool_action_does_not_fall_back_to_legacy_graph() -> None:
    legacy_calls: list[AgentRunState] = []

    def legacy_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_calls.append(run_state)
        return [
            AgentEvent(
                type="node_graph.created",
                payload={"graph": {"graphId": "legacy-tool-graph"}},
            )
        ]

    model = FakeDeepModel(
        [
            {
                **_reasoning_payload("tool_action"),
                "complexity": "bounded_tool",
            }
        ]
    )
    engine = AgentRuntimeEngine(route_runner=legacy_runner)
    run_state = AgentRunState.from_user_message(
        UserMessage(task_id="task-tool-action", content="Read this file and create a PDF.")
    ).model_copy(
        update={"project_path": "D:/Project/demo.alita", "run_id": "run-tool-action"}
    )

    result = engine.run_from_state(run_state, model_client=model)

    assert legacy_calls == []
    assert [event.type for event in result.events] == [
        "runtime.run_started",
        "reasoning.decision_created",
        "reasoning.completed",
        "runtime.state_delta",
        "runtime.deep_agent_product_path_blocked",
        "task.failed",
    ]
    assert result.events[-2].payload["reason"] == (
        "deep_agent_runtime_incomplete_for:tool_action"
    )
    assert result.events[-1].payload["errorCode"] == "deep_agent_product_path_incomplete"


def test_simple_answer_legacy_response_path_blocks_graph_feedback_events() -> None:
    def legacy_runner(run_state: AgentRunState, **kwargs):
        del run_state, kwargs
        return [
            AgentEvent(
                type="graph.replanned",
                payload={"graph": {"graphId": "legacy-replanned"}},
            ),
            AgentEvent(
                type="graph.overwrite_confirmation_required",
                payload={"taskId": "task-simple-block-feedback"},
            ),
        ]

    model = FakeDeepModel([_reasoning_payload("simple_answer")])
    engine = AgentRuntimeEngine(route_runner=legacy_runner)
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-simple-block-feedback",
            content="Create a one sentence greeting for the user.",
        )
    ).model_copy(
        update={"project_path": "D:/Project/demo.alita", "run_id": "run-feedback-block"}
    )

    result = engine.run_from_state(run_state, model_client=model)

    assert all(
        event.type
        not in {"graph.replanned", "graph.overwrite_confirmation_required"}
        for event in result.events
    )
    blocked = result.events[-2]
    assert blocked.type == "runtime.legacy_graph_blocked"
    assert blocked.payload["blockedEventTypes"] == [
        "graph.replanned",
        "graph.overwrite_confirmation_required",
    ]
    assert result.events[-1].payload["errorCode"] == "legacy_graph_blocked"


def test_deep_agent_planning_failure_does_not_call_legacy_route_runner() -> None:
    legacy_calls: list[AgentRunState] = []

    def legacy_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_calls.append(run_state)
        raise AssertionError("legacy route runner must not run after planning failure")

    def failing_deep_runtime(message: UserMessage, **kwargs):
        del kwargs
        return [
            AgentEvent(
                type="planning.failed",
                payload={
                    "taskId": message.task_id,
                    "runId": "run-planning-failed",
                    "threadId": "thread-planning-failed",
                    "errorCode": "deep_planning_unavailable",
                    "error": "model unavailable",
                },
            )
        ]

    engine = AgentRuntimeEngine(
        route_runner=legacy_runner,
        deep_runtime_runner=failing_deep_runtime,
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-planning-failed",
            content="Build a detailed execution graph.",
        )
    ).model_copy(
        update={
            "project_path": "D:/Project/demo.alita",
            "run_id": "run-planning-failed",
            "thread_id": "thread-planning-failed",
        }
    )

    result = engine.run_from_state(
        run_state,
        model_client=FakeSemanticModel("deep_planning"),
    )

    assert legacy_calls == []
    assert result.events[-1].type == "planning.failed"
    assert result.state.stage == "failed"


def test_streaming_deep_agent_planning_failure_persists_failed_state(tmp_path) -> None:
    legacy_stream_calls: list[AgentRunState] = []
    runtime_store = RuntimeStore(
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-stream-planning-failed",
    )

    def legacy_stream_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_stream_calls.append(run_state)
        raise AssertionError("legacy stream runner must not run after planning failure")

    def failing_deep_stream(message: UserMessage, **kwargs):
        del kwargs
        yield AgentEvent(
            type="planning.failed",
            payload={
                "taskId": message.task_id,
                "runId": "run-stream-planning-failed",
                "threadId": "thread-stream-planning-failed",
                "errorCode": "deep_planning_unavailable",
                "error": "model unavailable",
            },
        )

    engine = AgentRuntimeEngine(
        deep_runtime_stream_runner=failing_deep_stream,
        stream_runner=legacy_stream_runner,
        runtime_store=runtime_store,
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-stream-planning-failed",
            content="Build a detailed execution graph.",
        )
    ).model_copy(
        update={
            "project_path": str(tmp_path / "demo.alita"),
            "run_id": "run-stream-planning-failed",
            "thread_id": "thread-stream-planning-failed",
        }
    )

    events = list(
        engine.stream_from_state(
            run_state,
            model_client=FakeSemanticModel("deep_planning"),
        )
    )

    assert legacy_stream_calls == []
    assert events[-1].type == "planning.failed"
    restored = runtime_store.read_state()
    assert restored is not None
    assert restored.stage == "failed"


def test_streaming_deep_agent_incomplete_graph_task_blocks_and_persists_delta(
    tmp_path,
) -> None:
    legacy_stream_calls: list[AgentRunState] = []
    runtime_store = RuntimeStore(
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-stream-incomplete",
    )

    def legacy_stream_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_stream_calls.append(run_state)
        raise AssertionError("legacy stream runner must not run after incomplete graph task")

    def incomplete_deep_stream(message: UserMessage, **kwargs):
        del message, kwargs
        yield AgentEvent(
            type="reasoning.decision_created",
            payload={
                "decision": {
                    "next_action": "deep_planning",
                    "complexity": "graph_task",
                }
            },
        )

    engine = AgentRuntimeEngine(
        deep_runtime_stream_runner=incomplete_deep_stream,
        stream_runner=legacy_stream_runner,
        runtime_store=runtime_store,
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-stream-incomplete",
            content="Create a multi-step project analysis graph.",
        )
    ).model_copy(
        update={
            "project_path": str(tmp_path / "demo.alita"),
            "run_id": "run-stream-incomplete",
            "thread_id": "thread-stream-incomplete",
        }
    )

    events = list(
        engine.stream_from_state(
            run_state,
            model_client=FakeSemanticModel("deep_planning"),
        )
    )

    assert legacy_stream_calls == []
    assert [event.type for event in events] == [
        "runtime.run_started",
        "reasoning.decision_created",
        "runtime.state_delta",
        "runtime.deep_agent_product_path_blocked",
        "task.failed",
    ]
    assert events[-1].payload["errorCode"] == "deep_agent_product_path_incomplete"
    restored = runtime_store.read_state()
    assert restored is not None
    assert restored.stage == "failed"
    deltas = runtime_store.read_deltas()
    assert deltas[-1].stage_after == "failed"
    assert deltas[-1].decision["kind"] == "deep_agent_product_path_blocked"


def test_streaming_simple_answer_suppresses_legacy_graph_event_and_fails(
    tmp_path,
) -> None:
    runtime_store = RuntimeStore(
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-stream-simple-block",
    )

    def deep_stream(message: UserMessage, **kwargs):
        del message, kwargs
        yield AgentEvent(
            type="reasoning.completed",
            payload={"taskId": "task-stream-simple-block", "nextAction": "simple_answer"},
        )

    def legacy_stream_runner(run_state: AgentRunState, **kwargs):
        del run_state, kwargs
        yield AgentEvent(
            type="node_graph.created",
            payload={"graph": {"graphId": "legacy-stream-graph", "nodes": [], "edges": []}},
        )

    engine = AgentRuntimeEngine(
        deep_runtime_stream_runner=deep_stream,
        stream_runner=legacy_stream_runner,
        runtime_store=runtime_store,
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-stream-simple-block",
            content="Create a one sentence greeting for the user.",
        )
    ).model_copy(
        update={
            "project_path": str(tmp_path / "demo.alita"),
            "run_id": "run-stream-simple-block",
            "thread_id": "thread-stream-simple-block",
        }
    )

    events = list(
        engine.stream_from_state(
            run_state,
            model_client=FakeSemanticModel("deep_planning"),
        )
    )

    assert all(event.type != "node_graph.created" for event in events)
    assert [event.type for event in events] == [
        "runtime.run_started",
        "reasoning.completed",
        "runtime.state_delta",
        "runtime.legacy_graph_blocked",
        "task.failed",
    ]
    assert events[-1].payload["errorCode"] == "legacy_graph_blocked"
    restored = runtime_store.read_state()
    assert restored is not None
    assert restored.stage == "failed"


def test_streaming_simple_answer_suppresses_legacy_graph_feedback_and_fails(
    tmp_path,
) -> None:
    runtime_store = RuntimeStore(
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-stream-feedback-block",
    )

    def deep_stream(message: UserMessage, **kwargs):
        del message, kwargs
        yield AgentEvent(
            type="reasoning.completed",
            payload={
                "taskId": "task-stream-feedback-block",
                "nextAction": "simple_answer",
            },
        )

    def legacy_stream_runner(run_state: AgentRunState, **kwargs):
        del run_state, kwargs
        yield AgentEvent(
            type="graph.replanned",
            payload={"graph": {"graphId": "legacy-replanned"}},
        )
        yield AgentEvent(
            type="graph.overwrite_confirmation_required",
            payload={"taskId": "task-stream-feedback-block"},
        )

    engine = AgentRuntimeEngine(
        deep_runtime_stream_runner=deep_stream,
        stream_runner=legacy_stream_runner,
        runtime_store=runtime_store,
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-stream-feedback-block",
            content="Create a one sentence greeting for the user.",
        )
    ).model_copy(
        update={
            "project_path": str(tmp_path / "demo.alita"),
            "run_id": "run-stream-feedback-block",
            "thread_id": "thread-stream-feedback-block",
        }
    )

    events = list(
        engine.stream_from_state(
            run_state,
            model_client=FakeSemanticModel("deep_planning"),
        )
    )

    assert all(
        event.type
        not in {"graph.replanned", "graph.overwrite_confirmation_required"}
        for event in events
    )
    assert [event.type for event in events] == [
        "runtime.run_started",
        "reasoning.completed",
        "runtime.state_delta",
        "runtime.legacy_graph_blocked",
        "task.failed",
    ]
    assert events[-2].payload["blockedEventTypes"] == ["graph.replanned"]
    assert events[-1].payload["errorCode"] == "legacy_graph_blocked"
    restored = runtime_store.read_state()
    assert restored is not None
    assert restored.stage == "failed"


def test_deep_agent_runtime_does_not_call_legacy_task_planner(monkeypatch) -> None:
    import agent_service.planner_chain as planner_chain
    import agent_service.task_planner as task_planner

    def blocked(*args, **kwargs):
        del args, kwargs
        raise AssertionError("legacy task planner must not be called")

    monkeypatch.setattr(planner_chain, "analyze_task", blocked)
    monkeypatch.setattr(task_planner, "analyze_task", blocked)

    model = FakeDeepModel([_reasoning_payload("deep_planning"), _plan_payload()])
    engine = AgentRuntimeEngine()
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-no-template",
            content="Analyze this document into a custom report.",
        )
    ).model_copy(
        update={"project_path": "D:/Project/demo.alita", "run_id": "run-no-template"}
    )

    result = engine.run_from_state(run_state, model_client=model)

    assert result.events[-1].type == "planning.interrupted"
    graph_event = next(event for event in result.events if event.type == "node_graph.created")
    graph = graph_event.payload["graph"]
    assert graph["metadata"]["generatedBy"] == "deep_agent_runtime"


def test_planning_resume_command_from_pending_choice_builds_clarification_answer() -> None:
    command = planning_resume_command_from_pending_choice(
        {
            "kind": "planning.clarification",
            "threadId": "thread-clarify",
            "runId": "run-clarify",
            "answer": "The report is for executives.",
        }
    )

    assert command is not None
    assert command.kind == "clarification_answer"
    assert command.thread_id == "thread-clarify"
    assert command.run_id == "run-clarify"
    assert command.answer == "The report is for executives."


def test_planning_resume_command_uses_answer_fallback() -> None:
    command = planning_resume_command_from_pending_choice(
        {
            "kind": "planning.clarification",
            "threadId": "thread-clarify",
            "runId": "run-clarify",
        },
        answer_fallback="Use the executive audience.",
    )

    assert command is not None
    assert command.answer == "Use the executive audience."


def test_planning_resume_command_from_pending_choice_builds_confirmation_approval() -> None:
    command = planning_resume_command_from_pending_choice(
        {
            "kind": "planning.confirmation",
            "threadId": "thread-confirm",
            "runId": "run-confirm",
            "decision": "approve",
        }
    )

    assert command is not None
    assert command.kind == "confirmation"
    assert command.thread_id == "thread-confirm"
    assert command.run_id == "run-confirm"
    assert command.decision == "approve"
    assert command.revision_instructions == []


def test_planning_resume_command_requires_explicit_confirmation_decision() -> None:
    with pytest.raises(ValidationError, match="decision"):
        planning_resume_command_from_pending_choice(
            {
                "kind": "planning.confirmation",
                "threadId": "thread-confirm",
                "runId": "run-confirm",
            }
        )


def test_planning_resume_command_from_pending_choice_builds_confirmation_revision() -> None:
    command = planning_resume_command_from_pending_choice(
        {
            "kind": "planning.confirmation",
            "threadId": "thread-confirm",
            "runId": "run-confirm",
            "decision": "revise",
            "revisionInstructions": ["Add a verification step."],
        }
    )

    assert command is not None
    assert command.kind == "confirmation"
    assert command.decision == "revise"
    assert command.revision_instructions == ["Add a verification step."]


def test_planning_resume_command_rejects_malformed_pending_choice() -> None:
    with pytest.raises(ValidationError, match="threadId"):
        planning_resume_command_from_pending_choice(
            {
                "kind": "planning.clarification",
                "runId": "run-clarify",
                "answer": "The report is for executives.",
            }
        )
    with pytest.raises(ValidationError, match="decision"):
        planning_resume_command_from_pending_choice(
            {
                "kind": "planning.confirmation",
                "threadId": "thread-confirm",
                "runId": "run-confirm",
            }
        )


def test_runtime_engine_passes_planning_clarification_resume_to_deep_runtime(
    tmp_path,
) -> None:
    deep_calls: list[dict[str, Any]] = []
    legacy_calls: list[AgentRunState] = []
    runtime_store = RuntimeStore(
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-engine-clarify",
    )

    def legacy_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_calls.append(run_state)
        raise AssertionError("legacy runner must not be used for clarification resume")

    def deep_runtime_runner(message: UserMessage, **kwargs):
        deep_calls.append({"message": message, **kwargs})
        return [
            AgentEvent(
                type="node_graph.created",
                payload={
                    "graph": {
                        "graphId": "graph-clarify",
                        "nodes": [],
                        "edges": [],
                        "metadata": {"generatedBy": "deep_agent_runtime"},
                    }
                },
            )
        ]

    engine = AgentRuntimeEngine(
        route_runner=legacy_runner,
        deep_runtime_runner=deep_runtime_runner,
        runtime_store=runtime_store,
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-engine-clarify",
            content="The report is for executives.",
        ),
        pending_choice={
            "kind": "planning.clarification",
            "threadId": "thread-engine-clarify",
            "runId": "run-engine-clarify",
            "answer": "The report is for executives.",
        },
    ).model_copy(
        update={
            "project_path": str(tmp_path / "demo.alita"),
            "run_id": "run-engine-clarify",
            "thread_id": "thread-engine-clarify",
        }
    )

    result = engine.run_from_state(run_state)

    assert legacy_calls == []
    assert len(deep_calls) == 1
    assert deep_calls[0]["run_id"] == "run-engine-clarify"
    assert deep_calls[0]["thread_id"] == "thread-engine-clarify"
    assert deep_calls[0]["runtime_store"] is runtime_store
    assert deep_calls[0]["resume_command"] is not None
    assert deep_calls[0]["resume_command"].answer == "The report is for executives."
    assert result.events[-1].type == "node_graph.created"


def test_runtime_engine_passes_planning_confirmation_resume_to_deep_runtime(
    tmp_path,
) -> None:
    deep_calls: list[dict[str, Any]] = []
    legacy_calls: list[AgentRunState] = []
    runtime_store = RuntimeStore(
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-engine-confirm",
    )

    def legacy_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_calls.append(run_state)
        raise AssertionError("legacy runner must not be used for confirmation resume")

    def deep_runtime_runner(message: UserMessage, **kwargs):
        deep_calls.append({"message": message, **kwargs})
        return [
            AgentEvent(
                type="planning.cancelled",
                payload={
                    "taskId": message.task_id,
                    "runId": "run-engine-confirm",
                    "threadId": "thread-engine-confirm",
                    "graphId": "graph-confirm",
                },
            )
        ]

    engine = AgentRuntimeEngine(
        route_runner=legacy_runner,
        deep_runtime_runner=deep_runtime_runner,
        runtime_store=runtime_store,
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-engine-confirm",
            content="Revise with another verification step.",
        ),
        pending_choice={
            "kind": "planning.confirmation",
            "threadId": "thread-engine-confirm",
            "runId": "run-engine-confirm",
            "decision": "revise",
            "revisionInstructions": ["Add another verification step."],
        },
    ).model_copy(
        update={
            "project_path": str(tmp_path / "demo.alita"),
            "run_id": "run-engine-confirm",
            "thread_id": "thread-engine-confirm",
        }
    )

    result = engine.run_from_state(run_state)

    assert legacy_calls == []
    assert len(deep_calls) == 1
    command = deep_calls[0]["resume_command"]
    assert command is not None
    assert command.kind == "confirmation"
    assert command.decision == "revise"
    assert command.revision_instructions == ["Add another verification step."]
    assert result.events[-1].type == "planning.cancelled"
