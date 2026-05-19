from __future__ import annotations

from datetime import datetime, timezone
from collections.abc import Iterator
from typing import Literal, Protocol, TypedDict
from uuid import uuid4

from langgraph.graph import END, StateGraph

from agent_service.goal_spec import GoalSpec, parse_goal_spec
from agent_service.graph_compiler import compile_task_graph_to_node_graph
from agent_service.model_client import (
    ChatMessage as ModelChatMessage,
    LlamaCppModelClient,
    ModelRuntimeDisabled,
    ModelRuntimeRequestFailed,
)
from agent_service.schemas import AgentEvent, UserMessage
from agent_service.task_graph import build_document_task_graph


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
                    ),
                },
            )
        ],
    }


def build_graph(model_client: ModelClient | None = None):
    graph = StateGraph(AgentState)
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("request_required_inputs", request_required_inputs)
    graph.add_node("plan_node_graph", plan_node_graph)
    graph.add_node(
        "answer_with_model",
        lambda state: answer_with_model(state, model_client=model_client),
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
) -> AgentState:
    client = model_client or LlamaCppModelClient()

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
) -> list[AgentEvent]:
    app = build_graph(model_client=model_client)
    result = app.invoke({"message": message, "events": []})
    return result["events"]


def stream_agent_events(
    message: UserMessage,
    *,
    model_client: ModelClient | None = None,
) -> Iterator[AgentEvent]:
    intent = _classify_message(message)
    if intent != "chat":
        yield from run_agent(message, model_client=model_client)
        return

    client = model_client or LlamaCppModelClient()
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


def _create_document_graph(task_id: str, goal_spec: GoalSpec) -> dict:
    task_graph = build_document_task_graph(task_id, goal_spec)
    return compile_task_graph_to_node_graph(task_graph)


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
