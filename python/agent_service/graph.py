from __future__ import annotations

from datetime import datetime, timezone
from collections.abc import Iterator
import re
from typing import Literal, Protocol, TypedDict
from uuid import uuid4

from langgraph.graph import END, StateGraph

from agent_service.intent import (
    IntentKind,
    InquiryMode,
    RouteDecision,
    classify_route,
)
from agent_service.model_client import (
    ChatMessage as ModelChatMessage,
    LlamaCppModelClient,
    ModelRuntimeDisabled,
    ModelRuntimeRequestFailed,
)
from agent_service.plan_feedback import (
    GraphFeedbackKind,
    apply_graph_feedback,
    classify_graph_feedback,
)
from agent_service.schemas import AgentEvent, RunGraph, UserMessage
from agent_service.task_planner import (
    analyze_task,
    build_task_graph,
    resolve_tool_gaps,
    select_tools,
)
from agent_service.tool_execution import default_tool_packages_root
from agent_service.tool_registry import ToolRegistry
from agent_service.web_research import answer_simple_web_inquiry, build_research_graph
from agent_service.web_search import SearchProvider


AgentIntent = Literal[
    "chat",
    "local_inquiry",
    "web_simple_inquiry",
    "web_complex_choice",
    "web_complex_research_flow",
    "missing_input",
    "task",
]
InquiryChoice = Literal["quick_answer", "research_flow"]
RESEARCH_CHOICE_PROMPT = (
    "This question can be answered quickly or turned into a research flow. "
    "Choose how to proceed."
)


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
    route_decision: dict
    inquiry_choice: InquiryChoice
    current_graph: RunGraph
    has_run_history: bool
    artifact_refs: list[str]
    pending_choice: dict


def classify_intent(state: AgentState) -> AgentState:
    decision = classify_route(state["message"])
    return {
        **state,
        "intent": _compatible_intent(
            state["message"],
            decision,
            inquiry_choice=state.get("inquiry_choice"),
        ),
        "route_decision": decision.to_payload(),
    }


def request_required_inputs(state: AgentState) -> AgentState:
    missing_inputs = state.get("route_decision", {}).get("missing_inputs", [])
    if "document_file" in missing_inputs:
        prompt = "请把需要处理的文件添加到聊天框里。"
    else:
        prompt = "请先输入你想让我处理的问题或任务。"

    return {
        **state,
        "events": [
            AgentEvent(
                type="input.required",
                payload={
                    "prompt": prompt,
                    "missing": missing_inputs or ["message"],
                },
            )
        ],
    }


def plan_task_graph(state: AgentState) -> AgentState:
    message = state["message"]
    task_plan = analyze_task(message.content, message.attachments)
    task_plan.task_id = message.task_id
    registry = ToolRegistry.from_packages_root(default_tool_packages_root())
    task_plan.selected_tools = select_tools(
        task_plan.requirements,
        registry.enabled_tools(),
    )
    task_plan.tool_gaps = resolve_tool_gaps(
        task_plan.requirements,
        task_plan.selected_tools,
    )
    return {
        **state,
        "events": [
            AgentEvent(
                type="node_graph.created",
                payload={
                    "graph": build_task_graph(task_plan),
                },
            )
        ],
    }


def choose_research_mode(state: AgentState) -> AgentState:
    return {
        **state,
        "events": [
            AgentEvent(
                type="research.choice_required",
                payload={
                    "taskId": state["message"].task_id,
                    "prompt": RESEARCH_CHOICE_PROMPT,
                    "choices": [
                        {
                            "id": "quick_answer",
                            "label": "Quick answer",
                            "description": "Search the web now and return a concise sourced answer.",
                        },
                        {
                            "id": "research_flow",
                            "label": "Research flow",
                            "description": "Create a research graph for planning, source review, and report synthesis.",
                        },
                    ]
                },
            )
        ],
    }


def plan_research_graph(state: AgentState) -> AgentState:
    return {
        **state,
        "events": [
            AgentEvent(
                type="node_graph.created",
                payload={
                    "graph": build_research_graph(
                        state["message"],
                        state.get("route_decision", {}),
                    ),
                },
            )
        ],
    }


def build_graph(
    model_client: ModelClient | None = None,
    *,
    search_provider: SearchProvider | None = None,
    inquiry_choice: InquiryChoice | None = None,
):
    graph = StateGraph(AgentState)
    graph.add_node(
        "classify_intent",
        lambda state: classify_intent(
            {
                **state,
                "inquiry_choice": state.get("inquiry_choice") or inquiry_choice,
            }
        ),
    )
    graph.add_node("request_required_inputs", request_required_inputs)
    graph.add_node("plan_task_graph", plan_task_graph)
    graph.add_node("choose_research_mode", choose_research_mode)
    graph.add_node("plan_research_graph", plan_research_graph)
    graph.add_node(
        "answer_with_web",
        lambda state: answer_with_web(state, search_provider=search_provider),
    )
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
            "local_inquiry": "answer_with_model",
            "web_simple_inquiry": "answer_with_web",
            "web_complex_choice": "choose_research_mode",
            "web_complex_research_flow": "plan_research_graph",
            "missing_input": "request_required_inputs",
            "task": "plan_task_graph",
        },
    )
    graph.add_edge("answer_with_model", END)
    graph.add_edge("answer_with_web", END)
    graph.add_edge("choose_research_mode", END)
    graph.add_edge("plan_research_graph", END)
    graph.add_edge("request_required_inputs", END)
    graph.add_edge("plan_task_graph", END)
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


def answer_with_web(
    state: AgentState,
    *,
    search_provider: SearchProvider | None = None,
) -> AgentState:
    return {
        **state,
        "events": [
            answer_simple_web_inquiry(
                state["message"],
                state.get("route_decision", {}),
                search_provider=search_provider,
            )
        ],
    }


def run_agent(
    message: UserMessage,
    *,
    model_client: ModelClient | None = None,
    search_provider: SearchProvider | None = None,
    inquiry_choice: InquiryChoice | None = None,
    current_graph: RunGraph | None = None,
    has_run_history: bool = False,
    artifact_refs: list[str] | None = None,
    pending_choice: dict | None = None,
) -> list[AgentEvent]:
    if _should_handle_graph_feedback(
        message,
        current_graph,
        pending_choice=pending_choice,
    ):
        return [
            apply_graph_feedback(
                message,
                current_graph,
                has_run_history=has_run_history,
                artifact_refs=artifact_refs,
                pending_choice=pending_choice,
            )
        ]

    app = build_graph(
        model_client=model_client,
        search_provider=search_provider,
        inquiry_choice=inquiry_choice,
    )
    result = app.invoke(
        {"message": message, "events": [], "inquiry_choice": inquiry_choice}
    )
    return result["events"]


def stream_agent_events(
    message: UserMessage,
    *,
    model_client: ModelClient | None = None,
    search_provider: SearchProvider | None = None,
    inquiry_choice: InquiryChoice | None = None,
    current_graph: RunGraph | None = None,
    has_run_history: bool = False,
    artifact_refs: list[str] | None = None,
    pending_choice: dict | None = None,
) -> Iterator[AgentEvent]:
    if _should_handle_graph_feedback(
        message,
        current_graph,
        pending_choice=pending_choice,
    ):
        yield apply_graph_feedback(
            message,
            current_graph,
            has_run_history=has_run_history,
            artifact_refs=artifact_refs,
            pending_choice=pending_choice,
        )
        return

    decision = classify_route(message)
    intent = _compatible_intent(message, decision, inquiry_choice=inquiry_choice)
    if intent not in {"chat", "local_inquiry"}:
        yield from run_agent(
            message,
            model_client=model_client,
            search_provider=search_provider,
            inquiry_choice=inquiry_choice,
        )
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

    route_decision = classify_route(message)
    feedback_decision = classify_graph_feedback(message.content, current_graph)
    if feedback_decision.kind == GraphFeedbackKind.NEW_TASK:
        return False
    if feedback_decision.kind in {
        GraphFeedbackKind.LOCAL_MODIFICATION,
        GraphFeedbackKind.FULL_REPLAN,
    }:
        return True
    if _is_explicit_graph_constraint_feedback(message.content):
        return True
    if route_decision.intent.kind == IntentKind.INQUIRY:
        return False
    if route_decision.intent.kind == IntentKind.CHAT:
        return False
    return True


def _is_explicit_graph_constraint_feedback(content: str) -> bool:
    normalized = content.strip().lower()
    graph_referential = any(
        phrase in normalized
        for phrase in (
            "for this graph",
            "for the graph",
            "for the current graph",
            "current graph",
            "this flow",
            "in this flow",
            "for this flow",
            "this plan",
            "for this plan",
            "the plan",
            "workflow",
        )
    )
    if graph_referential:
        return True

    if re.match(r"^(what|why|how|when|where|which|who|can you explain)\b", normalized):
        return False

    return re.match(
        r"^(please\s+)?("
        r"(add|set|apply)\s+(the\s+|this\s+|a\s+)?constraint\b"
        r"|use\s+.+\b(sources|style|order)\b"
        r"|constraint\s*:"
        r")",
        normalized,
    ) is not None


def _route_intent(state: AgentState) -> AgentIntent:
    return state["intent"]


def _classify_message(message: UserMessage) -> AgentIntent:
    return _compatible_intent(message, classify_route(message))


def _compatible_intent(
    message: UserMessage,
    decision: RouteDecision,
    *,
    inquiry_choice: InquiryChoice | None = None,
) -> AgentIntent:
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


def _create_document_graph(task_id: str) -> dict:
    return {
        "graphId": f"{task_id}-graph",
        "nodes": [
            _node(
                node_id="document-input",
                node_type="fixed_tool",
                display_name="文档输入",
                status="completed",
                input_ports=[],
                output_ports=[_port("document-output", "文档", "document")],
                dependencies=[],
                summary="接收用户在聊天区提供的文档附件。",
                position={"x": 260, "y": 20},
                tool_ref="document.receive_attachment",
            ),
            _node(
                node_id="document-parse",
                node_type="fixed_tool",
                display_name="文档转 Markdown",
                status="waiting",
                input_ports=[_port("document-input", "文档", "document")],
                output_ports=[_port("markdown-output", "Markdown", "text")],
                dependencies=["document-input"],
                summary="把用户提供的本地文档转换为适合模型读取的 Markdown 正文。",
                position={"x": 260, "y": 190},
                tool_ref="document.markitdown_convert",
            ),
            _node(
                node_id="content-organize",
                node_type="model",
                display_name="整理内容",
                status="waiting",
                input_ports=[_port("text-input", "正文", "text")],
                output_ports=[_port("outline-output", "提纲", "json")],
                dependencies=["document-parse"],
                summary="提炼文档要点，形成结构化提纲。",
                position={"x": 90, "y": 370},
                model_ref="local-content-organizer",
            ),
            _node(
                node_id="report-generate",
                node_type="model",
                display_name="生成报告",
                status="waiting",
                input_ports=[_port("text-input", "正文", "text")],
                output_ports=[_port("report-output", "报告", "text")],
                dependencies=["document-parse"],
                summary="根据提取的正文生成报告初稿。",
                position={"x": 430, "y": 370},
                model_ref="local-report-writer",
            ),
            _node(
                node_id="typst-export",
                node_type="fixed_tool",
                display_name="Typst PDF 导出",
                status="waiting",
                input_ports=[
                    _port("outline-input", "提纲", "json"),
                    _port("report-input", "报告", "text"),
                ],
                output_ports=[
                    _port("typst-output", "Typst 源文件", "artifact"),
                    _port("pdf-output", "PDF 文件", "artifact"),
                ],
                dependencies=["content-organize", "report-generate"],
                summary="把整理结果和报告正文排版为 Typst 源文件，并编译为 PDF。",
                position={"x": 260, "y": 560},
                tool_ref="document.typst_compile",
            ),
            _node(
                node_id="file-export",
                node_type="output",
                display_name="导出文件",
                status="waiting",
                input_ports=[_port("artifact-input", "PDF 文件", "artifact")],
                output_ports=[_port("artifact-output", "产物", "artifact")],
                dependencies=["typst-export"],
                summary="汇总 Typst 源文件和 PDF，输出最终文件。",
                position={"x": 260, "y": 750},
            ),
        ],
        "edges": [
            {
                "id": "document-input-document-parse",
                "source": "document-input",
                "target": "document-parse",
            },
            {
                "id": "document-parse-content-organize",
                "source": "document-parse",
                "target": "content-organize",
            },
            {
                "id": "document-parse-report-generate",
                "source": "document-parse",
                "target": "report-generate",
            },
            {
                "id": "content-organize-typst-export",
                "source": "content-organize",
                "target": "typst-export",
            },
            {
                "id": "report-generate-typst-export",
                "source": "report-generate",
                "target": "typst-export",
            },
            {
                "id": "typst-export-file-export",
                "source": "typst-export",
                "target": "file-export",
            },
        ],
    }


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
