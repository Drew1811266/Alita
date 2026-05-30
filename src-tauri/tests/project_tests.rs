use alita_lib::project::{
    load_project_from_path, new_project, save_project_to_path, ProjectFileError, RunHistoryEntry,
};
use std::fs;

#[test]
fn new_project_uses_schema_version_one_and_empty_state() {
    let project = new_project("文档整理测试", "D:\\Projects\\文档整理测试.alita");

    assert_eq!(project.schema_version, 1);
    assert_eq!(project.name, "文档整理测试");
    assert!(project.messages.is_empty());
    assert!(project.graph.is_none());
    assert!(project.attachments.is_empty());
    assert!(project.model_ref.is_none());
}

#[test]
fn project_schema_does_not_store_memory_records() {
    let project = new_project("Memory test", "D:\\Projects\\memory-test.alita");
    let json = serde_json::to_value(&project).expect("project serializes");

    assert!(json.get("memory").is_none());
    assert!(json.get("memories").is_none());
    assert_eq!(
        json.get("schemaVersion").and_then(|value| value.as_u64()),
        Some(1)
    );
}

#[test]
fn saves_and_loads_project_json() {
    let temp_dir = tempfile::tempdir().unwrap();
    let project_path = temp_dir.path().join("demo.alita");
    let mut project = new_project("Demo", project_path.to_string_lossy().as_ref());
    project.messages.push(serde_json::json!({
        "messageId": "message-1",
        "role": "system",
        "content": "工程已创建。",
        "attachments": [],
        "createdAt": "2026-05-09T12:00:00.000Z"
    }));

    save_project_to_path(&project_path, &project).unwrap();
    let result = load_project_from_path(&project_path).unwrap();

    assert_eq!(result.project.name, "Demo");
    assert_eq!(result.project.messages.len(), 1);
    assert!(result.warnings.is_empty());
}

#[test]
fn loads_project_without_run_history_as_empty_history() {
    let temp_dir = tempfile::tempdir().unwrap();
    let project_path = temp_dir.path().join("historyless.alita");
    fs::write(
        &project_path,
        r#"{"schemaVersion":1,"projectId":"x","name":"Historyless","path":"D:\\Projects\\historyless.alita","createdAt":"2026-05-09T12:00:00.000Z","updatedAt":"2026-05-09T12:00:00.000Z","messages":[],"graph":null,"attachments":[],"modelRef":null,"toolSnapshot":[]}"#,
    )
    .unwrap();

    let result = load_project_from_path(&project_path).unwrap();

    assert!(result.project.run_history.is_empty());
    assert!(result.project.path.ends_with("historyless.alita"));
}

#[test]
fn rejects_non_alita_project_extension() {
    let temp_dir = tempfile::tempdir().unwrap();
    let project_path = temp_dir.path().join("wrong-extension.txt");
    fs::write(
        &project_path,
        r#"{"schemaVersion":1,"projectId":"x","name":"Wrong","path":"D:\\Projects\\wrong-extension.txt","createdAt":"2026-05-09T12:00:00.000Z","updatedAt":"2026-05-09T12:00:00.000Z","messages":[],"graph":null,"attachments":[],"modelRef":null,"toolSnapshot":[],"runHistory":[]}"#,
    )
    .unwrap();

    let error = load_project_from_path(&project_path).unwrap_err();

    assert!(matches!(
        error,
        ProjectFileError::UnsupportedExtension { .. }
    ));
}

#[test]
fn saves_and_loads_run_history_node_runs_and_artifacts() {
    let temp_dir = tempfile::tempdir().unwrap();
    let project_path = temp_dir.path().join("runs.alita");
    let mut project = new_project("Runs", project_path.to_string_lossy().as_ref());
    project.run_history.push(RunHistoryEntry {
        run_id: "run-1".to_string(),
        started_at: "2026-05-10T00:00:00.000Z".to_string(),
        completed_at: Some("2026-05-10T00:00:01.000Z".to_string()),
        status: "completed".to_string(),
        summary: "流程执行完成。".to_string(),
        node_run_ids: vec!["node-run-1".to_string()],
        artifact_refs: vec!["D:\\Project\\artifacts\\report.md".to_string()],
        runtime_notices: vec![serde_json::from_value(serde_json::json!({
            "nodeId": "document-parse",
            "notice": {
                "kind": "duration_exceeded",
                "message": "Node exceeded estimated duration.",
                "actualDurationMs": 1200
            }
        }))
        .unwrap()],
    });

    save_project_to_path(&project_path, &project).unwrap();
    let result = load_project_from_path(&project_path).unwrap();

    assert_eq!(
        result.project.run_history[0].node_run_ids,
        vec!["node-run-1"]
    );
    assert_eq!(
        result.project.run_history[0].artifact_refs,
        vec!["D:\\Project\\artifacts\\report.md"]
    );
    assert_eq!(result.project.run_history[0].runtime_notices.len(), 1);
    assert_eq!(
        result.project.run_history[0].runtime_notices[0].node_id,
        "document-parse"
    );
    assert_eq!(
        result.project.run_history[0].runtime_notices[0].notice["actualDurationMs"],
        1200
    );
}

#[test]
fn rejects_invalid_json_project_file() {
    let temp_dir = tempfile::tempdir().unwrap();
    let project_path = temp_dir.path().join("broken.alita");
    fs::write(&project_path, "{ invalid json").unwrap();

    let error = load_project_from_path(&project_path).unwrap_err();

    assert!(matches!(error, ProjectFileError::InvalidJson { .. }));
}

#[test]
fn rejects_unsupported_schema_version() {
    let temp_dir = tempfile::tempdir().unwrap();
    let project_path = temp_dir.path().join("future.alita");
    fs::write(
        &project_path,
        r#"{"schemaVersion":99,"projectId":"x","name":"Future","path":"D:\\Projects\\future.alita","createdAt":"2026-05-09T12:00:00.000Z","updatedAt":"2026-05-09T12:00:00.000Z","messages":[],"graph":null,"attachments":[],"modelRef":null,"toolSnapshot":[],"runHistory":[]}"#,
    )
    .unwrap();

    let error = load_project_from_path(&project_path).unwrap_err();

    assert!(matches!(
        error,
        ProjectFileError::UnsupportedSchema { version: 99 }
    ));
}

#[test]
fn missing_attachment_paths_are_reported_as_warnings() {
    let temp_dir = tempfile::tempdir().unwrap();
    let project_path = temp_dir.path().join("missing-attachment.alita");
    let missing_path = temp_dir.path().join("missing.docx");
    let mut project = new_project(
        "Missing Attachment",
        project_path.to_string_lossy().as_ref(),
    );
    project.attachments.push(
        serde_json::from_value(serde_json::json!({
            "attachmentId": "attachment-1",
            "name": "missing.docx",
            "path": missing_path.to_string_lossy(),
            "originalPath": missing_path.to_string_lossy(),
            "sizeBytes": 128,
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "fileExists": true
        }))
        .unwrap(),
    );

    save_project_to_path(&project_path, &project).unwrap();
    let result = load_project_from_path(&project_path).unwrap();

    assert_eq!(result.warnings.len(), 1);
    assert_eq!(result.warnings[0].code, "missing_attachment");
    assert!(!result.project.attachments[0].file_exists);
}
