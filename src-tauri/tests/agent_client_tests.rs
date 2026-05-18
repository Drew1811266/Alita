use std::{
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    thread::{self, JoinHandle},
    time::Duration,
};

use alita_lib::agent_client::{
    AgentAttachment, AgentMessageRequest, AsrStatusResponse, AsrTranscriptionRequest, InquiryChoice,
};
use alita_lib::commands::{agent_message_request_from_payload, SubmitMessagePayload};

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
        inquiry_choice: None,
    };

    let json = serde_json::to_value(request).expect("request should serialize");

    assert_eq!(json["task_id"], "task-1");
    assert_eq!(json["content"], "整理成报告");
    assert_eq!(json["attachments"][0]["name"], "input.docx");
    assert_eq!(json["attachments"][0]["size_bytes"], 10);
    assert!(json.get("inquiry_choice").is_none());
}

#[test]
fn serializes_agent_message_request_with_inquiry_choice() {
    let request = AgentMessageRequest {
        task_id: "task-1".to_string(),
        content: "Research and compare current Python packaging tools".to_string(),
        attachments: vec![],
        inquiry_choice: Some(InquiryChoice::ResearchFlow),
    };

    let json = serde_json::to_value(request).expect("request should serialize");

    assert_eq!(json["inquiry_choice"], "research_flow");
}

#[test]
fn deserializes_agent_message_request_inquiry_choice_as_enum() {
    let request: AgentMessageRequest = serde_json::from_value(serde_json::json!({
        "task_id": "task-1",
        "content": "Research and compare current Python packaging tools",
        "attachments": [],
        "inquiry_choice": "quick_answer"
    }))
    .expect("request should deserialize");

    assert_eq!(request.inquiry_choice, Some(InquiryChoice::QuickAnswer));
}

#[test]
fn maps_submit_message_payload_to_agent_request_with_inquiry_choice() {
    let request = agent_message_request_from_payload(SubmitMessagePayload {
        task_id: "task-1".to_string(),
        content: "Research and compare current Python packaging tools".to_string(),
        attachments: vec![],
        inquiry_choice: Some(InquiryChoice::ResearchFlow),
    });

    assert_eq!(request.task_id, "task-1");
    assert_eq!(request.inquiry_choice, Some(InquiryChoice::ResearchFlow));
    assert!(request.attachments.is_empty());
}

#[test]
fn maps_submit_message_payload_to_agent_request_without_inquiry_choice() {
    let request = agent_message_request_from_payload(SubmitMessagePayload {
        task_id: "task-1".to_string(),
        content: "hello".to_string(),
        attachments: vec![],
        inquiry_choice: None,
    });

    assert_eq!(request.task_id, "task-1");
    assert_eq!(request.inquiry_choice, None);
}

#[test]
fn stores_sidecar_auth_token() {
    let client = alita_lib::agent_client::AgentClient::new("http://127.0.0.1:8765")
        .with_auth_token("token-1");

    assert_eq!(client.auth_token(), Some("token-1"));
    assert_eq!(
        alita_lib::agent_client::sidecar_token_header(),
        "X-Alita-Sidecar-Token"
    );
}

#[test]
fn serializes_asr_transcription_request() {
    let request = AsrTranscriptionRequest {
        audio_path: "C:\\Temp\\alita-asr-input.wav".to_string(),
        language: "zh".to_string(),
        model_path: None,
    };

    let json = serde_json::to_value(request).expect("request should serialize");

    assert_eq!(json["audioPath"], "C:\\Temp\\alita-asr-input.wav");
    assert_eq!(json["language"], "zh");
    assert!(json.get("modelPath").is_none());
}

#[test]
fn serializes_asr_transcription_request_with_model_path() {
    let request = AsrTranscriptionRequest {
        audio_path: "C:\\Temp\\alita-asr-input.wav".to_string(),
        language: "zh".to_string(),
        model_path: Some("C:\\Models\\Qwen3-ASR-1.7B".to_string()),
    };

    let json = serde_json::to_value(request).expect("request should serialize");

    assert_eq!(json["audioPath"], "C:\\Temp\\alita-asr-input.wav");
    assert_eq!(json["language"], "zh");
    assert_eq!(json["modelPath"], "C:\\Models\\Qwen3-ASR-1.7B");
}

#[test]
fn deserializes_asr_status_response() {
    let status: AsrStatusResponse = serde_json::from_value(serde_json::json!({
        "available": false,
        "configured": false,
        "modelPath": null,
        "message": "voice model is not configured",
        "errorCode": "asr_not_configured"
    }))
    .unwrap();

    assert!(!status.available);
    assert_eq!(status.error_code.as_deref(), Some("asr_not_configured"));
}

#[test]
fn get_asr_status_sends_auth_header_to_status_endpoint() {
    let (base_url, server) = spawn_test_server(
        r#"{"available":true,"configured":true,"modelPath":"C:\\Models\\asr","message":"voice model is configured"}"#,
    );
    let client = alita_lib::agent_client::AgentClient::new(base_url).with_auth_token("token-1");

    let status = tauri::async_runtime::block_on(client.get_asr_status())
        .expect("status request should succeed");
    let request = server.join().expect("server should capture request");

    assert!(status.available);
    assert_eq!(request.method, "GET");
    assert_eq!(request.path, "/asr/status");
    assert_eq!(
        request.header(alita_lib::agent_client::sidecar_token_header()),
        Some("token-1")
    );
}

#[test]
fn get_asr_status_for_model_sends_model_path_query_and_auth_header() {
    let (base_url, server) = spawn_test_server(
        r#"{"available":true,"configured":true,"modelPath":"C:\\Models\\Qwen3-ASR-1.7B","message":"voice model is configured"}"#,
    );
    let client = alita_lib::agent_client::AgentClient::new(base_url).with_auth_token("token-model");

    let status = tauri::async_runtime::block_on(
        client.get_asr_status_for_model(Some("C:\\Models\\Qwen3-ASR-1.7B")),
    )
    .expect("status request should succeed");
    let request = server.join().expect("server should capture request");

    assert!(status.available);
    assert_eq!(request.method, "GET");
    assert_eq!(
        request.path,
        "/asr/status?modelPath=C%3A%5CModels%5CQwen3-ASR-1.7B"
    );
    assert_eq!(
        request.header(alita_lib::agent_client::sidecar_token_header()),
        Some("token-model")
    );
}

#[test]
fn transcribe_asr_audio_sends_auth_header_and_json_body() {
    let (base_url, server) = spawn_test_server(r#"{"text":"ok"}"#);
    let client = alita_lib::agent_client::AgentClient::new(base_url).with_auth_token("token-2");
    let request = AsrTranscriptionRequest {
        audio_path: "C:\\Temp\\alita-asr-input.wav".to_string(),
        language: "zh".to_string(),
        model_path: Some("C:\\Models\\Qwen3-ASR-1.7B".to_string()),
    };

    let response = tauri::async_runtime::block_on(client.transcribe_asr_audio(&request))
        .expect("transcription request should succeed");
    let captured = server.join().expect("server should capture request");
    let body: serde_json::Value =
        serde_json::from_str(&captured.body).expect("request body should be JSON");

    assert_eq!(response.text, "ok");
    assert_eq!(captured.method, "POST");
    assert_eq!(captured.path, "/asr/transcribe");
    assert_eq!(
        captured.header(alita_lib::agent_client::sidecar_token_header()),
        Some("token-2")
    );
    assert_eq!(captured.header("content-type"), Some("application/json"));
    assert_eq!(body["audioPath"], "C:\\Temp\\alita-asr-input.wav");
    assert_eq!(body["language"], "zh");
    assert_eq!(body["modelPath"], "C:\\Models\\Qwen3-ASR-1.7B");
}

#[derive(Debug)]
struct CapturedRequest {
    method: String,
    path: String,
    headers: Vec<(String, String)>,
    body: String,
}

impl CapturedRequest {
    fn header(&self, name: &str) -> Option<&str> {
        let name = name.to_ascii_lowercase();
        self.headers
            .iter()
            .find(|(header_name, _)| header_name == &name)
            .map(|(_, value)| value.as_str())
    }
}

fn spawn_test_server(response_body: &'static str) -> (String, JoinHandle<CapturedRequest>) {
    let listener = TcpListener::bind("127.0.0.1:0").expect("test server should bind");
    let address = listener
        .local_addr()
        .expect("test server should have address");
    let server = thread::spawn(move || {
        let (mut stream, _) = listener.accept().expect("server should accept request");
        let request = read_http_request(&mut stream);
        let response = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            response_body.len(),
            response_body
        );
        stream
            .write_all(response.as_bytes())
            .expect("server should write response");

        request
    });

    (format!("http://{address}"), server)
}

fn read_http_request(stream: &mut TcpStream) -> CapturedRequest {
    stream
        .set_read_timeout(Some(Duration::from_secs(5)))
        .expect("read timeout should be set");

    let mut bytes = Vec::new();
    let mut buffer = [0_u8; 4096];
    let mut header_end = None;
    let mut expected_len = None;

    loop {
        let read = stream
            .read(&mut buffer)
            .expect("server should read request");
        if read == 0 {
            break;
        }
        bytes.extend_from_slice(&buffer[..read]);

        if header_end.is_none() {
            header_end = find_header_end(&bytes);
        }

        if let Some(end) = header_end {
            if expected_len.is_none() {
                expected_len = Some(end + 4 + content_length(&bytes[..end]));
            }
            if bytes.len() >= expected_len.unwrap() {
                break;
            }
        }
    }

    parse_http_request(bytes)
}

fn find_header_end(bytes: &[u8]) -> Option<usize> {
    bytes.windows(4).position(|window| window == b"\r\n\r\n")
}

fn content_length(header_bytes: &[u8]) -> usize {
    let headers = String::from_utf8_lossy(header_bytes);
    headers
        .lines()
        .find_map(|line| {
            let (name, value) = line.split_once(':')?;
            if name.eq_ignore_ascii_case("content-length") {
                value.trim().parse::<usize>().ok()
            } else {
                None
            }
        })
        .unwrap_or(0)
}

fn parse_http_request(bytes: Vec<u8>) -> CapturedRequest {
    let header_end = find_header_end(&bytes).expect("request should include headers");
    let headers = String::from_utf8_lossy(&bytes[..header_end]);
    let mut lines = headers.lines();
    let request_line = lines.next().expect("request should include request line");
    let mut request_parts = request_line.split_whitespace();
    let method = request_parts
        .next()
        .expect("request should include method")
        .to_string();
    let path = request_parts
        .next()
        .expect("request should include path")
        .to_string();
    let headers = lines
        .filter_map(|line| {
            let (name, value) = line.split_once(':')?;
            Some((name.to_ascii_lowercase(), value.trim().to_string()))
        })
        .collect();
    let body = String::from_utf8(bytes[(header_end + 4)..].to_vec())
        .expect("request body should be UTF-8");

    CapturedRequest {
        method,
        path,
        headers,
        body,
    }
}
