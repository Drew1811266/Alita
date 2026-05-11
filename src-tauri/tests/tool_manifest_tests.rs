use alita_lib::tools::ToolManifest;
use serde_json::json;
use std::fs;

#[test]
fn loads_document_manifest_identity_and_permissions() {
    let manifest = ToolManifest::from_path("../tool-packages/document/manifest.json")
        .expect("document manifest should load");

    assert_eq!(manifest.tool_id, "document.read_write");
    assert_eq!(manifest.name, "文档处理工具包");
    assert_eq!(manifest.source_type, "python_plugin");
    assert_eq!(
        manifest.permissions,
        vec![
            "read_project_files",
            "write_project_outputs",
            "run_python_plugin"
        ]
    );
}

#[test]
fn loads_document_manifest_schemas_and_policies() {
    let manifest = ToolManifest::from_path("../tool-packages/document/manifest.json")
        .expect("document manifest should load");

    let operation_enum = manifest.input_schema["properties"]["operation"]["enum"]
        .as_array()
        .expect("operation enum should be an array");

    assert!(operation_enum.iter().any(|value| value == "write_docx"));
    assert_eq!(manifest.examples[0]["title"], "读取多个文档");
    assert_eq!(manifest.examples[2]["input"]["operation"], "write_docx");
    assert_eq!(manifest.timeout_policy["seconds"], 60);
    assert_eq!(manifest.artifact_policy["writes_to"], "outputs");
}

#[test]
fn invalid_manifest_json_returns_error() {
    let temp_dir = tempfile::tempdir().expect("temp dir should be created");
    let manifest_path = temp_dir.path().join("manifest.json");
    fs::write(&manifest_path, "{ invalid json").expect("invalid manifest should be written");

    let error = ToolManifest::from_path(&manifest_path).expect_err("invalid JSON should fail");

    assert!(error.contains("parse"));
}

#[test]
fn empty_critical_manifest_fields_return_error() {
    let temp_dir = tempfile::tempdir().expect("temp dir should be created");
    let manifest_path = temp_dir.path().join("manifest.json");
    let mut manifest = valid_manifest();
    manifest["tool_id"] = json!("");
    fs::write(&manifest_path, manifest.to_string()).expect("manifest should be written");

    let error = ToolManifest::from_path(&manifest_path).expect_err("invalid manifest should fail");

    assert!(error.contains("tool_id"));
}

#[test]
fn empty_examples_return_error() {
    let temp_dir = tempfile::tempdir().expect("temp dir should be created");
    let manifest_path = temp_dir.path().join("manifest.json");
    let mut manifest = valid_manifest();
    manifest["examples"] = json!([]);
    fs::write(&manifest_path, manifest.to_string()).expect("manifest should be written");

    let error = ToolManifest::from_path(&manifest_path).expect_err("invalid manifest should fail");

    assert!(error.contains("examples"));
}

#[test]
fn non_object_policy_returns_error() {
    let temp_dir = tempfile::tempdir().expect("temp dir should be created");
    let manifest_path = temp_dir.path().join("manifest.json");
    let mut manifest = valid_manifest();
    manifest["timeout_policy"] = json!("sixty seconds");
    fs::write(&manifest_path, manifest.to_string()).expect("manifest should be written");

    let error = ToolManifest::from_path(&manifest_path).expect_err("invalid manifest should fail");

    assert!(error.contains("timeout_policy"));
}

#[test]
fn loads_extended_manifest_fields() {
    let temp_dir = tempfile::tempdir().expect("temp dir should be created");
    let manifest_path = temp_dir.path().join("manifest.json");
    let mut manifest = valid_manifest();
    manifest["runtime"] = json!("python_sidecar");
    manifest["capabilities"] = json!(["document.convert.markdown"]);
    manifest["package"] = json!({
        "name": "markitdown",
        "source": "github",
        "upstreamUrl": "https://github.com/microsoft/markitdown",
        "lockedVersion": "latest-compatible"
    });
    manifest["operations"] = json!([
        {
            "name": "convert_local_file",
            "description": "Convert a local document to Markdown"
        }
    ]);
    manifest["dependency_policy"] = json!({
        "python": ["markitdown[pdf,docx,pptx,xlsx]"]
    });
    manifest["security_policy"] = json!({
        "network": false,
        "plugins": false,
        "maxFileSizeMb": 100
    });
    manifest["node_templates"] = json!([
        {
            "nodeType": "fixed_tool",
            "displayName": "文档转 Markdown"
        }
    ]);
    fs::write(&manifest_path, manifest.to_string()).expect("manifest should be written");

    let manifest = ToolManifest::from_path(&manifest_path).expect("manifest should load");

    assert_eq!(manifest.runtime.as_deref(), Some("python_sidecar"));
    assert_eq!(manifest.capabilities, vec!["document.convert.markdown"]);

    let package = manifest.package.expect("package should load");
    assert_eq!(package.name, "markitdown");
    assert_eq!(package.source, "github");
    assert_eq!(
        package.upstream_url.as_deref(),
        Some("https://github.com/microsoft/markitdown")
    );
    assert_eq!(package.locked_version.as_deref(), Some("latest-compatible"));

    assert_eq!(manifest.operations[0].name, "convert_local_file");
    assert_eq!(
        manifest.operations[0].description,
        "Convert a local document to Markdown"
    );
    assert_eq!(
        manifest.dependency_policy["python"][0],
        "markitdown[pdf,docx,pptx,xlsx]"
    );
    assert_eq!(manifest.security_policy["network"], false);
    assert_eq!(manifest.security_policy["plugins"], false);
    assert_eq!(manifest.security_policy["maxFileSizeMb"], 100);
    assert_eq!(manifest.node_templates[0]["nodeType"], "fixed_tool");
    assert_eq!(manifest.node_templates[0]["displayName"], "文档转 Markdown");
}

#[test]
fn loads_markitdown_manifest() {
    let manifest = ToolManifest::from_path("../tool-packages/markitdown/manifest.json")
        .expect("markitdown manifest should load");

    assert_eq!(manifest.tool_id, "document.markitdown_convert");
    assert_eq!(manifest.source_type, "external_python_package");
    assert_eq!(manifest.runtime.as_deref(), Some("python_sidecar"));

    let package = manifest.package.expect("package should load");
    assert_eq!(package.name, "markitdown");
    assert_eq!(package.locked_version.as_deref(), Some("0.1.5"));

    assert!(manifest
        .capabilities
        .contains(&"document.convert.markdown".to_string()));
    assert!(manifest
        .permissions
        .contains(&"read_project_files".to_string()));
    assert_eq!(manifest.security_policy["network"], false);
    assert_eq!(manifest.security_policy["plugins"], false);
    assert_eq!(manifest.node_templates[0]["nodeType"], "fixed_tool");
    assert_eq!(
        manifest.node_templates[0]["inputPorts"][0]["dataType"],
        "document"
    );
    assert_eq!(
        manifest.node_templates[0]["outputPorts"][0]["label"],
        "Markdown"
    );
}

fn valid_manifest() -> serde_json::Value {
    json!({
        "tool_id": "document.read_write",
        "name": "Document Tool",
        "description": "Read and write documents",
        "version": "0.1.0",
        "source_type": "python_plugin",
        "license": "internal",
        "entrypoint": "python/tools/document_tool.py",
        "input_schema": {},
        "output_schema": {},
        "permissions": ["read_project_files"],
        "examples": [{ "title": "Read", "input": { "operation": "read" } }],
        "error_codes": ["read_failed"],
        "timeout_policy": { "seconds": 60 },
        "artifact_policy": { "writes_to": "outputs" }
    })
}
