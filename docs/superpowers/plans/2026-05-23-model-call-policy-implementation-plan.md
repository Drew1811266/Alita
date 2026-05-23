# Model Call Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a model-call policy layer so LangGraph route decisions choose fast model calls for simple chat and deeper reasoning calls for complex tasks and graph model nodes.

**Architecture:** Add `agent_service.model_policy` as the boundary between route classification and llama.cpp calls. Keep Qwen thinking details inside `LlamaCppModelClient`, preserve existing explicit `temperature` and `max_tokens` overrides, and pass policies from graph routing and graph execution call sites.

**Tech Stack:** Python 3.12, FastAPI sidecar, LangGraph, llama.cpp OpenAI-compatible chat endpoint, pytest.

---

## File Structure

- Create `python/agent_service/model_policy.py`: profile enums, immutable policy values, route-to-policy mapping, graph-node-to-policy mapping, and policy default merging.
- Create `python/tests/test_model_policy.py`: unit tests for route and graph-node policy selection.
- Modify `python/agent_service/model_client.py`: accept optional `ModelCallPolicy`, build payloads from policy defaults, include best-effort thinking extra fields, and retry without extra fields when rejected.
- Modify `python/tests/test_model_client.py`: test policy payloads, explicit override behavior, extra body retry, and streaming policy defaults.
- Modify `python/agent_service/graph.py`: resolve fast policy for chat/local inquiry, attach deep-policy metadata to task and research graphs, and pass fast policy into streaming chat.
- Modify `python/tests/test_graph.py`: update fakes to capture policies and assert chat, task, and research paths choose the correct profiles.
- Modify `python/agent_service/model_runtime.py`: pass `NODE_REASONING` into graph model node calls while keeping `ModelBinding` token overrides.
- Modify `python/tests/test_model_runtime.py`: update fakes to capture policies and assert node model execution uses `NODE_REASONING`.
- Modify `python/agent_service/execution.py`: pass node-aware policy into generic planned model nodes.
- Modify `python/tests/test_execution.py`: assert planned model nodes receive `NODE_REASONING`.

---

### Task 1: Add Model Policy Module

**Files:**
- Create: `python/agent_service/model_policy.py`
- Create: `python/tests/test_model_policy.py`

- [ ] **Step 1: Write failing policy tests**

Create `python/tests/test_model_policy.py`:

```python
from __future__ import annotations

from agent_service.model_policy import (
    DEEP_REASONING_POLICY,
    FAST_CHAT_POLICY,
    FAST_FACTUAL_POLICY,
    NODE_REASONING_POLICY,
    ModelCallProfile,
    apply_policy_defaults,
    policy_for_agent_intent,
    policy_for_graph_node,
)
from agent_service.schemas import GraphNode


def _node(
    node_id: str,
    node_type: str,
    *,
    model_ref: str | None = None,
) -> GraphNode:
    return GraphNode(
        nodeId=node_id,
        nodeType=node_type,
        displayName=node_id,
        status="waiting",
        inputPorts=[],
        outputPorts=[],
        dependencies=[],
        modelRef=model_ref,
        summary="test node",
        createdBy="agent",
        artifactRefs=[],
        retryCount=0,
        position={"x": 0, "y": 0},
    )


def test_policy_for_agent_intent_uses_fast_chat_for_conversation() -> None:
    assert policy_for_agent_intent("chat").profile == ModelCallProfile.FAST_CHAT
    assert policy_for_agent_intent("local_inquiry").profile == ModelCallProfile.FAST_CHAT


def test_policy_for_agent_intent_uses_fast_factual_for_simple_web() -> None:
    assert (
        policy_for_agent_intent("web_simple_inquiry").profile
        == ModelCallProfile.FAST_FACTUAL
    )
    assert (
        policy_for_agent_intent("web_complex_choice").profile
        == ModelCallProfile.FAST_FACTUAL
    )


def test_policy_for_agent_intent_uses_deep_reasoning_for_complex_work() -> None:
    assert (
        policy_for_agent_intent("task").profile
        == ModelCallProfile.DEEP_REASONING
    )
    assert (
        policy_for_agent_intent("web_complex_research_flow").profile
        == ModelCallProfile.DEEP_REASONING
    )


def test_policy_for_graph_node_uses_deep_reasoning_for_research_synthesis() -> None:
    policy = policy_for_graph_node(
        _node(
            "research-report-synthesis",
            "model",
            model_ref="research-report-synthesizer",
        ),
        graph_metadata={"kind": "research"},
    )

    assert policy.profile == ModelCallProfile.DEEP_REASONING


def test_policy_for_graph_node_uses_node_reasoning_for_model_nodes() -> None:
    policy = policy_for_graph_node(
        _node("content-organize", "model", model_ref="local-content-organizer"),
        graph_metadata={},
    )

    assert policy.profile == ModelCallProfile.NODE_REASONING


def test_policy_for_graph_node_uses_fast_chat_for_non_model_fallback() -> None:
    policy = policy_for_graph_node(
        _node("file-export", "output"),
        graph_metadata={},
    )

    assert policy.profile == ModelCallProfile.FAST_CHAT


def test_apply_policy_defaults_preserves_explicit_overrides() -> None:
    resolved = apply_policy_defaults(
        NODE_REASONING_POLICY,
        temperature=0.4,
        max_tokens=2048,
        stream=True,
    )

    assert resolved.temperature == 0.4
    assert resolved.max_tokens == 2048
    assert resolved.stream is True
    assert resolved.policy.profile == ModelCallProfile.NODE_REASONING


def test_policy_constants_have_expected_profiles() -> None:
    assert FAST_CHAT_POLICY.profile == ModelCallProfile.FAST_CHAT
    assert FAST_FACTUAL_POLICY.profile == ModelCallProfile.FAST_FACTUAL
    assert DEEP_REASONING_POLICY.profile == ModelCallProfile.DEEP_REASONING
    assert NODE_REASONING_POLICY.profile == ModelCallProfile.NODE_REASONING
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python/tests/test_model_policy.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_service.model_policy'`.

- [ ] **Step 3: Implement `model_policy.py`**

Create `python/agent_service/model_policy.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from agent_service.schemas import GraphNode


ThinkingMode = Literal["off", "auto", "deep"]


class ModelCallProfile(str, Enum):
    FAST_CHAT = "fast_chat"
    FAST_FACTUAL = "fast_factual"
    DEEP_REASONING = "deep_reasoning"
    NODE_REASONING = "node_reasoning"


@dataclass(frozen=True)
class ModelCallPolicy:
    profile: ModelCallProfile
    temperature: float
    max_tokens: int
    thinking: ThinkingMode
    preserve_thinking: bool = False
    stream: bool | None = None
    extra_body: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedModelCallSettings:
    policy: ModelCallPolicy
    temperature: float
    max_tokens: int
    stream: bool
    extra_body: dict[str, Any]


FAST_CHAT_POLICY = ModelCallPolicy(
    profile=ModelCallProfile.FAST_CHAT,
    temperature=0.3,
    max_tokens=768,
    thinking="off",
    preserve_thinking=False,
    stream=True,
    extra_body={
        "chat_template_kwargs": {
            "enable_thinking": False,
        }
    },
)

FAST_FACTUAL_POLICY = ModelCallPolicy(
    profile=ModelCallProfile.FAST_FACTUAL,
    temperature=0.2,
    max_tokens=1024,
    thinking="auto",
    preserve_thinking=False,
)

DEEP_REASONING_POLICY = ModelCallPolicy(
    profile=ModelCallProfile.DEEP_REASONING,
    temperature=0.2,
    max_tokens=8192,
    thinking="deep",
    preserve_thinking=True,
    stream=False,
    extra_body={
        "chat_template_kwargs": {
            "enable_thinking": True,
            "preserve_thinking": True,
        }
    },
)

NODE_REASONING_POLICY = ModelCallPolicy(
    profile=ModelCallProfile.NODE_REASONING,
    temperature=0.2,
    max_tokens=4096,
    thinking="auto",
    preserve_thinking=True,
    stream=False,
    extra_body={
        "chat_template_kwargs": {
            "enable_thinking": True,
            "preserve_thinking": True,
        }
    },
)


def policy_for_agent_intent(intent: str) -> ModelCallPolicy:
    if intent in {"chat", "local_inquiry"}:
        return FAST_CHAT_POLICY
    if intent in {"web_simple_inquiry", "web_complex_choice"}:
        return FAST_FACTUAL_POLICY
    if intent in {"task", "web_complex_research_flow"}:
        return DEEP_REASONING_POLICY
    return FAST_CHAT_POLICY


def policy_for_graph_node(
    node: GraphNode,
    *,
    graph_metadata: dict[str, Any] | None = None,
) -> ModelCallPolicy:
    metadata = graph_metadata or {}
    if (
        metadata.get("kind") == "research"
        and node.nodeId == "research-report-synthesis"
    ):
        return DEEP_REASONING_POLICY
    if node.nodeType == "model":
        return NODE_REASONING_POLICY
    return FAST_CHAT_POLICY


def apply_policy_defaults(
    policy: ModelCallPolicy | None,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    stream: bool | None = None,
) -> ResolvedModelCallSettings:
    effective_policy = policy or FAST_CHAT_POLICY
    return ResolvedModelCallSettings(
        policy=effective_policy,
        temperature=(
            effective_policy.temperature if temperature is None else temperature
        ),
        max_tokens=effective_policy.max_tokens if max_tokens is None else max_tokens,
        stream=(
            bool(effective_policy.stream)
            if stream is None
            else stream
        ),
        extra_body=dict(effective_policy.extra_body),
    )
```

- [ ] **Step 4: Run policy tests**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python/tests/test_model_policy.py -q
```

Expected: PASS, 8 tests passed.

- [ ] **Step 5: Commit task 1**

```powershell
git add python\agent_service\model_policy.py python\tests\test_model_policy.py
git commit -m "feat: add model call policy profiles"
```

---

### Task 2: Extend LlamaCppModelClient With Policy Support

**Files:**
- Modify: `python/agent_service/model_client.py`
- Modify: `python/tests/test_model_client.py`

- [ ] **Step 1: Add failing model client policy tests**

Append these tests to `python/tests/test_model_client.py`:

```python
from agent_service.model_policy import DEEP_REASONING_POLICY, FAST_CHAT_POLICY


def test_llama_client_applies_policy_defaults_to_chat_payload() -> None:
    calls: list[tuple[str, dict, float]] = []

    def transport(url: str, payload: dict, timeout: float) -> dict:
        calls.append((url, payload, timeout))
        return {"choices": [{"message": {"content": "deep answer"}}]}

    client = LlamaCppModelClient(
        ModelClientConfig(enabled=True),
        transport=transport,
    )

    assert (
        client.chat(
            [ChatMessage(role="user", content="plan this")],
            policy=DEEP_REASONING_POLICY,
        )
        == "deep answer"
    )

    assert calls[0][1]["temperature"] == 0.2
    assert calls[0][1]["max_tokens"] == 8192
    assert calls[0][1]["chat_template_kwargs"] == {
        "enable_thinking": True,
        "preserve_thinking": True,
    }


def test_llama_client_explicit_arguments_override_policy_defaults() -> None:
    calls: list[tuple[str, dict, float]] = []

    def transport(url: str, payload: dict, timeout: float) -> dict:
        calls.append((url, payload, timeout))
        return {"choices": [{"message": {"content": "ok"}}]}

    client = LlamaCppModelClient(
        ModelClientConfig(enabled=True),
        transport=transport,
    )

    assert (
        client.chat(
            [ChatMessage(role="user", content="hello")],
            policy=DEEP_REASONING_POLICY,
            temperature=0.5,
            max_tokens=123,
        )
        == "ok"
    )
    assert calls[0][1]["temperature"] == 0.5
    assert calls[0][1]["max_tokens"] == 123


def test_llama_client_retries_without_policy_extra_body_when_rejected() -> None:
    calls: list[tuple[str, dict, float]] = []

    def transport(url: str, payload: dict, timeout: float) -> dict:
        calls.append((url, payload, timeout))
        if len(calls) == 1:
            raise ModelRuntimeRequestFailed("unknown request field")
        return {"choices": [{"message": {"content": "fallback ok"}}]}

    client = LlamaCppModelClient(
        ModelClientConfig(enabled=True),
        transport=transport,
    )

    assert (
        client.chat(
            [ChatMessage(role="user", content="hello")],
            policy=DEEP_REASONING_POLICY,
        )
        == "fallback ok"
    )
    assert "chat_template_kwargs" in calls[0][1]
    assert "chat_template_kwargs" not in calls[1][1]
    assert calls[1][1]["max_tokens"] == 8192


def test_llama_client_applies_policy_defaults_to_stream_payload() -> None:
    calls: list[tuple[str, dict, float]] = []

    def stream_transport(url: str, payload: dict, timeout: float):
        calls.append((url, payload, timeout))
        return [
            b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n',
            b"data: [DONE]\n\n",
        ]

    client = LlamaCppModelClient(
        ModelClientConfig(enabled=True),
        stream_transport=stream_transport,
    )

    assert list(
        client.stream_chat(
            [ChatMessage(role="user", content="hello")],
            policy=FAST_CHAT_POLICY,
        )
    ) == ["ok"]
    assert calls[0][1]["temperature"] == 0.3
    assert calls[0][1]["max_tokens"] == 768
    assert calls[0][1]["stream"] is True
    assert calls[0][1]["chat_template_kwargs"] == {"enable_thinking": False}
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python/tests/test_model_client.py -q
```

Expected: FAIL with `TypeError` because `chat()` and `stream_chat()` do not accept `policy`.

- [ ] **Step 3: Update model client imports and protocol signatures**

In `python/agent_service/model_client.py`, add:

```python
from agent_service.model_policy import ModelCallPolicy, apply_policy_defaults
```

Change `LlamaCppModelClient.chat()` and `stream_chat()` signatures to:

```python
def chat(
    self,
    messages: list[ChatMessage],
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    policy: ModelCallPolicy | None = None,
) -> str:
```

```python
def stream_chat(
    self,
    messages: list[ChatMessage],
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    policy: ModelCallPolicy | None = None,
) -> Iterator[str]:
```

- [ ] **Step 4: Add payload builder and retry helper**

In `python/agent_service/model_client.py`, add these helpers below `_post_json_stream()`:

```python
def _chat_payload(
    config: ModelClientConfig,
    messages: list[ChatMessage],
    *,
    temperature: float | None,
    max_tokens: int | None,
    stream: bool,
    policy: ModelCallPolicy | None,
    include_extra_body: bool = True,
) -> dict:
    resolved = apply_policy_defaults(
        policy,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=stream,
    )
    payload = {
        "model": config.model,
        "messages": [
            {"role": message.role, "content": message.content}
            for message in messages
        ],
        "temperature": resolved.temperature,
        "max_tokens": resolved.max_tokens,
        "stream": resolved.stream,
    }
    if include_extra_body:
        payload.update(resolved.extra_body)
    return payload
```

Replace manual payload construction in `chat()` with:

```python
payload = _chat_payload(
    self.config,
    messages,
    temperature=temperature,
    max_tokens=max_tokens,
    stream=False,
    policy=policy,
)
try:
    response = self._transport(
        f"{self.config.base_url}/v1/chat/completions",
        payload,
        self.config.timeout_seconds,
    )
except ModelRuntimeRequestFailed:
    if policy is None or not policy.extra_body:
        raise
    payload = _chat_payload(
        self.config,
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
        policy=policy,
        include_extra_body=False,
    )
    response = self._transport(
        f"{self.config.base_url}/v1/chat/completions",
        payload,
        self.config.timeout_seconds,
    )
```

Replace manual payload construction in `stream_chat()` with:

```python
payload = _chat_payload(
    self.config,
    messages,
    temperature=temperature,
    max_tokens=max_tokens,
    stream=True,
    policy=policy,
)
```

- [ ] **Step 5: Preserve existing token-budget retry**

In `chat()`, keep the existing `_should_retry_empty_reasoning_response()` block, but build the retry payload from the already resolved payload:

```python
if _should_retry_empty_reasoning_response(response):
    retry_payload = {
        **payload,
        "max_tokens": max(int(payload["max_tokens"]) * 4, 4096),
    }
    retry_response = self._transport(
        f"{self.config.base_url}/v1/chat/completions",
        retry_payload,
        self.config.timeout_seconds,
    )
    retry_content = _extract_chat_content(retry_response)
    if retry_content.strip():
        return retry_content
```

- [ ] **Step 6: Run model client tests**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python/tests/test_model_client.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit task 2**

```powershell
git add python\agent_service\model_client.py python\tests\test_model_client.py
git commit -m "feat: apply model policies in llama client"
```

---

### Task 3: Wire Policies Into LangGraph Routing

**Files:**
- Modify: `python/agent_service/graph.py`
- Modify: `python/tests/test_graph.py`

- [ ] **Step 1: Update graph fake model client to capture policy**

In `python/tests/test_graph.py`, add:

```python
from agent_service.model_policy import ModelCallPolicy, ModelCallProfile
```

Update `FakeModelClient`:

```python
class FakeModelClient:
    def __init__(self, reply: str = "本地模型回复") -> None:
        self.reply = reply
        self.calls: list[list[ChatMessage]] = []
        self.policies: list[ModelCallPolicy | None] = []

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ) -> str:
        self.calls.append(messages)
        self.policies.append(policy)
        return self.reply

    def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ):
        self.calls.append(messages)
        self.policies.append(policy)
        yield "你好"
        yield "，本地模型"
```

- [ ] **Step 2: Add failing graph policy assertions**

Add these tests to `python/tests/test_graph.py`:

```python
def test_plain_chat_uses_fast_chat_policy() -> None:
    client = FakeModelClient("fast answer")

    events = run_agent(
        UserMessage(task_id="task-chat", content="hello"),
        model_client=client,
    )

    assert [event.type for event in events] == ["message.created"]
    assert client.policies[0] is not None
    assert client.policies[0].profile == ModelCallProfile.FAST_CHAT


def test_plain_chat_stream_uses_fast_chat_policy() -> None:
    client = FakeModelClient()

    events = list(
        stream_agent_events(
            UserMessage(task_id="task-chat", content="hello"),
            model_client=client,
        )
    )

    assert events[-1].type == "message.completed"
    assert client.policies[0] is not None
    assert client.policies[0].profile == ModelCallProfile.FAST_CHAT


def test_task_graph_records_deep_reasoning_policy_metadata() -> None:
    events = list(
        stream_agent_events(
            UserMessage(
                task_id="task-content",
                content="Please write a structured project proposal.",
            )
        )
    )

    graph_event = next(event for event in events if event.type == "node_graph.created")
    assert graph_event.payload["graph"]["metadata"]["modelPolicy"] == "deep_reasoning"


def test_research_graph_records_deep_reasoning_policy_metadata() -> None:
    events = run_agent(
        UserMessage(
            task_id="task-research",
            content="Research current GitHub trending developer tools and create a report.",
        ),
        inquiry_choice="research_flow",
    )

    graph_event = next(event for event in events if event.type == "node_graph.created")
    assert graph_event.payload["graph"]["metadata"]["modelPolicy"] == "deep_reasoning"
```

- [ ] **Step 3: Run graph tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python/tests/test_graph.py -q
```

Expected: FAIL because graph calls do not pass policies and graph metadata lacks `modelPolicy`.

- [ ] **Step 4: Import and use policy resolver in `graph.py`**

In `python/agent_service/graph.py`, add:

```python
from agent_service.model_policy import (
    DEEP_REASONING_POLICY,
    policy_for_agent_intent,
)
```

In `answer_with_model()`, change the model call to:

```python
policy = policy_for_agent_intent(state.get("intent", "chat"))
content = client.chat(
    _build_model_messages(state["message"]),
    policy=policy,
)
```

In `stream_agent_events()`, change streaming chat to:

```python
policy = policy_for_agent_intent(intent)
for delta in client.stream_chat(
    _build_model_messages(message),
    policy=policy,
):
    yield AgentEvent(
        type="message.delta",
        payload={"messageId": message_id, "delta": delta},
    )
```

- [ ] **Step 5: Add graph metadata helper**

In `python/agent_service/graph.py`, add:

```python
def _with_model_policy_metadata(graph_payload: dict, policy_name: str) -> dict:
    metadata = dict(graph_payload.get("metadata") or {})
    metadata["modelPolicy"] = policy_name
    return {
        **graph_payload,
        "metadata": metadata,
    }
```

In `_graph_payload_for_task()`, wrap both return paths:

```python
if spec.task_type == "document_processing" and not _is_markdown_conversion_only(
    message.content
):
    return _with_model_policy_metadata(
        _create_document_graph(message.task_id, spec, message),
        DEEP_REASONING_POLICY.profile.value,
    )
return _with_model_policy_metadata(
    _build_task_graph_payload(message),
    DEEP_REASONING_POLICY.profile.value,
)
```

In `plan_research_graph()`, wrap `build_research_graph(...)`:

```python
"graph": _with_model_policy_metadata(
    build_research_graph(
        state["message"],
        state.get("route_decision", {}),
    ),
    DEEP_REASONING_POLICY.profile.value,
),
```

- [ ] **Step 6: Run graph tests**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python/tests/test_graph.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit task 3**

```powershell
git add python\agent_service\graph.py python\tests\test_graph.py
git commit -m "feat: route graph calls through model policies"
```

---

### Task 4: Apply Node Reasoning Policy During Graph Execution

**Files:**
- Modify: `python/agent_service/model_runtime.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/tests/test_model_runtime.py`
- Modify: `python/tests/test_execution.py`

- [ ] **Step 1: Add model runtime policy test**

In `python/tests/test_model_runtime.py`, add:

```python
from agent_service.model_policy import ModelCallPolicy, ModelCallProfile
```

Update `FakeModelClient`:

```python
class FakeModelClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.messages: list[list[ChatMessage]] = []
        self.temperatures: list[float | None] = []
        self.max_tokens: list[int | None] = []
        self.policies: list[ModelCallPolicy | None] = []

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ) -> str:
        self.messages.append(messages)
        self.temperatures.append(temperature)
        self.max_tokens.append(max_tokens)
        self.policies.append(policy)
        return self.reply
```

Append:

```python
def test_model_runtime_uses_node_reasoning_policy() -> None:
    model_client = FakeModelClient("outline text")
    runtime = ModelRuntime(model_client=model_client)
    binding = ModelBinding(
        model_ref="local.content_organizer",
        purpose="organize_document_content",
        prompt_template="document.content_organizer.zh.v1",
        output_key="outline",
        max_tokens=1024,
    )

    runtime.run(
        binding,
        inputs={"document-parse": NodeOutput(values={"text": "document body"})},
    )

    assert model_client.policies[0] is not None
    assert model_client.policies[0].profile == ModelCallProfile.NODE_REASONING
    assert model_client.max_tokens == [1024]
```

- [ ] **Step 2: Run model runtime tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python/tests/test_model_runtime.py -q
```

Expected: FAIL because `ModelRuntime.run()` does not pass a policy.

- [ ] **Step 3: Update `ModelRuntime` protocol and call**

In `python/agent_service/model_runtime.py`, add:

```python
from agent_service.model_policy import ModelCallPolicy, NODE_REASONING_POLICY
```

Update the local protocol:

```python
class ModelClient(Protocol):
    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ) -> str:
        pass
```

Change `ModelRuntime.run()`:

```python
content = self.model_client.chat(
    messages,
    temperature=binding.temperature,
    max_tokens=binding.max_tokens,
    policy=NODE_REASONING_POLICY,
)
```

- [ ] **Step 4: Add planned task executor policy test**

In `python/tests/test_execution.py`, add imports:

```python
from agent_service.model_client import ChatMessage
from agent_service.model_policy import ModelCallPolicy, ModelCallProfile
```

Add this fake and test:

```python
class CapturingModelClient:
    def __init__(self) -> None:
        self.policies: list[ModelCallPolicy | None] = []

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ) -> str:
        self.policies.append(policy)
        return "model node output"


def test_planned_model_nodes_use_node_reasoning_policy(tmp_path: Path) -> None:
    model_client = CapturingModelClient()
    request = build_request(
        tmp_path,
        graph_metadata={"taskKind": "content"},
        nodes=[
            build_node(
                "model-model-reasoning",
                "model",
                [],
                model_ref="local-task-reasoner",
            ),
            build_node("task-output", "output", ["model-model-reasoning"]),
        ],
    )

    events = list(run_graph_events(request, model_client=model_client))

    assert events[-1].type == "task.completed"
    assert model_client.policies[0] is not None
    assert model_client.policies[0].profile == ModelCallProfile.NODE_REASONING
```

If `build_request()` does not accept `graph_metadata`, extend the helper in the same test file:

```python
def build_request(
    tmp_path: Path,
    *,
    nodes: list[dict],
    edges: list[dict] | None = None,
    graph_metadata: dict | None = None,
    ...
) -> RunGraphRequest:
    ...
    graph={
        "graphId": "graph-run",
        "nodes": nodes,
        "edges": edges or _edges_from_dependencies(nodes),
        "metadata": graph_metadata or {},
    }
```

- [ ] **Step 5: Run execution test to verify failure**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python/tests/test_execution.py::test_planned_model_nodes_use_node_reasoning_policy -q
```

Expected: FAIL because `PlannedTaskExecutor` does not pass a policy.

- [ ] **Step 6: Update `execution.py` planned model call**

In `python/agent_service/execution.py`, add:

```python
from agent_service.model_policy import policy_for_graph_node
```

In `PlannedTaskExecutor.run()`, change the model node call:

```python
content = self.model_client.chat(
    [
        ModelChatMessage(
            role="system",
            content=(
                "Execute the planned model step. Return only the useful "
                "task result, not a description of the plan."
            ),
        ),
        ModelChatMessage(
            role="user",
            content=_planned_model_prompt(node, inputs),
        ),
    ],
    temperature=0.2,
    max_tokens=1536,
    policy=policy_for_graph_node(
        node,
        graph_metadata=self.request.graph.metadata,
    ),
)
```

- [ ] **Step 7: Run model runtime and targeted execution tests**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python/tests/test_model_runtime.py python/tests/test_execution.py::test_planned_model_nodes_use_node_reasoning_policy -q
```

Expected: PASS.

- [ ] **Step 8: Commit task 4**

```powershell
git add python\agent_service\model_runtime.py python\agent_service\execution.py python\tests\test_model_runtime.py python\tests\test_execution.py
git commit -m "feat: apply node reasoning policy during graph execution"
```

---

### Task 5: Regression Verification And Documentation Check

**Files:**
- Verify only unless prior tasks reveal a required small fix.

- [ ] **Step 1: Run focused Python tests**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest `
  python/tests/test_model_policy.py `
  python/tests/test_model_client.py `
  python/tests/test_graph.py `
  python/tests/test_model_runtime.py `
  python/tests/test_execution.py `
  -q
```

Expected: PASS.

- [ ] **Step 2: Run full Python test suite**

Run:

```powershell
$env:PYTHONPATH='python'; python -m pytest python/tests -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend type check**

Run:

```powershell
npm run frontend:lint
```

Expected: PASS. This guards the unchanged frontend schemas against accidental drift.

- [ ] **Step 4: Run frontend tests**

Run:

```powershell
npm run frontend:test
```

Expected: PASS.

- [ ] **Step 5: Run Rust desktop check**

Run:

```powershell
cargo check --manifest-path src-tauri\Cargo.toml
```

Expected: PASS. If the worktree lacks local sidecar binaries or llama resources, copy the already-existing ignored local resources from the primary workspace before running the command:

```powershell
New-Item -ItemType Directory -Force -Path src-tauri\binaries | Out-Null
Copy-Item -LiteralPath "D:\Software Project\Alita\src-tauri\binaries\alita-agent-sidecar-x86_64-pc-windows-msvc.exe" -Destination "D:\Software Project\Alita\.worktrees\merge-all-main\src-tauri\binaries\alita-agent-sidecar-x86_64-pc-windows-msvc.exe" -Force
New-Item -ItemType Directory -Force -Path src-tauri\resources | Out-Null
Copy-Item -LiteralPath "D:\Software Project\Alita\src-tauri\resources\llama-cpp" -Destination "D:\Software Project\Alita\.worktrees\merge-all-main\src-tauri\resources\llama-cpp" -Recurse -Force
cargo check --manifest-path src-tauri\Cargo.toml
```

- [ ] **Step 6: Inspect diff**

Run:

```powershell
git diff --stat main...HEAD
git diff --check
```

Expected: policy module, Python tests, and Python runtime integration changes only; no whitespace errors.

- [ ] **Step 7: Commit verification fixes only when needed**

If steps 1-6 required a small code fix, commit it:

```powershell
git add python\agent_service python\tests
git commit -m "test: stabilize model policy integration"
```

Expected: no commit if verification passed without additional changes.

---

## Self-Review Checklist

- Spec coverage: implements route policy selection, llama.cpp policy adaptation, graph metadata, graph-node policy selection, and compatibility with legacy call parameters.
- Backward compatibility: legacy callers can still pass explicit `temperature` and `max_tokens`.
- Scope control: no UI switch, no chain-of-thought display, no frontend schema change.
- Verification: focused Python tests, full Python tests, frontend lint/tests, and Rust check are included.
