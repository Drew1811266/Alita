use alita_lib::commands::{open_artifact_command, reveal_artifact_command};

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
