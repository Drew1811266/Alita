from agent_service.runtime_trace import RuntimeSpan
from agent_service.trace_store import TraceStore


def test_trace_store_appends_and_lists_spans(tmp_path) -> None:
    store = TraceStore(project_path=str(tmp_path / "demo.alita"), run_id="run-1")
    span = RuntimeSpan(
        trace_id="trace-run-1",
        span_id="span-000001",
        parent_span_id=None,
        run_id="run-1",
        node_id="node-a",
        kind="tool.call",
        name="internal:test.echo_values",
        status="ok",
        started_at="2026-05-30T00:00:00Z",
        ended_at="2026-05-30T00:00:01Z",
        duration_ms=1000,
    )

    store.append_span(span)

    assert store.list_spans()[0]["kind"] == "tool.call"
    assert store.list_spans()[0]["spanId"] == "span-000001"
