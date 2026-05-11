# Alita MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows-first MVP that lets a user chat with a local AI agent, attach txt/md/docx files, see a top-to-bottom node graph, run fixed document tools, and export md/docx artifacts.

**Architecture:** Tauri hosts a React/TypeScript frontend and a Rust trusted core. Rust owns workspace files, tool execution, event persistence, and model adapter boundaries; a Python LangGraph sidecar owns Agent state transitions and planning. The first vertical slice uses a mock model path for reliable tests and a llama.cpp adapter boundary for the local model runtime.

**Tech Stack:** Tauri 2, Rust, React + TypeScript + Vite, `@xyflow/react`, Python 3.10+, FastAPI, LangGraph, Pydantic, python-docx, pytest.

---

## Source References

- Tauri 2 official site confirms the project creation command and the Rust + web frontend model: https://tauri.app/
- React Flow official docs use the `@xyflow/react` package and require importing its stylesheet: https://reactflow.dev/learn
- LangGraph official docs install with `pip install -U langgraph` and require Python 3.10+: https://docs.langchain.com/oss/python/langgraph/install
- llama.cpp server docs describe OpenAI-compatible chat, responses, embeddings, schema-constrained JSON, function calling, and model load/unload routes: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

## Scope Guardrails

This plan implements the confirmed MVP only:

- Included: Tauri shell, React UI, Rust domain/event/workspace layers, Python LangGraph sidecar, document tool package, fixed node execution, lightweight node popover, protocol placeholder for temporary nodes.
- Excluded from implementation: PDF/xlsx/pptx, real temporary script execution, tool marketplace, external API provider, full multimodal runtime, complex project history UI.

## Planned File Structure

```text
package.json
vite.config.ts
tsconfig.json
src/
  main.tsx
  app/App.tsx
  app/app.css
  shared/types.ts
  shared/events.ts
  features/chat/ChatPanel.tsx
  features/canvas/NodeCanvas.tsx
  features/canvas/NodePopover.tsx
  features/canvas/nodeLayout.ts
  features/task/useTaskEvents.ts
src-tauri/
  Cargo.toml
  tauri.conf.json
  src/main.rs
  src/domain.rs
  src/events.rs
  src/workspace.rs
  src/model.rs
  src/tools.rs
  src/agent_client.rs
  src/commands.rs
  tests/domain_tests.rs
  tests/workspace_tests.rs
python/
  pyproject.toml
  agent_service/app.py
  agent_service/graph.py
  agent_service/schemas.py
  tools/document_tool.py
  tests/test_graph.py
  tests/test_document_tool.py
tool-packages/
  document/manifest.json
```

## Task 1: Scaffold the Tauri + React Workspace

**Files:**
- Create: `package.json`
- Create: `vite.config.ts`
- Create: `tsconfig.json`
- Create: `index.html`
- Create: `src/main.tsx`
- Create: `src/app/App.tsx`
- Create: `src/app/app.css`
- Create: `src-tauri/Cargo.toml`
- Create: `src-tauri/tauri.conf.json`
- Create: `src-tauri/build.rs`
- Create: `src-tauri/src/main.rs`
- Create: `src-tauri/src/lib.rs`
- Create: `.gitignore`
- Create: `package-lock.json`

- [x] **Step 1: Create the app scaffold**

Run:

```powershell
npm create tauri-app@latest . -- --template react-ts
```

Expected: the command creates a Tauri project with `src/`, `src-tauri/`, and a React TypeScript frontend. If the command refuses to scaffold into a non-empty directory, create the files listed in this task manually using the snippets below.

- [x] **Step 2: Normalize `package.json` scripts and dependencies**

Use this content:

```json
{
  "name": "alita",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "tauri dev",
    "build": "tauri build",
    "frontend:dev": "vite",
    "frontend:build": "tsc && vite build",
    "frontend:test": "vitest run",
    "frontend:lint": "tsc --noEmit"
  },
  "dependencies": {
    "@tauri-apps/api": "2.11.0",
    "@xyflow/react": "12.10.2",
    "clsx": "2.1.1",
    "react": "19.2.6",
    "react-dom": "19.2.6"
  },
  "devDependencies": {
    "@tauri-apps/cli": "2.11.1",
    "@types/react": "19.2.14",
    "@types/react-dom": "19.2.3",
    "@vitejs/plugin-react": "6.0.1",
    "typescript": "6.0.3",
    "vite": "8.0.11",
    "vitest": "4.1.5"
  }
}
```

- [x] **Step 3: Create the initial React app shell**

Use this content for `src/app/App.tsx`:

```tsx
import "./app.css";

export function App() {
  return (
    <main className="appShell">
      <section className="chatColumn">聊天区</section>
      <section className="canvasColumn">节点画布</section>
    </main>
  );
}
```

Use this content for `src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./app/App";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

Use this content for `src/app/app.css`:

```css
:root {
  color: #123631;
  background: #f0fdfa;
  font-family: "Microsoft YaHei", "Segoe UI", system-ui, sans-serif;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
}

.appShell {
  width: 100vw;
  height: 100vh;
  display: grid;
  grid-template-columns: 40fr 60fr;
  gap: 12px;
  padding: 12px;
}

.chatColumn,
.canvasColumn {
  min-width: 0;
  border: 1px solid #c7d8d5;
  border-radius: 8px;
  background: #ffffff;
  overflow: hidden;
}
```

- [x] **Step 4: Verify the frontend typecheck**

Run:

```powershell
npm run frontend:lint
```

Expected: TypeScript exits with code 0.

- [x] **Step 5: Verify the Tauri shell starts**

Run:

```powershell
npm run dev
```

Expected: a desktop window opens with the left chat and right canvas placeholder.

- [x] **Step 6: Commit or checkpoint**

If this workspace has Git initialized:

```powershell
git add package.json vite.config.ts tsconfig.json index.html src src-tauri
git commit -m "chore: scaffold tauri react app"
```

If this workspace is not a Git repository, record the changed file list in the task notes and continue.

## Task 2: Define Shared Domain Types

**Files:**
- Create: `src/shared/types.ts`
- Create: `src/shared/events.ts`
- Create: `src-tauri/src/domain.rs`
- Modify: `src-tauri/src/lib.rs`
- Modify: `src-tauri/Cargo.toml`
- Create/Update: `src-tauri/Cargo.lock`
- Test: `src-tauri/tests/domain_tests.rs`

- [x] **Step 1: Add TypeScript domain types**

Create `src/shared/types.ts`:

```ts
export type NodeStatus =
  | "waiting"
  | "ready"
  | "running"
  | "completed"
  | "failed"
  | "needs_user_input"
  | "needs_permission"
  | "skipped";

export type NodeType = "fixed_tool" | "model" | "output" | "temporary_placeholder";

export interface NodePort {
  id: string;
  label: string;
  dataType: "text" | "document" | "artifact" | "json";
}

export interface AgentNode {
  nodeId: string;
  nodeType: NodeType;
  displayName: string;
  status: NodeStatus;
  inputPorts: NodePort[];
  outputPorts: NodePort[];
  dependencies: string[];
  toolRef?: string;
  modelRef?: string;
  summary: string;
  createdBy: "agent" | "system";
  artifactRefs: string[];
  retryCount: number;
  position: { x: number; y: number };
}

export interface ChatAttachment {
  attachmentId: string;
  name: string;
  path: string;
  sizeBytes: number;
  mimeType: string;
}

export interface ChatMessage {
  messageId: string;
  role: "user" | "assistant" | "system";
  content: string;
  attachments: ChatAttachment[];
  createdAt: string;
}

export interface NodeGraph {
  graphId: string;
  nodes: AgentNode[];
  edges: Array<{ id: string; source: string; target: string }>;
}
```

Create `src/shared/events.ts`:

```ts
import type { AgentNode, ChatMessage, NodeGraph } from "./types";

export type BackendEvent =
  | { type: "message.created"; payload: { message: ChatMessage } }
  | { type: "input.required"; payload: { prompt: string; missing: string[] } }
  | { type: "node_graph.created"; payload: { graph: NodeGraph } }
  | { type: "node.created"; payload: { node: AgentNode } }
  | { type: "node.updated"; payload: { node: AgentNode } }
  | { type: "node.running"; payload: { nodeId: string } }
  | { type: "node.completed"; payload: { nodeId: string; artifactRefs: string[] } }
  | { type: "node.failed"; payload: { nodeId: string; error: string } }
  | { type: "permission.required"; payload: { nodeId: string; permissions: string[] } }
  | { type: "artifact.created"; payload: { artifactId: string; path: string } }
  | { type: "task.completed"; payload: { taskId: string } }
  | { type: "task.failed"; payload: { taskId: string; error: string } };
```

- [x] **Step 2: Add Rust domain types**

Create `src-tauri/src/domain.rs`:

```rust
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
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

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum NodeType {
    FixedTool,
    Model,
    Output,
    TemporaryPlaceholder,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct NodePort {
    pub id: String,
    pub label: String,
    pub data_type: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
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

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct CanvasPosition {
    pub x: f64,
    pub y: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ChatAttachment {
    pub attachment_id: String,
    pub name: String,
    pub path: String,
    pub size_bytes: u64,
    pub mime_type: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ChatMessage {
    pub message_id: String,
    pub role: String,
    pub content: String,
    pub attachments: Vec<ChatAttachment>,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct NodeGraph {
    pub graph_id: String,
    pub nodes: Vec<AgentNode>,
    pub edges: Vec<NodeEdge>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct NodeEdge {
    pub id: String,
    pub source: String,
    pub target: String,
}
```

- [x] **Step 3: Wire Rust module**

Modify `src-tauri/src/lib.rs`. Keep `main.rs` as the Tauri 2 binary shim that calls `alita_lib::run()`.

```rust
pub mod domain;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

- [x] **Step 4: Add Rust domain serialization tests**

Create `src-tauri/tests/domain_tests.rs`:

```rust
#[path = "../src/domain.rs"]
mod domain;

use domain::{CanvasPosition, NodeStatus, NodeType, AgentNode, NodePort};

#[test]
fn serializes_node_status_as_snake_case() {
    let json = serde_json::to_string(&NodeStatus::NeedsUserInput).unwrap();
    assert_eq!(json, "\"needs_user_input\"");
}

#[test]
fn builds_agent_node_with_ports() {
    let node = AgentNode {
        node_id: "node-doc-read".to_string(),
        node_type: NodeType::FixedTool,
        display_name: "文档读取".to_string(),
        status: NodeStatus::Waiting,
        input_ports: vec![NodePort {
            id: "in".to_string(),
            label: "输入".to_string(),
            data_type: "document".to_string(),
        }],
        output_ports: vec![NodePort {
            id: "out".to_string(),
            label: "输出".to_string(),
            data_type: "text".to_string(),
        }],
        dependencies: vec![],
        tool_ref: Some("document.read".to_string()),
        model_ref: None,
        summary: "读取文档内容".to_string(),
        created_by: "agent".to_string(),
        artifact_refs: vec![],
        retry_count: 0,
        position: CanvasPosition { x: 280.0, y: 80.0 },
    };

    assert_eq!(node.input_ports.len(), 1);
    assert_eq!(node.output_ports[0].data_type, "text");

    let value = serde_json::to_value(&node).unwrap();
    assert_eq!(value["nodeId"], "node-doc-read");
    assert_eq!(value["nodeType"], "fixed_tool");
    assert_eq!(value["inputPorts"][0]["dataType"], "document");
}
```

- [x] **Step 5: Run Rust tests**

Run:

```powershell
cd src-tauri
& "$env:USERPROFILE\.cargo\bin\cargo.exe" test --test domain_tests
```

Expected: workspace tests pass.
If the command fails on this Windows machine because `link.exe` or Windows SDK libraries such as `kernel32.lib` are unavailable, record that as an environment blocker and continue only after code review confirms the source changes.

- [x] **Step 6: Commit or checkpoint**

```powershell
git add src/shared src-tauri/src/domain.rs src-tauri/src/lib.rs src-tauri/tests/domain_tests.rs src-tauri/Cargo.toml src-tauri/Cargo.lock
git commit -m "feat: define shared task and node domain types"
```

If Git is unavailable, record the changed file list.

## Task 3: Implement Workspace and Audit Log Boundaries

**Files:**
- Create: `src-tauri/src/workspace.rs`
- Modify: `src-tauri/src/lib.rs`
- Modify: `src-tauri/Cargo.toml`
- Create/Update: `src-tauri/Cargo.lock`
- Test: `src-tauri/tests/workspace_tests.rs`

- [x] **Step 1: Write failing workspace tests**

Create `src-tauri/tests/workspace_tests.rs`:

```rust
#[path = "../src/workspace.rs"]
mod workspace;

use std::io::ErrorKind;
use std::fs;

#[test]
fn creates_workspace_directories() {
    let root = tempfile::tempdir().unwrap();
    let ws = workspace::Workspace::create(root.path(), "task-1").unwrap();

    assert!(ws.inputs_dir().exists());
    assert!(ws.temp_dir().exists());
    assert!(ws.outputs_dir().exists());
    assert!(ws.artifacts_dir().exists());
    assert!(ws.logs_dir().exists());
    assert!(ws.node_runs_dir().exists());
    assert!(ws.manifests_dir().exists());
    assert!(ws.security_dir().exists());
}

#[test]
fn rejects_paths_outside_workspace() {
    let root = tempfile::tempdir().unwrap();
    let ws = workspace::Workspace::create(root.path(), "task-2").unwrap();
    let outside = root.path().join("outside.txt");
    fs::write(&outside, "outside").unwrap();

    assert!(ws.ensure_inside_workspace(&outside).is_err());
}

#[test]
fn rejects_parent_directory_task_id() {
    let root = tempfile::tempdir().unwrap();

    assert!(workspace::Workspace::create(root.path(), "../escape").is_err());
}

#[test]
fn rejects_windows_separator_task_id() {
    let root = tempfile::tempdir().unwrap();

    assert!(workspace::Workspace::create(root.path(), "..\\escape").is_err());
}

#[test]
fn rejects_absolute_path_task_id() {
    let root = tempfile::tempdir().unwrap();
    let absolute_task_id = std::env::temp_dir()
        .join("escape-task")
        .to_string_lossy()
        .into_owned();

    assert!(workspace::Workspace::create(root.path(), &absolute_task_id).is_err());
}

#[test]
fn rejects_sibling_paths_with_matching_prefix() {
    let root = tempfile::tempdir().unwrap();
    let ws = workspace::Workspace::create(root.path(), "task").unwrap();
    let sibling = root.path().join("task-evil");
    fs::create_dir_all(&sibling).unwrap();

    assert!(ws.ensure_inside_workspace(&sibling).is_err());
}

#[test]
fn rejects_symlinked_workspace_root_before_creating_child_directories() {
    let root = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    let symlink = root.path().join("task_symlink");

    match symlink_dir(outside.path(), &symlink) {
        Ok(()) => {}
        Err(error)
            if matches!(
                error.kind(),
                ErrorKind::PermissionDenied | ErrorKind::Unsupported
            ) =>
        {
            eprintln!(
                "skipping symlink boundary regression because symlink creation is unavailable: {error}"
            );
            return;
        }
        Err(error) => panic!("failed to create symlink for regression test: {error}"),
    }

    assert!(workspace::Workspace::create(root.path(), "task_symlink").is_err());
    for child in ["inputs", "artifacts", "logs", "node-runs", "manifests", "security"] {
        assert!(!outside.path().join(child).exists());
    }
}

#[test]
fn rejects_symlinked_workspace_root_aliasing_directory_inside_base() {
    let root = tempfile::tempdir().unwrap();
    let other = root.path().join("other");
    fs::create_dir_all(&other).unwrap();
    let symlink = root.path().join("task_symlink_inside");

    match symlink_dir(&other, &symlink) {
        Ok(()) => {}
        Err(error)
            if matches!(
                error.kind(),
                ErrorKind::PermissionDenied | ErrorKind::Unsupported
            ) =>
        {
            eprintln!(
                "skipping inside-base symlink regression because symlink creation is unavailable: {error}"
            );
            return;
        }
        Err(error) => panic!("failed to create symlink for inside-base regression test: {error}"),
    }

    assert!(workspace::Workspace::create(root.path(), "task_symlink_inside").is_err());
    for child in ["inputs", "artifacts", "logs", "node-runs", "manifests", "security"] {
        assert!(!other.join(child).exists());
    }
}

#[cfg(windows)]
fn symlink_dir(original: &std::path::Path, link: &std::path::Path) -> std::io::Result<()> {
    std::os::windows::fs::symlink_dir(original, link)
}

#[cfg(unix)]
fn symlink_dir(original: &std::path::Path, link: &std::path::Path) -> std::io::Result<()> {
    std::os::unix::fs::symlink(original, link)
}
```

- [x] **Step 2: Add test dependencies**

Add to `src-tauri/Cargo.toml`:

```toml
[dev-dependencies]
tempfile = "3"
```

- [x] **Step 3: Run tests to verify failure**

Run:

```powershell
cd src-tauri
& "$env:USERPROFILE\.cargo\bin\cargo.exe" test --test workspace_tests
```

Expected: FAIL because `workspace.rs` does not exist or functions are undefined.
If the command fails earlier because `link.exe` or Windows SDK libraries are unavailable, record that as an environment blocker instead of a source-code failure.

- [x] **Step 4: Implement workspace boundaries**

Create `src-tauri/src/workspace.rs`:

```rust
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
        let root = self
            .root
            .canonicalize()
            .map_err(|err| format!("workspace root unavailable: {err}"))?;
        let candidate = path
            .canonicalize()
            .map_err(|err| format!("path unavailable: {err}"))?;

        if candidate.starts_with(root) {
            Ok(())
        } else {
            Err(format!("path outside workspace: {}", candidate.display()))
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
```

- [x] **Step 5: Wire Rust module**

Modify `src-tauri/src/lib.rs`:

```rust
pub mod domain;
pub mod workspace;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

- [x] **Step 6: Run workspace tests**

Run:

```powershell
cd src-tauri
& "$env:USERPROFILE\.cargo\bin\cargo.exe" test --test workspace_tests
```

Expected: both tests pass.
If the command fails because `link.exe` or Windows SDK libraries are unavailable, record that as an environment blocker and continue only after code review confirms the source changes.

- [x] **Step 7: Commit or checkpoint**

```powershell
git add src-tauri/src/workspace.rs src-tauri/src/lib.rs src-tauri/tests/workspace_tests.rs src-tauri/Cargo.toml src-tauri/Cargo.lock
git commit -m "feat: add workspace safety boundaries"
```

If Git is unavailable, record the changed file list.

## Task 4: Build the Minimal Chat UI

**Files:**
- Create: `src/features/chat/ChatPanel.tsx`
- Modify: `src/app/App.tsx`
- Modify: `src/app/app.css`

- [x] **Step 1: Create `ChatPanel`**

Create `src/features/chat/ChatPanel.tsx`:

```tsx
import type { ChatAttachment, ChatMessage } from "../../shared/types";

interface ChatPanelProps {
  messages: ChatMessage[];
  pendingAttachments: ChatAttachment[];
  draft: string;
  onDraftChange: (value: string) => void;
  onSend: () => void;
  onAddFile: () => void;
}

export function ChatPanel({
  messages,
  pendingAttachments,
  draft,
  onDraftChange,
  onSend,
  onAddFile,
}: ChatPanelProps) {
  return (
    <section className="chatPanel">
      <header className="panelHeader">
        <span>聊天</span>
        <span className="statusPill">简洁模式</span>
      </header>
      <div className="messageList">
        {messages.map((message) => (
          <article key={message.messageId} className={`message message-${message.role}`}>
            <p>{message.content}</p>
            {message.attachments.map((attachment) => (
              <div key={attachment.attachmentId} className="attachmentCard">
                {attachment.name}
              </div>
            ))}
          </article>
        ))}
      </div>
      <footer className="composer">
        {pendingAttachments.length > 0 && (
          <div className="attachmentRow">
            {pendingAttachments.map((attachment) => (
              <span key={attachment.attachmentId} className="attachmentChip">
                {attachment.name}
              </span>
            ))}
          </div>
        )}
        <textarea
          value={draft}
          onChange={(event) => onDraftChange(event.target.value)}
          placeholder="描述你的任务，或添加文件后一起发送..."
        />
        <div className="composerBar">
          <button type="button" className="secondaryButton" onClick={onAddFile}>
            添加文件
          </button>
          <button type="button" className="primaryButton" onClick={onSend}>
            发送
          </button>
        </div>
      </footer>
    </section>
  );
}
```

- [x] **Step 2: Wire chat into `App` with sample state**

Modify `src/app/App.tsx`:

```tsx
import { useState } from "react";
import { ChatPanel } from "../features/chat/ChatPanel";
import type { ChatAttachment, ChatMessage } from "../shared/types";
import "./app.css";

const initialMessages: ChatMessage[] = [
  {
    messageId: "m1",
    role: "user",
    content: "帮我把这个文档处理一下。",
    attachments: [],
    createdAt: new Date().toISOString(),
  },
  {
    messageId: "m2",
    role: "assistant",
    content: "请把需要处理的文档添加到聊天框里，并告诉我希望处理成什么结果。",
    attachments: [],
    createdAt: new Date().toISOString(),
  },
];

export function App() {
  const [messages, setMessages] = useState(initialMessages);
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);

  function handleAddFile() {
    setAttachments([
      {
        attachmentId: "sample-doc",
        name: "项目资料.docx",
        path: "workspace/inputs/project.docx",
        sizeBytes: 1024,
        mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      },
    ]);
  }

  function handleSend() {
    if (!draft.trim() && attachments.length === 0) {
      return;
    }
    setMessages((current) => [
      ...current,
      {
        messageId: `m-${current.length + 1}`,
        role: "user",
        content: draft.trim() || "已添加文件。",
        attachments,
        createdAt: new Date().toISOString(),
      },
    ]);
    setDraft("");
    setAttachments([]);
  }

  return (
    <main className="appShell">
      <ChatPanel
        messages={messages}
        pendingAttachments={attachments}
        draft={draft}
        onDraftChange={setDraft}
        onSend={handleSend}
        onAddFile={handleAddFile}
      />
      <section className="canvasColumn">节点画布</section>
    </main>
  );
}
```

- [x] **Step 3: Add chat CSS**

Append to `src/app/app.css`:

```css
.chatPanel {
  min-width: 0;
  border: 1px solid #c7d8d5;
  border-radius: 8px;
  background: #ffffff;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.panelHeader {
  height: 48px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 16px;
  border-bottom: 1px solid #c7d8d5;
  color: #526a66;
  font-size: 13px;
  font-weight: 720;
}

.statusPill {
  padding: 5px 9px;
  border-radius: 999px;
  background: #ccfbf1;
  color: #115e59;
  font-size: 12px;
}

.messageList {
  flex: 1;
  min-height: 0;
  padding: 16px;
  overflow: auto;
}

.message {
  width: fit-content;
  max-width: 90%;
  padding: 10px 12px;
  border: 1px solid #c7d8d5;
  border-radius: 8px;
  margin-bottom: 12px;
  color: #526a66;
}

.message-user {
  margin-left: auto;
  background: #fff7ed;
  border-color: #fed7aa;
  color: #7c2d12;
}

.message-assistant,
.message-system {
  background: #ffffff;
}

.attachmentCard,
.attachmentChip {
  border: 1px solid #fed7aa;
  background: #fff7ed;
  color: #7c2d12;
}

.attachmentCard {
  margin-top: 8px;
  padding: 7px 9px;
  border-radius: 8px;
  font-size: 13px;
}

.composer {
  margin: 0 16px 16px;
  border: 1px solid #c7d8d5;
  border-radius: 8px;
  background: #ffffff;
  overflow: hidden;
}

.attachmentRow {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 10px 0;
}

.attachmentChip {
  padding: 6px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.composer textarea {
  width: 100%;
  min-height: 92px;
  resize: none;
  border: 0;
  outline: none;
  padding: 12px;
  color: #123631;
  font: inherit;
}

.composerBar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 10px;
  border-top: 1px solid #c7d8d5;
}

.primaryButton,
.secondaryButton {
  border: 0;
  border-radius: 6px;
  padding: 7px 12px;
  font-weight: 760;
  cursor: pointer;
}

.primaryButton {
  background: #f97316;
  color: #ffffff;
}

.secondaryButton {
  background: #ccfbf1;
  color: #115e59;
}
```

- [x] **Step 4: Run frontend typecheck**

Run:

```powershell
npm run frontend:lint
```

Expected: TypeScript exits with code 0.

- [x] **Step 5: Verify manually**

Run:

```powershell
npm run dev
```

Expected: left panel shows chat messages; clicking `添加文件` adds `项目资料.docx`; clicking `发送` appends a user message with the attachment.

- [x] **Step 6: Commit or checkpoint**

```powershell
git add src/app src/features/chat
git commit -m "feat: add minimal chat panel"
```

If Git is unavailable, record the changed file list.

## Task 5: Implement the Top-to-Bottom Node Canvas

**Files:**
- Create: `src/features/canvas/nodeLayout.ts`
- Create: `src/features/canvas/NodePopover.tsx`
- Create: `src/features/canvas/NodeCanvas.tsx`
- Modify: `src/app/App.tsx`
- Modify: `src/app/app.css`

- [x] **Step 1: Create sample node graph layout**

Create `src/features/canvas/nodeLayout.ts`:

```ts
import type { AgentNode, NodeGraph } from "../../shared/types";

export function createDocumentGraph(): NodeGraph {
  const nodes: AgentNode[] = [
    makeNode("input", "fixed_tool", "文档输入", "completed", 280, 60, "读取用户添加的本地文档。"),
    makeNode("parse", "fixed_tool", "文档解析", "running", 280, 190, "提取文本、结构和元数据。"),
    makeNode("organize", "model", "内容整理", "waiting", 120, 330, "整理章节、要点和引用。"),
    makeNode("report", "fixed_tool", "报告生成", "waiting", 440, 330, "生成 Markdown 和 docx 内容。"),
    makeNode("export", "output", "导出文件", "waiting", 280, 500, "写入项目输出目录。"),
  ];

  return {
    graphId: "sample-doc-graph",
    nodes,
    edges: [
      { id: "input-parse", source: "input", target: "parse" },
      { id: "parse-organize", source: "parse", target: "organize" },
      { id: "parse-report", source: "parse", target: "report" },
      { id: "organize-export", source: "organize", target: "export" },
      { id: "report-export", source: "report", target: "export" },
    ],
  };
}

function makeNode(
  nodeId: string,
  nodeType: AgentNode["nodeType"],
  displayName: string,
  status: AgentNode["status"],
  x: number,
  y: number,
  summary: string,
): AgentNode {
  return {
    nodeId,
    nodeType,
    displayName,
    status,
    inputPorts: [{ id: "in", label: "输入", dataType: "document" }],
    outputPorts: [{ id: "out", label: "输出", dataType: "artifact" }],
    dependencies: [],
    summary,
    createdBy: "agent",
    artifactRefs: [],
    retryCount: 0,
    position: { x, y },
  };
}
```

- [x] **Step 2: Create the node popover**

Create `src/features/canvas/NodePopover.tsx`:

```tsx
import type { AgentNode } from "../../shared/types";

interface NodePopoverProps {
  node: AgentNode;
}

export function NodePopover({ node }: NodePopoverProps) {
  return (
    <aside className="nodePopover">
      <header>
        <h3>{node.displayName}</h3>
        <p>
          {node.nodeType} · {node.status}
        </p>
      </header>
      <dl>
        <dt>AI 调用目的</dt>
        <dd>{node.summary}</dd>
        <dt>将调用的功能</dt>
        <dd>{node.toolRef ?? node.modelRef ?? "内部流程节点"}</dd>
        <dt>输入</dt>
        <dd>{node.inputPorts.map((port) => port.label).join("、")}</dd>
        <dt>输出</dt>
        <dd>{node.outputPorts.map((port) => port.label).join("、")}</dd>
      </dl>
      <button type="button" className="detailsButton">
        查看详情
      </button>
    </aside>
  );
}
```

- [x] **Step 3: Create `NodeCanvas` with React Flow**

Create `src/features/canvas/NodeCanvas.tsx`:

```tsx
import { useMemo, useState } from "react";
import { Background, Handle, MarkerType, Position, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { AgentNode, NodeGraph } from "../../shared/types";
import { NodePopover } from "./NodePopover";

interface NodeCanvasProps {
  graph: NodeGraph | null;
}

export function NodeCanvas({ graph }: NodeCanvasProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const selectedNode = graph?.nodes.find((node) => node.nodeId === selectedNodeId) ?? null;

  const flowNodes = useMemo<Node[]>(() => {
    if (!graph) return [];
    return graph.nodes.map((node) => ({
      id: node.nodeId,
      type: "agentNode",
      position: node.position,
      data: { node },
    }));
  }, [graph]);

  const flowEdges = useMemo<Edge[]>(() => {
    if (!graph) return [];
    return graph.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      markerEnd: { type: MarkerType.ArrowClosed },
      type: "smoothstep",
    }));
  }, [graph]);

  if (!graph) {
    return (
      <section className="canvasPanel">
        <header className="panelHeader">
          <span>节点画布</span>
          <span className="statusPill">等待输入</span>
        </header>
        <div className="emptyCanvas">输入完整后，右侧显示自上而下的数据流节点图。</div>
      </section>
    );
  }

  return (
    <section className="canvasPanel">
      <header className="panelHeader">
        <span>节点画布</span>
        <span className="statusPill">上游 → 下游</span>
      </header>
      <div className="canvasBody">
        <ReactFlow
          nodes={flowNodes}
          edges={flowEdges}
          nodeTypes={{ agentNode: AgentNodeView }}
          fitView
          onNodeClick={(_, node) => setSelectedNodeId(node.id)}
        >
          <Background />
        </ReactFlow>
        {selectedNode && <NodePopover node={selectedNode} />}
      </div>
    </section>
  );
}

function AgentNodeView({ data }: { data: { node: AgentNode } }) {
  const node = data.node;
  return (
    <div className={`flowNode flowNode-${node.nodeType} flowNode-${node.status}`}>
      <Handle type="target" position={Position.Top} />
      <span className="nodeTag">{node.nodeType}</span>
      <strong>{node.displayName}</strong>
      <p>{node.summary}</p>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
```

- [x] **Step 4: Wire canvas into `App`**

Modify `src/app/App.tsx` to import and use the graph after send:

```tsx
import { useState } from "react";
import { ChatPanel } from "../features/chat/ChatPanel";
import { NodeCanvas } from "../features/canvas/NodeCanvas";
import { createDocumentGraph } from "../features/canvas/nodeLayout";
import type { ChatAttachment, ChatMessage, NodeGraph } from "../shared/types";
import "./app.css";

const initialMessages: ChatMessage[] = [
  {
    messageId: "m1",
    role: "user",
    content: "帮我把这个文档处理一下。",
    attachments: [],
    createdAt: new Date().toISOString(),
  },
  {
    messageId: "m2",
    role: "assistant",
    content: "请把需要处理的文档添加到聊天框里，并告诉我希望处理成什么结果。",
    attachments: [],
    createdAt: new Date().toISOString(),
  },
];

export function App() {
  const [messages, setMessages] = useState(initialMessages);
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [graph, setGraph] = useState<NodeGraph | null>(null);

  function handleAddFile() {
    setAttachments([
      {
        attachmentId: "sample-doc",
        name: "项目资料.docx",
        path: "workspace/inputs/project.docx",
        sizeBytes: 1024,
        mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      },
    ]);
  }

  function handleSend() {
    if (!draft.trim() && attachments.length === 0) return;
    setMessages((current) => [
      ...current,
      {
        messageId: `m-${current.length + 1}`,
        role: "user",
        content: draft.trim() || "已添加文件。",
        attachments,
        createdAt: new Date().toISOString(),
      },
      {
        messageId: `m-${current.length + 2}`,
        role: "assistant",
        content: "已收到。我会根据文件和要求生成右侧的工具节点流程。",
        attachments: [],
        createdAt: new Date().toISOString(),
      },
    ]);
    setGraph(createDocumentGraph());
    setDraft("");
    setAttachments([]);
  }

  return (
    <main className="appShell">
      <ChatPanel
        messages={messages}
        pendingAttachments={attachments}
        draft={draft}
        onDraftChange={setDraft}
        onSend={handleSend}
        onAddFile={handleAddFile}
      />
      <NodeCanvas graph={graph} />
    </main>
  );
}
```

- [x] **Step 5: Add canvas CSS**

Append to `src/app/app.css`:

```css
.canvasPanel {
  min-width: 0;
  border: 1px solid #c7d8d5;
  border-radius: 8px;
  background: #ffffff;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.canvasBody {
  position: relative;
  flex: 1;
  min-height: 0;
}

.emptyCanvas {
  flex: 1;
  display: grid;
  place-items: center;
  color: #526a66;
  background: #f8fffd;
}

.flowNode {
  width: 210px;
  min-height: 88px;
  padding: 18px 12px 12px;
  border: 1px solid #9db8e8;
  border-radius: 8px;
  background: #eff6ff;
  color: #123631;
}

.flowNode p {
  margin: 6px 0 0;
  color: #526a66;
  font-size: 12px;
}

.flowNode-temporary_placeholder {
  border-style: dashed;
  border-color: #fb923c;
  background: #fff7ed;
}

.flowNode-output {
  border-color: #86efac;
  background: #f0fdf4;
}

.nodeTag {
  display: inline-block;
  margin-bottom: 7px;
  padding: 3px 7px;
  border-radius: 999px;
  background: #ffffff;
  color: #115e59;
  font-size: 11px;
  font-weight: 760;
  border: 1px solid #a7f3d0;
}

.nodePopover {
  position: absolute;
  right: 16px;
  top: 64px;
  z-index: 10;
  width: 280px;
  border: 1px solid #9db8e8;
  border-radius: 8px;
  background: #ffffff;
  overflow: hidden;
}

.nodePopover header {
  padding: 12px 14px;
  border-bottom: 1px solid #c7d8d5;
}

.nodePopover header p,
.nodePopover dd {
  color: #526a66;
  font-size: 13px;
}

.nodePopover dl {
  margin: 0;
  padding: 12px 14px;
}

.nodePopover dt {
  color: #0d9488;
  font-size: 12px;
  font-weight: 760;
}

.nodePopover dd {
  margin: 3px 0 10px;
}

.detailsButton {
  width: calc(100% - 28px);
  margin: 0 14px 14px;
  border: 0;
  border-radius: 6px;
  padding: 8px 10px;
  background: #ccfbf1;
  color: #115e59;
  font-weight: 760;
}
```

- [x] **Step 6: Run frontend typecheck**

Run:

```powershell
npm run frontend:lint
```

Expected: TypeScript exits with code 0.

- [x] **Step 7: Verify manually**

Run:

```powershell
npm run dev
```

Expected: after adding a file and sending a message, the right panel displays a top-to-bottom node graph. Clicking a node shows a lightweight popover.

- [x] **Step 8: Commit or checkpoint**

```powershell
git add src/features/canvas src/app src/shared
git commit -m "feat: add top-down node canvas"
```

If Git is unavailable, record the changed file list.

## Task 6: Implement Tool Manifest Loading

**Files:**
- Create: `tool-packages/document/manifest.json`
- Create: `src-tauri/src/tools.rs`
- Modify: `src-tauri/src/lib.rs`
- Test: `src-tauri/tests/tool_manifest_tests.rs`

- [x] **Step 1: Add document tool manifest**

Create `tool-packages/document/manifest.json`:

```json
{
  "tool_id": "document.read_write",
  "name": "文档处理工具包",
  "description": "读取 txt、md、docx，并导出 md 或 docx 文件。",
  "version": "0.1.0",
  "source_type": "python_plugin",
  "license": "internal",
  "entrypoint": "python/tools/document_tool.py",
  "input_schema": {
    "type": "object",
    "required": ["operation", "input_paths", "output_path"],
    "properties": {
      "operation": { "type": "string", "enum": ["read", "write_markdown", "write_docx"] },
      "input_paths": { "type": "array", "items": { "type": "string" } },
      "output_path": { "type": "string" },
      "content": { "type": "string" }
    }
  },
  "output_schema": {
    "type": "object",
    "required": ["artifacts"],
    "properties": {
      "artifacts": { "type": "array", "items": { "type": "string" } },
      "text": { "type": "string" }
    }
  },
  "permissions": ["read_project_files", "write_project_outputs", "run_python_plugin"],
  "examples": [
    {
      "title": "读取多个文档",
      "input": {
        "operation": "read",
        "input_paths": ["inputs/需求.md", "inputs/说明.txt"],
        "output_path": "outputs/读取结果.md"
      }
    },
    {
      "title": "写入 Markdown",
      "input": {
        "operation": "write_markdown",
        "input_paths": [],
        "output_path": "outputs/总结.md",
        "content": "这是自动生成的项目总结。"
      }
    },
    {
      "title": "导出 Word 文档",
      "input": {
        "operation": "write_docx",
        "input_paths": [],
        "output_path": "outputs/报告.docx",
        "content": "这是自动生成的报告内容。"
      }
    }
  ],
  "error_codes": ["unsupported_format", "read_failed", "write_failed"],
  "timeout_policy": { "seconds": 60 },
  "artifact_policy": { "writes_to": "outputs" }
}
```

- [x] **Step 2: Write failing manifest tests**

Create `src-tauri/tests/tool_manifest_tests.rs`:

```rust
#[path = "../src/tools.rs"]
mod tools;

#[test]
fn loads_document_manifest() {
    let manifest = tools::ToolManifest::from_path("../tool-packages/document/manifest.json").unwrap();
    assert_eq!(manifest.tool_id, "document.read_write");
    assert!(manifest.permissions.contains(&"read_project_files".to_string()));
}
```

- [x] **Step 3: Run test to verify failure**

Run:

```powershell
cd src-tauri
& "$env:USERPROFILE\.cargo\bin\cargo.exe" test --test tool_manifest_tests
```

Expected: FAIL because `tools.rs` does not exist or `ToolManifest` is undefined.
If this Windows environment fails earlier with `link.exe` or Windows SDK library errors, record that as an environment blocker.

- [x] **Step 4: Implement manifest loading**

Create `src-tauri/src/tools.rs`:

```rust
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs;
use std::path::Path;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ToolManifest {
    pub tool_id: String,
    pub name: String,
    pub description: String,
    pub version: String,
    pub source_type: String,
    pub license: String,
    pub entrypoint: String,
    pub input_schema: Value,
    pub output_schema: Value,
    pub permissions: Vec<String>,
    pub examples: Vec<Value>,
    pub error_codes: Vec<String>,
    pub timeout_policy: Value,
    pub artifact_policy: Value,
}

impl ToolManifest {
    pub fn from_path(path: impl AsRef<Path>) -> Result<Self, String> {
        let text = fs::read_to_string(path.as_ref())
            .map_err(|err| format!("failed to read manifest {}: {err}", path.as_ref().display()))?;
        serde_json::from_str(&text).map_err(|err| format!("invalid manifest json: {err}"))
    }
}
```

- [x] **Step 5: Wire Rust module**

Modify `src-tauri/src/lib.rs`:

```rust
pub mod domain;
pub mod tools;
pub mod workspace;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

- [x] **Step 6: Run manifest tests**

Run:

```powershell
cd src-tauri
& "$env:USERPROFILE\.cargo\bin\cargo.exe" test --test tool_manifest_tests
```

Expected: test passes.
If the command fails because `link.exe` or Windows SDK libraries are unavailable, record that as an environment blocker and continue only after code review confirms the source changes.

Observed on 2026-05-09: `cargo test --test tool_manifest_tests` fails before compiling project tests because the Windows MSVC linker `link.exe` is unavailable in this machine. `cargo fmt --check`, `npm run frontend:lint`, and UTF-8/manifest JSON checks pass.

- [x] **Step 7: Commit or checkpoint**

```powershell
git add tool-packages/document/manifest.json src-tauri/src/tools.rs src-tauri/src/lib.rs src-tauri/tests/tool_manifest_tests.rs
git commit -m "feat: load document tool manifest"
```

If Git is unavailable, record the changed file list.
Observed on 2026-05-09: workspace is not a Git repository, so changed files are recorded in the task summary instead of a commit.

## Task 7: Implement the Python Document Tool

**Files:**
- Create: `python/pyproject.toml`
- Create: `python/tools/document_tool.py`
- Test: `python/tests/test_document_tool.py`

- [x] **Step 1: Create Python project config**

Create `python/pyproject.toml`:

```toml
[project]
name = "alita-sidecar"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
  "fastapi",
  "langgraph",
  "pydantic",
  "python-docx",
  "uvicorn"
]

[project.optional-dependencies]
test = ["pytest"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [x] **Step 2: Create document tool implementation**

Create `python/tools/document_tool.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docx import Document


SUPPORTED_INPUTS = {".txt", ".md", ".docx"}


@dataclass(frozen=True)
class DocumentReadResult:
    text: str
    sources: list[str]


def read_documents(paths: list[str]) -> DocumentReadResult:
    chunks: list[str] = []
    sources: list[str] = []

    for raw_path in paths:
        path = Path(raw_path)
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_INPUTS:
            raise ValueError(f"unsupported_format:{suffix}")
        if suffix in {".txt", ".md"}:
            text = path.read_text(encoding="utf-8")
        else:
            doc = Document(path)
            text = "\n".join(paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip())
        chunks.append(text)
        sources.append(str(path))

    return DocumentReadResult(text="\n\n".join(chunks), sources=sources)


def write_markdown(content: str, output_path: str) -> str:
    path = Path(output_path)
    if path.suffix.lower() != ".md":
        raise ValueError("write_failed:markdown_output_must_end_with_md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


def write_docx(content: str, output_path: str) -> str:
    path = Path(output_path)
    if path.suffix.lower() != ".docx":
        raise ValueError("write_failed:docx_output_must_end_with_docx")
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    for line in content.splitlines():
        if line.strip():
            doc.add_paragraph(line)
    doc.save(path)
    return str(path)
```

- [x] **Step 3: Write tests**

Create `python/tests/test_document_tool.py`:

```python
from pathlib import Path

from docx import Document

from tools.document_tool import read_documents, write_docx, write_markdown


def test_reads_txt_and_markdown(tmp_path: Path):
    txt = tmp_path / "a.txt"
    md = tmp_path / "b.md"
    txt.write_text("hello", encoding="utf-8")
    md.write_text("# title", encoding="utf-8")

    result = read_documents([str(txt), str(md)])

    assert "hello" in result.text
    assert "# title" in result.text
    assert result.sources == [str(txt), str(md)]


def test_reads_docx(tmp_path: Path):
    path = tmp_path / "input.docx"
    doc = Document()
    doc.add_paragraph("docx content")
    doc.save(path)

    result = read_documents([str(path)])

    assert "docx content" in result.text


def test_writes_markdown_and_docx(tmp_path: Path):
    md_path = write_markdown("report", str(tmp_path / "report.md"))
    docx_path = write_docx("report", str(tmp_path / "report.docx"))

    assert Path(md_path).read_text(encoding="utf-8") == "report"
    assert Path(docx_path).exists()
```

- [x] **Step 4: Install Python dependencies**

Run:

```powershell
cd python
python -m pip install -e ".[test]"
```

Expected: dependencies install successfully.

- [x] **Step 5: Run Python tests**

Run:

```powershell
cd python
pytest
```

Expected: all tests pass.
Observed on 2026-05-09: `python -m pytest` passes with 5 document tool tests.

- [x] **Step 6: Commit or checkpoint**

```powershell
git add python/pyproject.toml python/tools/document_tool.py python/tests/test_document_tool.py
git commit -m "feat: add document processing tool"
```

If Git is unavailable, record the changed file list.
Observed on 2026-05-09: workspace is not a Git repository, so changed files are recorded in the task summary instead of a commit.

## Task 8: Implement Python LangGraph Sidecar Skeleton

**Files:**
- Create: `python/agent_service/schemas.py`
- Create: `python/agent_service/graph.py`
- Create: `python/agent_service/app.py`
- Test: `python/tests/test_graph.py`

- [x] **Step 1: Create sidecar schemas**

Create `python/agent_service/schemas.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, Field


class Attachment(BaseModel):
    attachment_id: str
    name: str
    path: str
    size_bytes: int
    mime_type: str


class UserMessage(BaseModel):
    task_id: str
    content: str
    attachments: list[Attachment] = Field(default_factory=list)


class AgentEvent(BaseModel):
    type: str
    payload: dict
```

- [x] **Step 2: Create graph logic with missing-input handling**

Create `python/agent_service/graph.py`:

```python
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from agent_service.schemas import AgentEvent, UserMessage


class AgentState(TypedDict):
    message: UserMessage
    events: list[AgentEvent]


def check_required_inputs(state: AgentState) -> AgentState:
    message = state["message"]
    if not message.attachments:
        return {
            **state,
            "events": [
                AgentEvent(
                    type="input.required",
                    payload={
                        "prompt": "请把需要处理的文档添加到聊天框里。",
                        "missing": ["document_file"],
                    },
                )
            ],
        }
    return state


def plan_node_graph(state: AgentState) -> AgentState:
    if state["events"]:
        return state
    return {
        **state,
        "events": [
            AgentEvent(
                type="node_graph.created",
                payload={
                    "graph_id": f"{state['message'].task_id}-graph",
                    "nodes": [
                        {"node_id": "input", "display_name": "文档输入", "status": "completed"},
                        {"node_id": "parse", "display_name": "文档解析", "status": "waiting"},
                        {"node_id": "organize", "display_name": "内容整理", "status": "waiting"},
                        {"node_id": "export", "display_name": "导出文件", "status": "waiting"},
                    ],
                    "edges": [
                        {"id": "input-parse", "source": "input", "target": "parse"},
                        {"id": "parse-organize", "source": "parse", "target": "organize"},
                        {"id": "organize-export", "source": "organize", "target": "export"},
                    ],
                },
            )
        ],
    }


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("check_required_inputs", check_required_inputs)
    graph.add_node("plan_node_graph", plan_node_graph)
    graph.set_entry_point("check_required_inputs")
    graph.add_edge("check_required_inputs", "plan_node_graph")
    graph.add_edge("plan_node_graph", END)
    return graph.compile()


def run_agent(message: UserMessage) -> list[AgentEvent]:
    app = build_graph()
    result = app.invoke({"message": message, "events": []})
    return result["events"]
```

- [x] **Step 3: Create FastAPI app**

Create `python/agent_service/app.py`:

```python
from __future__ import annotations

from fastapi import FastAPI

from agent_service.graph import run_agent
from agent_service.schemas import AgentEvent, UserMessage

app = FastAPI(title="Alita Agent Sidecar")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/agent/message", response_model=list[AgentEvent])
def agent_message(message: UserMessage) -> list[AgentEvent]:
    return run_agent(message)
```

- [x] **Step 4: Write graph tests**

Create `python/tests/test_graph.py`:

```python
from agent_service.graph import run_agent
from agent_service.schemas import Attachment, UserMessage


def test_missing_attachment_requests_input():
    events = run_agent(UserMessage(task_id="task-1", content="帮我处理这个文档"))

    assert events[0].type == "input.required"
    assert events[0].payload["missing"] == ["document_file"]


def test_attachment_generates_node_graph():
    events = run_agent(
        UserMessage(
            task_id="task-2",
            content="整理成报告",
            attachments=[
                Attachment(
                    attachment_id="a1",
                    name="input.docx",
                    path="workspace/inputs/input.docx",
                    size_bytes=100,
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            ],
        )
    )

    assert events[0].type == "node_graph.created"
    assert events[0].payload["nodes"][0]["display_name"] == "文档输入"
```

- [x] **Step 5: Run tests**

Run:

```powershell
cd python
pytest tests/test_graph.py
```

Expected: both graph tests pass.
Observed on 2026-05-09: `python -m pytest` passes with 7 total Python tests. The sidecar emits `node_graph.created.payload.graph` in the shared frontend `NodeGraph` camelCase shape.

- [x] **Step 6: Run sidecar health endpoint**

Run:

```powershell
cd python
python -m uvicorn agent_service.app:app --port 8765
```

Expected: visiting `http://127.0.0.1:8765/health` returns `{"status":"ok"}`.
Observed on 2026-05-09: temporary uvicorn process returned `{"status":"ok"}` from `http://127.0.0.1:8765/health`, then was stopped.

- [x] **Step 7: Commit or checkpoint**

```powershell
git add python/agent_service python/tests/test_graph.py
git commit -m "feat: add langgraph sidecar skeleton"
```

If Git is unavailable, record the changed file list.
Observed on 2026-05-09: workspace is not a Git repository, so changed files are recorded in the task summary instead of a commit.

## Task 9: Add Rust Agent Client

**Files:**
- Create: `src-tauri/src/agent_client.rs`
- Modify: `src-tauri/src/lib.rs`
- Test: `src-tauri/tests/agent_client_tests.rs`

- [x] **Step 1: Write an agent client unit test for request shape**

Create `src-tauri/tests/agent_client_tests.rs`:

```rust
#[path = "../src/agent_client.rs"]
mod agent_client;

use agent_client::{AgentMessageRequest, AgentAttachment};

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
            mime_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document".to_string(),
        }],
    };

    let json = serde_json::to_value(request).unwrap();
    assert_eq!(json["task_id"], "task-1");
    assert_eq!(json["attachments"][0]["name"], "input.docx");
}
```

- [x] **Step 2: Add dependencies**

Add to `src-tauri/Cargo.toml`:

```toml
[dependencies]
reqwest = { version = "0.12", features = ["json"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
```

Keep existing Tauri dependencies from the scaffold.

- [x] **Step 3: Implement the client**

Create `src-tauri/src/agent_client.rs`:

```rust
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AgentAttachment {
    pub attachment_id: String,
    pub name: String,
    pub path: String,
    pub size_bytes: u64,
    pub mime_type: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AgentMessageRequest {
    pub task_id: String,
    pub content: String,
    pub attachments: Vec<AgentAttachment>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AgentEvent {
    pub r#type: String,
    pub payload: serde_json::Value,
}

#[derive(Debug, Clone)]
pub struct AgentClient {
    base_url: String,
    http: reqwest::Client,
}

impl AgentClient {
    pub fn new(base_url: impl Into<String>) -> Self {
        Self {
            base_url: base_url.into(),
            http: reqwest::Client::new(),
        }
    }

    pub async fn send_message(&self, request: &AgentMessageRequest) -> Result<Vec<AgentEvent>, String> {
        let url = format!("{}/agent/message", self.base_url.trim_end_matches('/'));
        let response = self
            .http
            .post(url)
            .json(request)
            .send()
            .await
            .map_err(|err| format!("agent sidecar request failed: {err}"))?;

        if !response.status().is_success() {
            return Err(format!("agent sidecar returned {}", response.status()));
        }

        response
            .json::<Vec<AgentEvent>>()
            .await
            .map_err(|err| format!("invalid agent response: {err}"))
    }
}
```

- [x] **Step 4: Wire module**

Modify `src-tauri/src/lib.rs`:

```rust
pub mod agent_client;
pub mod domain;
pub mod tools;
pub mod workspace;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

- [x] **Step 5: Run Rust tests**

Run:

```powershell
cd src-tauri
& "$env:USERPROFILE\.cargo\bin\cargo.exe" test --test agent_client_tests
```

Expected: request serialization test passes.
Observed on 2026-05-09: `cargo fmt --check` passes and `Cargo.lock` resolves the new dependency. `cargo test --test agent_client_tests` fails before compiling project tests because the Windows MSVC linker `link.exe` is unavailable in this machine.

- [x] **Step 6: Commit or checkpoint**

```powershell
git add src-tauri/src/agent_client.rs src-tauri/src/lib.rs src-tauri/tests/agent_client_tests.rs src-tauri/Cargo.toml
git commit -m "feat: add rust agent sidecar client"
```

If Git is unavailable, record the changed file list.
Observed on 2026-05-09: workspace is not a Git repository, so changed files are recorded in the task summary instead of a commit.

## Task 10: Add Tauri Commands for Chat Submission

**Files:**
- Create: `src-tauri/src/commands.rs`
- Modify: `src-tauri/src/lib.rs`
- Modify: `src/features/task/useTaskEvents.ts`
- Modify: `src/app/App.tsx`

- [x] **Step 1: Add Rust command module**

Create `src-tauri/src/commands.rs`:

```rust
use crate::agent_client::{AgentAttachment, AgentClient, AgentMessageRequest};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SubmitMessagePayload {
    pub task_id: String,
    pub content: String,
    pub attachments: Vec<AgentAttachment>,
}

#[tauri::command]
pub async fn submit_user_message(payload: SubmitMessagePayload) -> Result<serde_json::Value, String> {
    let client = AgentClient::new("http://127.0.0.1:8765");
    let request = AgentMessageRequest {
        task_id: payload.task_id,
        content: payload.content,
        attachments: payload.attachments,
    };
    let events = client.send_message(&request).await?;
    serde_json::to_value(events).map_err(|err| format!("failed to serialize agent events: {err}"))
}
```

- [x] **Step 2: Register command**

Modify `src-tauri/src/lib.rs`:

```rust
pub mod agent_client;
pub mod commands;
pub mod domain;
pub mod tools;
pub mod workspace;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![commands::submit_user_message])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

- [x] **Step 3: Create frontend task bridge**

Create `src/features/task/useTaskEvents.ts`:

```ts
import { invoke } from "@tauri-apps/api/core";
import type { BackendEvent } from "../../shared/events";
import type { ChatAttachment } from "../../shared/types";

interface SubmitMessagePayload {
  task_id: string;
  content: string;
  attachments: ChatAttachment[];
}

export async function submitUserMessage(payload: SubmitMessagePayload): Promise<BackendEvent[]> {
  return invoke<BackendEvent[]>("submit_user_message", { payload });
}
```

- [x] **Step 4: Update `App` to call backend**

In `src/app/App.tsx`, replace the body of `handleSend` with:

```tsx
async function handleSend() {
  if (!draft.trim() && attachments.length === 0) return;
  const userMessage: ChatMessage = {
    messageId: `m-${messages.length + 1}`,
    role: "user",
    content: draft.trim() || "已添加文件。",
    attachments,
    createdAt: new Date().toISOString(),
  };
  setMessages((current) => [...current, userMessage]);

  try {
    const events = await submitUserMessage({
      task_id: "task-dev",
      content: userMessage.content,
      attachments,
    });
    for (const event of events) {
      if (event.type === "input.required") {
        setMessages((current) => [
          ...current,
          {
            messageId: `m-${current.length + 1}`,
            role: "assistant",
            content: event.payload.prompt,
            attachments: [],
            createdAt: new Date().toISOString(),
          },
        ]);
      }
      if (event.type === "node_graph.created") {
        setGraph(createDocumentGraph());
      }
    }
  } catch (error) {
    setMessages((current) => [
      ...current,
      {
        messageId: `m-${current.length + 1}`,
        role: "assistant",
        content: `后台 Agent 暂不可用：${String(error)}`,
        attachments: [],
        createdAt: new Date().toISOString(),
      },
    ]);
  }

  setDraft("");
  setAttachments([]);
}
```

Add this import:

```tsx
import { submitUserMessage } from "../features/task/useTaskEvents";
```

- [x] **Step 5: Run both services**

Terminal 1:

```powershell
cd python
python -m uvicorn agent_service.app:app --port 8765
```

Terminal 2:

```powershell
npm run dev
```

Expected: sending a message with no file produces an assistant prompt requesting a document; sending with the sample attachment produces a node graph.
Observed on 2026-05-09: browser verification at `http://127.0.0.1:1420/` passed with sidecar on `http://127.0.0.1:8765`; no-file send produced the document prompt, and sample attachment send produced the right-side document node graph.

- [x] **Step 6: Commit or checkpoint**

```powershell
git add src-tauri/src/commands.rs src-tauri/src/lib.rs src/features/task src/app/App.tsx
git commit -m "feat: connect chat submission to agent sidecar"
```

If Git is unavailable, record the changed file list.
Observed on 2026-05-09: workspace is not a Git repository, so changed files are recorded in the task summary instead of a commit.

## Task 11: Add Model Runtime Boundary

**Files:**
- Create: `src-tauri/src/model.rs`
- Modify: `src-tauri/src/lib.rs`
- Test: `src-tauri/tests/model_tests.rs`

- [x] **Step 1: Write model capability tests**

Create `src-tauri/tests/model_tests.rs`:

```rust
#[path = "../src/model.rs"]
mod model;

use model::{ModelCapabilities, RuntimeBackend};

#[test]
fn default_local_capabilities_are_text_and_embedding_ready() {
    let capabilities = ModelCapabilities::local_llama_cpp();

    assert_eq!(capabilities.runtime_backend, RuntimeBackend::LlamaCpp);
    assert!(capabilities.supports_chat);
    assert!(capabilities.supports_embeddings);
    assert!(!capabilities.supports_images);
    assert!(capabilities.local_only);
}
```

- [x] **Step 2: Implement model boundary**

Create `src-tauri/src/model.rs`:

```rust
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeBackend {
    LlamaCpp,
    Ollama,
    LocalAi,
    OnnxRuntimeGenAi,
    ExternalApi,
    Mock,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ModelCapabilities {
    pub supports_chat: bool,
    pub supports_tools: bool,
    pub supports_embeddings: bool,
    pub supports_images: bool,
    pub supports_audio: bool,
    pub context_window: u32,
    pub max_output_tokens: u32,
    pub runtime_backend: RuntimeBackend,
    pub local_only: bool,
}

impl ModelCapabilities {
    pub fn local_llama_cpp() -> Self {
        Self {
            supports_chat: true,
            supports_tools: true,
            supports_embeddings: true,
            supports_images: false,
            supports_audio: false,
            context_window: 4096,
            max_output_tokens: 1024,
            runtime_backend: RuntimeBackend::LlamaCpp,
            local_only: true,
        }
    }
}
```

- [x] **Step 3: Wire module**

Modify `src-tauri/src/lib.rs`:

```rust
pub mod agent_client;
pub mod commands;
pub mod domain;
pub mod model;
pub mod tools;
pub mod workspace;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![commands::submit_user_message])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

- [x] **Step 4: Run model tests**

Run:

```powershell
cd src-tauri
& "$env:USERPROFILE\.cargo\bin\cargo.exe" test --test model_tests
```

Expected: model capability test passes.
Observed on 2026-05-09: `cargo fmt --check`, `npm run frontend:lint`, and `python -m pytest` pass. `cargo test --test model_tests` fails before compiling project tests because the Windows MSVC linker `link.exe` is unavailable in this machine.

- [x] **Step 5: Commit or checkpoint**

```powershell
git add src-tauri/src/model.rs src-tauri/src/lib.rs src-tauri/tests/model_tests.rs
git commit -m "feat: add local model runtime boundary"
```

If Git is unavailable, record the changed file list.
Observed on 2026-05-09: workspace is not a Git repository, so changed files are recorded in the task summary instead of a commit.

## Task 12: Add End-to-End MVP Verification Script

**Files:**
- Create: `scripts/verify-mvp.ps1`
- Create: `docs/mvp-verification.md`

- [x] **Step 1: Create verification script**

Create `scripts/verify-mvp.ps1`:

```powershell
$ErrorActionPreference = "Stop"

Write-Host "Running frontend typecheck..."
npm run frontend:lint

Write-Host "Running Rust tests..."
Push-Location src-tauri
cargo test
Pop-Location

Write-Host "Running Python tests..."
Push-Location python
pytest
Pop-Location

Write-Host "MVP verification passed."
```

- [x] **Step 2: Create manual verification guide**

Create `docs/mvp-verification.md`:

```markdown
# MVP Verification

1. Start the Python sidecar:

   ```powershell
   cd python
   python -m uvicorn agent_service.app:app --port 8765
   ```

2. Start the Tauri app:

   ```powershell
   npm run dev
   ```

3. In the app, send `帮我把这个文档整理成一份中文报告` with no attachment.

   Expected: AI asks the user to upload a document.

4. Click `添加文件`, then send `输出为 docx，并保留要点结构`.

   Expected: right panel shows a top-to-bottom node graph.

5. Click a node.

   Expected: a lightweight node popover appears with purpose, function, input, and output summary.

6. Run automated checks:

   ```powershell
   .\scripts\verify-mvp.ps1
   ```

   Expected: frontend typecheck, Rust tests, and Python tests pass.
```

- [x] **Step 3: Run verification script**

Run:

```powershell
.\scripts\verify-mvp.ps1
```

Expected: all checks pass.
Observed on 2026-05-09: script runs frontend typecheck, Python tests, and Rust formatting successfully. Rust tests are blocked because this machine does not have the Windows MSVC linker `link.exe`.

- [x] **Step 4: Commit or checkpoint**

```powershell
git add scripts/verify-mvp.ps1 docs/mvp-verification.md
git commit -m "test: add mvp verification workflow"
```

If Git is unavailable, record the changed file list.
Observed on 2026-05-09: workspace is not a Git repository, so changed files are recorded in the task summary instead of a commit.

## Self-Review Notes

- Spec coverage: tasks cover the Tauri shell, React UI, sidecar, node graph, document tool package, model runtime boundary, workspace safety, event bridge, and verification.
- MVP exclusions preserved: PDF/xlsx/pptx, real temporary script execution, external API, full multimodal support, and tool marketplace are not implemented.
- Type consistency: `AgentNode`, `NodeGraph`, event names, node statuses, and tool manifest fields match the design document.
- Implementation order: every task leaves the project in a testable state.


