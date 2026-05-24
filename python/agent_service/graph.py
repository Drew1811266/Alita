from __future__ import annotations

from datetime import datetime, timezone
from collections.abc import Iterator
from typing import Literal, Protocol, TypedDict
from uuid import uuid4

from langgraph.graph import END, StateGraph

from agent_service.context_manager import build_context_bundle
from agent_service.goal_spec import GoalSpec, parse_goal_spec
from agent_service.graph_compiler import compile_task_graph_to_node_graph
from agent_service.model_client import (
    AgentModelClientConfig,
    ChatMessage as ModelChatMessage,
    ModelRuntimeDisabled,
    ModelRuntimeRequestFailed,
    create_model_client,
)
from agent_service.model_sessions import (
    DEFAULT_MODEL_SESSION_REGISTRY,
    ModelSessionRegistry,
)
from agent_service.planner_v2 import PlannerV2
from agent_service.schemas import AgentEvent, AgentModelConfig, UserMessage
from agent_service.tool_execution import default_tool_packages_root
from agent_service.tool_registry import ToolRegistry


AgentIntent = Literal["chat", "missing_input", "document_task"]


class ModelClient(Protocol):
    def chat(
        self,
        messages: list[ModelChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str:
        ...

    def stream_chat(
        self,
        messages: list[ModelChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> Iterator[str]:
        ...


class AgentState(TypedDict, total=False):
    message: UserMessage
    events: list[AgentEvent]
    intent: AgentIntent
    goal_spec: GoalSpec


def _client_config_from_session(config: AgentModelConfig) -> AgentModelClientConfig:
    return AgentModelClientConfig(
        mode=config.mode,
        enabled=True,
        base_url=config.base_url,
        model=config.model,
        api_key=config.api_key,
        provider_display_name=config.display_name
        or config.provider_type
        or "API provider",
    )


def _model_client_for_message(
    message: UserMessage,
    *,
    model_client: ModelClient | None,
    model_client_factory=create_model_client,
    model_session_registry: ModelSessionRegistry = DEFAULT_MODEL_SESSION_REGISTRY,
) -> ModelClient:
    if model_client is not None:
        return model_client
    if message.model_session_id is not None:
        session_id = message.model_session_id.strip()
        if not session_id:
            raise ModelRuntimeDisabled("Agent model session expired or was not found")
        session_config = model_session_registry.consume(session_id)
        if session_config is None:
            raise ModelRuntimeDisabled("Agent model session expired or was not found")
        return model_client_factory(_client_config_from_session(session_config))
    return model_client_factory()


def classify_intent(state: AgentState) -> AgentState:
    goal_spec = parse_goal_spec(state["message"])
    return {
        **state,
        "goal_spec": goal_spec,
        "intent": _intent_from_goal_spec(goal_spec),
    }


def request_required_inputs(state: AgentState) -> AgentState:
    return {
        **state,
        "events": [
            AgentEvent(
                type="input.required",
                payload={
                    "prompt": "请把需要处理的文件添加到聊天框里。",
                    "missing": ["document_file"],
                },
            )
        ],
    }


def plan_node_graph(state: AgentState) -> AgentState:
    return {
        **state,
        "events": [
            AgentEvent(
                type="node_graph.created",
                payload={
                    "graph": _create_document_graph(
                        state["message"].task_id,
                        state["goal_spec"],
                        state["message"],
                    ),
                },
            )
        ],
    }


def build_graph(
    model_client: ModelClient | None = None,
    *,
    model_client_factory=create_model_client,
    model_session_registry: ModelSessionRegistry = DEFAULT_MODEL_SESSION_REGISTRY,
):
    graph = StateGraph(AgentState)
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("request_required_inputs", request_required_inputs)
    graph.add_node("plan_node_graph", plan_node_graph)
    graph.add_node(
        "answer_with_model",
        lambda state: answer_with_model(
            state,
            model_client=model_client,
            model_client_factory=model_client_factory,
            model_session_registry=model_session_registry,
        ),
    )
    graph.set_entry_point("classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        _route_intent,
        {
            "chat": "answer_with_model",
            "missing_input": "request_required_inputs",
            "document_task": "plan_node_graph",
        },
    )
    graph.add_edge("answer_with_model", END)
    graph.add_edge("request_required_inputs", END)
    graph.add_edge("plan_node_graph", END)
    return graph.compile()


def answer_with_model(
    state: AgentState,
    *,
    model_client: ModelClient | None = None,
    model_client_factory=create_model_client,
    model_session_registry: ModelSessionRegistry = DEFAULT_MODEL_SESSION_REGISTRY,
) -> AgentState:
    client = _model_client_for_message(
        state["message"],
        model_client=model_client,
        model_client_factory=model_client_factory,
        model_session_registry=model_session_registry,
    )

    try:
        content = client.chat(
            _build_model_messages(state["message"]),
            temperature=0.2,
            max_tokens=1024,
        )
    except ModelRuntimeDisabled:
        content = "本地模型暂未启用。请在首选项里设置默认 GGUF 模型，并确认 llama.cpp 服务已启动。"
    except ModelRuntimeRequestFailed as error:
        content = f"本地模型暂时没有返回可用结果：{error}"

    return {
        **state,
        "events": [
            AgentEvent(
                type="message.created",
                payload={"message": _assistant_message(content)},
            )
        ],
    }


def run_agent(
    message: UserMessage,
    *,
    model_client: ModelClient | None = None,
    model_client_factory=create_model_client,
    model_session_registry: ModelSessionRegistry = DEFAULT_MODEL_SESSION_REGISTRY,
) -> list[AgentEvent]:
    app = build_graph(
        model_client=model_client,
        model_client_factory=model_client_factory,
        model_session_registry=model_session_registry,
    )
    result = app.invoke({"message": message, "events": []})
    return result["events"]


def stream_agent_events(
    message: UserMessage,
    *,
    model_client: ModelClient | None = None,
    model_client_factory=create_model_client,
    model_session_registry: ModelSessionRegistry = DEFAULT_MODEL_SESSION_REGISTRY,
) -> Iterator[AgentEvent]:
    intent = _classify_message(message)
    if intent != "chat":
        yield from run_agent(
            message,
            model_client=model_client,
            model_client_factory=model_client_factory,
            model_session_registry=model_session_registry,
        )
        return

    client = _model_client_for_message(
        message,
        model_client=model_client,
        model_client_factory=model_client_factory,
        model_session_registry=model_session_registry,
    )
    assistant_message = _assistant_message("")
    message_id = assistant_message["messageId"]
    yield AgentEvent(
        type="message.started",
        payload={"message": assistant_message},
    )

    try:
        for delta in client.stream_chat(
            _build_model_messages(message),
            temperature=0.2,
            max_tokens=1024,
        ):
            yield AgentEvent(
                type="message.delta",
                payload={"messageId": message_id, "delta": delta},
            )
    except ModelRuntimeDisabled:
        yield AgentEvent(
            type="message.delta",
            payload={
                "messageId": message_id,
                "delta": "本地模型暂未启用。请在首选项里设置默认 GGUF 模型，并确认 llama.cpp 服务已启动。",
            },
        )
    except ModelRuntimeRequestFailed as error:
        yield AgentEvent(
            type="message.delta",
            payload={
                "messageId": message_id,
                "delta": f"本地模型暂时没有返回可用结果：{error}",
            },
        )

    yield AgentEvent(
        type="message.completed",
        payload={"messageId": message_id},
    )


def _route_intent(state: AgentState) -> AgentIntent:
    return state["intent"]


def _intent_from_goal_spec(goal_spec: GoalSpec) -> AgentIntent:
    if goal_spec.task_type == "document_processing" and goal_spec.missing_inputs:
        return "missing_input"

    if goal_spec.task_type == "document_processing":
        return "document_task"

    return "chat"


def _classify_message(message: UserMessage) -> AgentIntent:
    return _intent_from_goal_spec(parse_goal_spec(message))


def _build_model_messages(message: UserMessage) -> list[ModelChatMessage]:
    user_content = message.content.strip() or "请根据当前对话继续。"
    if message.attachments:
        attachment_names = "、".join(attachment.name for attachment in message.attachments)
        user_content = f"{user_content}\n\n当前项目附件：{attachment_names}"

    return [
        ModelChatMessage(
            role="system",
            content=(
                "你是 Alita中的本地 AI 助手。"
                "请用简洁、准确的中文回答用户。"
                "当前版本只负责对话、任务澄清和流程规划说明；"
                "不要声称已经完成未实际执行的工具操作。"
            ),
        ),
        ModelChatMessage(role="user", content=user_content),
    ]


def _assistant_message(content: str) -> dict:
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "messageId": f"assistant-{uuid4()}",
        "role": "assistant",
        "content": content,
        "attachments": [],
        "createdAt": created_at,
    }


def _create_document_graph(
    task_id: str, goal_spec: GoalSpec, message: UserMessage
) -> dict:
    tool_registry = ToolRegistry.from_packages_root(default_tool_packages_root())
    context = build_context_bundle(
        message=message,
        goal_spec=goal_spec,
        project_path="project.alita",
        tool_registry=tool_registry,
    )
    plan = PlannerV2(tool_registry=tool_registry).plan(
        task_id=task_id,
        goal_spec=goal_spec,
        context=context,
    )
    return compile_task_graph_to_node_graph(plan.task_graph)


def _node(
    *,
    node_id: str,
    node_type: str,
    display_name: str,
    status: str,
    input_ports: list[dict],
    output_ports: list[dict],
    dependencies: list[str],
    summary: str,
    position: dict,
    tool_ref: str | None = None,
    model_ref: str | None = None,
    script_review: dict | None = None,
) -> dict:
    node = {
        "nodeId": node_id,
        "nodeType": node_type,
        "displayName": display_name,
        "status": status,
        "inputPorts": input_ports,
        "outputPorts": output_ports,
        "dependencies": dependencies,
        "summary": summary,
        "createdBy": "agent",
        "artifactRefs": [],
        "retryCount": 0,
        "position": position,
    }
    if tool_ref:
        node["toolRef"] = tool_ref
    if model_ref:
        node["modelRef"] = model_ref
    if script_review is not None:
        node["scriptReview"] = script_review
    elif node_type == "temporary_placeholder":
        node["scriptReview"] = {
            "status": "not_reviewed",
            "summary": "临时脚本节点当前仅可审查，尚不能执行。",
            "permissions": [],
        }
    return node


def _port(port_id: str, label: str, data_type: str) -> dict:
    return {
        "id": port_id,
        "label": label,
        "dataType": data_type,
    }
