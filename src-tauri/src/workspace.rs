use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone)]
pub struct Workspace {
    root: PathBuf,
}

impl Workspace {
    pub fn create(base_dir: &Path, task_id: &str) -> std::io::Result<Self> {
        if !is_valid_task_id(task_id) {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "task_id must contain only ASCII letters, digits, '-' or '_'",
            ));
        }

        let canonical_base = base_dir.canonicalize()?;
        let root = canonical_base.join(task_id);
        if !root.starts_with(&canonical_base) {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "workspace root must be inside base directory",
            ));
        }

        fs::create_dir_all(&root)?;

        let canonical_root = root.canonicalize()?;
        if !is_expected_workspace_root(&canonical_base, &canonical_root, task_id) {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "workspace root must be a direct child of base directory named by task_id",
            ));
        }

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
            fs::create_dir_all(canonical_root.join(child))?;
        }

        Ok(Self {
            root: canonical_root,
        })
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn inputs_dir(&self) -> PathBuf {
        self.root.join("inputs")
    }

    pub fn temp_dir(&self) -> PathBuf {
        self.root.join("temp")
    }

    pub fn outputs_dir(&self) -> PathBuf {
        self.root.join("outputs")
    }

    pub fn artifacts_dir(&self) -> PathBuf {
        self.root.join("artifacts")
    }

    pub fn logs_dir(&self) -> PathBuf {
        self.root.join("logs")
    }

    pub fn node_runs_dir(&self) -> PathBuf {
        self.root.join("node-runs")
    }

    pub fn manifests_dir(&self) -> PathBuf {
        self.root.join("manifests")
    }

    pub fn security_dir(&self) -> PathBuf {
        self.root.join("security")
    }

    pub fn ensure_inside_workspace(&self, path: &Path) -> Result<(), String> {
        let root = self.root.canonicalize().map_err(|error| {
            format!(
                "failed to canonicalize workspace root '{}': {error}",
                self.root.display()
            )
        })?;
        let candidate = path.canonicalize().map_err(|error| {
            format!(
                "failed to canonicalize candidate path '{}': {error}",
                path.display()
            )
        })?;

        if candidate.starts_with(&root) {
            Ok(())
        } else {
            Err(format!(
                "path '{}' is outside workspace '{}'",
                candidate.display(),
                root.display()
            ))
        }
    }
}

fn is_valid_task_id(task_id: &str) -> bool {
    !task_id.is_empty()
        && task_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-' || byte == b'_')
}

fn is_expected_workspace_root(canonical_base: &Path, canonical_root: &Path, task_id: &str) -> bool {
    canonical_root.starts_with(canonical_base)
        && canonical_root.parent() == Some(canonical_base)
        && canonical_root.file_name().and_then(|name| name.to_str()) == Some(task_id)
}
