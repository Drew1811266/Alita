use alita_lib::workspace::Workspace;
use std::fs;
use std::io::ErrorKind;

#[test]
fn creates_workspace_directories() {
    let base_dir = tempfile::tempdir().unwrap();

    let workspace = Workspace::create(base_dir.path(), "task-1").unwrap();

    assert!(workspace.root().is_dir());
    assert!(workspace.inputs_dir().is_dir());
    assert!(workspace.temp_dir().is_dir());
    assert!(workspace.outputs_dir().is_dir());
    assert!(workspace.artifacts_dir().is_dir());
    assert!(workspace.logs_dir().is_dir());
    assert!(workspace.node_runs_dir().is_dir());
    assert!(workspace.manifests_dir().is_dir());
    assert!(workspace.security_dir().is_dir());
}

#[test]
fn rejects_paths_outside_workspace() {
    let base_dir = tempfile::tempdir().unwrap();
    let workspace = Workspace::create(base_dir.path(), "task-1").unwrap();
    let outside_file = base_dir.path().join("outside.txt");
    fs::write(&outside_file, "outside").unwrap();

    let result = workspace.ensure_inside_workspace(&outside_file);

    assert!(result.is_err());
}

#[test]
fn accepts_paths_inside_workspace() {
    let base_dir = tempfile::tempdir().unwrap();
    let workspace = Workspace::create(base_dir.path(), "task-1").unwrap();
    let input_file = workspace.inputs_dir().join("input.txt");
    fs::write(&input_file, "inside").unwrap();

    let result = workspace.ensure_inside_workspace(&input_file);

    assert!(result.is_ok());
}

#[test]
fn rejects_parent_directory_task_id() {
    let base_dir = tempfile::tempdir().unwrap();

    let result = Workspace::create(base_dir.path(), "../escape");

    assert!(result.is_err());
    assert!(!base_dir.path().parent().unwrap().join("escape").exists());
}

#[test]
fn rejects_windows_separator_task_id() {
    let base_dir = tempfile::tempdir().unwrap();

    let result = Workspace::create(base_dir.path(), "..\\escape");

    assert!(result.is_err());
}

#[test]
fn rejects_absolute_path_task_id() {
    let base_dir = tempfile::tempdir().unwrap();
    let absolute_task_id = std::env::temp_dir()
        .join("escape-task")
        .to_string_lossy()
        .into_owned();

    let result = Workspace::create(base_dir.path(), &absolute_task_id);

    assert!(result.is_err());
}

#[test]
fn rejects_sibling_paths_with_matching_prefix() {
    let base_dir = tempfile::tempdir().unwrap();
    let workspace = Workspace::create(base_dir.path(), "task").unwrap();
    let sibling_dir = base_dir.path().join("task-evil");
    fs::create_dir_all(&sibling_dir).unwrap();

    let result = workspace.ensure_inside_workspace(&sibling_dir);

    assert!(result.is_err());
}

#[test]
fn rejects_symlinked_workspace_root_before_creating_child_directories() {
    let base_dir = tempfile::tempdir().unwrap();
    let outside_dir = tempfile::tempdir().unwrap();
    let symlink_path = base_dir.path().join("task_symlink");

    match symlink_dir(outside_dir.path(), &symlink_path) {
        Ok(()) => {}
        Err(error) if is_symlink_creation_unavailable(&error) => {
            eprintln!(
                "skipping symlink boundary regression because symlink creation is unavailable: {error}"
            );
            return;
        }
        Err(error) => panic!("failed to create symlink for regression test: {error}"),
    }

    let result = Workspace::create(base_dir.path(), "task_symlink");

    assert!(result.is_err());
    for child in [
        "inputs",
        "temp",
        "outputs",
        "artifacts",
        "logs",
        "node-runs",
        "manifests",
        "security",
    ] {
        assert!(!outside_dir.path().join(child).exists());
    }
}

#[test]
fn rejects_symlinked_workspace_root_aliasing_directory_inside_base() {
    let base_dir = tempfile::tempdir().unwrap();
    let other_dir = base_dir.path().join("other");
    fs::create_dir_all(&other_dir).unwrap();
    let symlink_path = base_dir.path().join("task_symlink_inside");

    match symlink_dir(&other_dir, &symlink_path) {
        Ok(()) => {}
        Err(error) if is_symlink_creation_unavailable(&error) => {
            eprintln!(
                "skipping inside-base symlink regression because symlink creation is unavailable: {error}"
            );
            return;
        }
        Err(error) => panic!("failed to create symlink for inside-base regression test: {error}"),
    }

    let result = Workspace::create(base_dir.path(), "task_symlink_inside");

    assert!(result.is_err());
    for child in [
        "inputs",
        "temp",
        "outputs",
        "artifacts",
        "logs",
        "node-runs",
        "manifests",
        "security",
    ] {
        assert!(!other_dir.join(child).exists());
    }
}

fn is_symlink_creation_unavailable(error: &std::io::Error) -> bool {
    matches!(
        error.kind(),
        ErrorKind::PermissionDenied | ErrorKind::Unsupported
    ) || error.raw_os_error() == Some(1314)
}

#[cfg(windows)]
fn symlink_dir(original: &std::path::Path, link: &std::path::Path) -> std::io::Result<()> {
    std::os::windows::fs::symlink_dir(original, link)
}

#[cfg(unix)]
fn symlink_dir(original: &std::path::Path, link: &std::path::Path) -> std::io::Result<()> {
    std::os::unix::fs::symlink(original, link)
}
