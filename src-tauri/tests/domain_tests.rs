use alita_lib::domain::{AgentNode, CanvasPosition, NodePort, NodeStatus, NodeType};

#[test]
fn node_status_serializes_as_snake_case() {
    let serialized = serde_json::to_string(&NodeStatus::NeedsUserInput).unwrap();

    assert_eq!(serialized, "\"needs_user_input\"");
}

#[test]
fn node_type_serializes_planning_and_temporary_script_as_snake_case() {
    let planning = serde_json::to_string(&NodeType::Planning).unwrap();
    let temporary_script = serde_json::to_string(&NodeType::TemporaryScript).unwrap();

    assert_eq!(planning, "\"planning\"");
    assert_eq!(temporary_script, "\"temporary_script\"");
}

#[test]
fn agent_node_serializes_with_camel_case_fields_and_snake_case_enums() {
    let node = sample_agent_node();
    let serialized = serde_json::to_value(&node).unwrap();

    assert_eq!(serialized["nodeId"], "node-1");
    assert_eq!(serialized["nodeType"], "fixed_tool");
    assert_eq!(serialized["displayName"], "Fetch document");
    assert_eq!(serialized["status"], "needs_permission");
    assert_eq!(serialized["summary"], "Fetches the requested document");
    assert_eq!(serialized["inputPorts"][0]["dataType"], "text");
    assert_eq!(serialized["outputPorts"][0]["dataType"], "document");
    assert_eq!(serialized["createdBy"], "agent");
    assert_eq!(serialized["retryCount"], 1);
    assert_eq!(serialized["position"]["x"].as_f64().unwrap(), 120.0);
    assert_eq!(serialized["position"]["y"].as_f64().unwrap(), 240.0);
}

#[test]
fn builds_agent_node_with_ports_and_basic_values() {
    let node = sample_agent_node();

    assert_eq!(node.node_id, "node-1");
    assert_eq!(node.node_type, NodeType::FixedTool);
    assert_eq!(node.input_ports.len(), 1);
    assert_eq!(node.output_ports.len(), 1);
    assert_eq!(node.dependencies, vec!["node-0"]);
    assert_eq!(node.artifact_refs, vec!["artifact-1"]);
    assert_eq!(node.position.x, 120.0);
    assert_eq!(node.position.y, 240.0);
}

fn sample_agent_node() -> AgentNode {
    AgentNode {
        node_id: "node-1".to_string(),
        node_type: NodeType::FixedTool,
        display_name: "Fetch document".to_string(),
        status: NodeStatus::NeedsPermission,
        input_ports: vec![NodePort {
            id: "input-1".to_string(),
            label: "Prompt".to_string(),
            data_type: "text".to_string(),
        }],
        output_ports: vec![NodePort {
            id: "output-1".to_string(),
            label: "Document".to_string(),
            data_type: "document".to_string(),
        }],
        dependencies: vec!["node-0".to_string()],
        tool_ref: Some("tool.fetch".to_string()),
        model_ref: None,
        summary: "Fetches the requested document".to_string(),
        created_by: "agent".to_string(),
        artifact_refs: vec!["artifact-1".to_string()],
        retry_count: 1,
        position: CanvasPosition { x: 120.0, y: 240.0 },
    }
}
