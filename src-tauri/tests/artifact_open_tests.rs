use alita_lib::commands::{
    open_artifact_command, read_artifact_preview_from_path, reveal_artifact_command,
};
use std::fs;

#[test]
fn builds_windows_reveal_command_with_select_argument() {
    let command = reveal_artifact_command("D:\\Project Files\\report.md");

    if cfg!(windows) {
        assert_eq!(command.program, "explorer");
        assert_eq!(
            command.args,
            vec!["/select,D:\\Project Files\\report.md".to_string()]
        );
    }
}

#[test]
fn builds_windows_open_command_with_default_file_handler() {
    let command = open_artifact_command("D:\\Project Files\\report.md");

    if cfg!(windows) {
        assert_eq!(command.program, "cmd");
        assert_eq!(
            command.args,
            vec![
                "/C".to_string(),
                "start".to_string(),
                "".to_string(),
                "D:\\Project Files\\report.md".to_string()
            ]
        );
    }
}

#[test]
fn reads_utf8_artifact_preview() {
    let temp_dir = tempfile::tempdir().expect("tempdir");
    let artifact_path = temp_dir.path().join("report.md");
    fs::write(&artifact_path, "# Report\n\nAlpha").expect("write artifact");

    let preview = read_artifact_preview_from_path(&artifact_path, 1024).expect("preview");

    assert_eq!(preview.file_name, "report.md");
    assert_eq!(preview.size_bytes, 15);
    assert_eq!(preview.content, "# Report\n\nAlpha");
    assert!(!preview.truncated);
}

#[test]
fn truncates_large_artifact_preview() {
    let temp_dir = tempfile::tempdir().expect("tempdir");
    let artifact_path = temp_dir.path().join("large.md");
    fs::write(&artifact_path, "0123456789").expect("write artifact");

    let preview = read_artifact_preview_from_path(&artifact_path, 5).expect("preview");

    assert_eq!(preview.content, "01234");
    assert!(preview.truncated);
}
