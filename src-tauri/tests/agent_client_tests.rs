#[path = "../src/agent_client.rs"]
mod agent_client;

use agent_client::{AgentAttachment, AgentMessageRequest};

#[test]
fn serializes_agent_message_request() {
    let request = AgentMessageRequest {
        task_id: "task-1".to_string(),
        content: "整理成报告".to_string(),
        attachments: vec![AgentAttachment {
            attachment_id: "a1".to_string(),
            name: "input.docx".to_string(),
            path: "workspace/inputs/input.docx".to_string(),
            size_bytes: 10,
            mime_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                .to_string(),
        }],
    };

    let json = serde_json::to_value(request).expect("request should serialize");

    assert_eq!(json["task_id"], "task-1");
    assert_eq!(json["content"], "整理成报告");
    assert_eq!(json["attachments"][0]["name"], "input.docx");
    assert_eq!(json["attachments"][0]["size_bytes"], 10);
}

#[test]
fn stores_sidecar_auth_token() {
    let client = agent_client::AgentClient::new("http://127.0.0.1:8765").with_auth_token("token-1");

    assert_eq!(client.auth_token(), Some("token-1"));
    assert_eq!(
        agent_client::sidecar_token_header(),
        "X-Alita-Sidecar-Token"
    );
}
