use alita_lib::commands::attachment_metadata_for_path;
use std::fs;

#[test]
fn reads_attachment_metadata_from_existing_file() {
    let temp_dir = tempfile::tempdir().unwrap();
    let file_path = temp_dir.path().join("input.docx");
    fs::write(&file_path, b"hello").unwrap();

    let attachment = attachment_metadata_for_path(&file_path).unwrap();

    assert!(attachment.attachment_id.starts_with("attachment-"));
    assert_eq!(attachment.name, "input.docx");
    assert_eq!(attachment.path, file_path.to_string_lossy());
    assert_eq!(attachment.size_bytes, 5);
    assert_eq!(
        attachment.mime_type,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    );
}

#[test]
fn rejects_missing_attachment_file() {
    let temp_dir = tempfile::tempdir().unwrap();
    let missing_path = temp_dir.path().join("missing.pdf");

    let error = attachment_metadata_for_path(&missing_path).unwrap_err();

    assert!(error.contains("failed to read attachment metadata"));
}
