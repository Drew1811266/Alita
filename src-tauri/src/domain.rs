use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NodeStatus {
    Waiting,
    Ready,
    Running,
    Completed,
    Failed,
    NeedsUserInput,
    NeedsPermission,
    Skipped,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NodeType {
    FixedTool,
    Model,
    Output,
    TemporaryPlaceholder,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CanvasPosition {
    pub x: f64,
    pub y: f64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NodePort {
    pub id: String,
    pub label: String,
    pub data_type: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AgentNode {
    pub node_id: String,
    pub node_type: NodeType,
    pub display_name: String,
    pub status: NodeStatus,
    pub input_ports: Vec<NodePort>,
    pub output_ports: Vec<NodePort>,
    pub dependencies: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tool_ref: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub model_ref: Option<String>,
    pub summary: String,
    pub created_by: String,
    pub artifact_refs: Vec<String>,
    pub retry_count: u32,
    pub position: CanvasPosition,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NodeEdge {
    pub id: String,
    pub source: String,
    pub target: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NodeGraph {
    pub graph_id: String,
    pub nodes: Vec<AgentNode>,
    pub edges: Vec<NodeEdge>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChatAttachment {
    pub attachment_id: String,
    pub name: String,
    pub path: String,
    pub size_bytes: u64,
    pub mime_type: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChatMessage {
    pub message_id: String,
    pub role: String,
    pub content: String,
    pub attachments: Vec<ChatAttachment>,
    pub created_at: String,
}
