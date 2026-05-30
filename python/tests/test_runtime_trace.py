from agent_service.runtime_trace import RuntimeSpan, next_span_id, trace_id_for_run


def test_trace_id_is_stable_for_run():
    assert trace_id_for_run("run-123") == "trace-run-123"


def test_span_record_uses_camel_case_payload():
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
        metadata={"ok": True},
    )

    assert span.to_record() == {
        "traceId": "trace-run-1",
        "spanId": "span-000001",
        "parentSpanId": None,
        "runId": "run-1",
        "nodeId": "node-a",
        "kind": "tool.call",
        "name": "internal:test.echo_values",
        "status": "ok",
        "startedAt": "2026-05-30T00:00:00Z",
        "endedAt": "2026-05-30T00:00:01Z",
        "durationMs": 1000,
        "metadata": {"ok": True},
    }


def test_next_span_id_is_deterministic_for_counter():
    assert next_span_id(1) == "span-000001"
    assert next_span_id(42) == "span-000042"
