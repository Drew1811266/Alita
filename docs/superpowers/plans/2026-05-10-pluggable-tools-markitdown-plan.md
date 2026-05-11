# 插件化工具体系与 MarkItDown 接入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立第一版可插拔工具包协议，并把 Microsoft MarkItDown 作为独立外部工具节点接入 Alita。

**Architecture:** Rust 侧继续负责读取 `tool-packages/*/manifest.json` 并向首选项暴露工具元数据；Python sidecar 新增工具执行协议和 MarkItDown 适配器；LangGraph 生成的文档流程把“解析文档”升级为“文档转 Markdown”固定工具节点。第一版不做独立进程沙箱，但所有输入输出必须经过路径、网络、插件和格式限制。

**Tech Stack:** Tauri 2、React、TypeScript、Rust、FastAPI sidecar、Python、LangGraph、MarkItDown、PyInstaller、Vitest、pytest、cargo test。

**Repo Note:** 当前 `D:\Software Project\Alita` 不是 git 仓库，`git status` 会失败。因此本计划中的“提交”步骤在当前环境改为“记录检查点并运行对应验证命令”。如果后续项目初始化为 git 仓库，再恢复正常 commit。

---

## File Structure

### Create

- `D:\Software Project\Alita\tool-packages\markitdown\manifest.json`  
  MarkItDown 工具包公开契约。

- `D:\Software Project\Alita\tool-packages\markitdown\README.md`  
  说明该工具包的来源、第一版限制和权限。

- `D:\Software Project\Alita\python\tools\markitdown_tool.py`  
  MarkItDown 本地文件转 Markdown 适配器。

- `D:\Software Project\Alita\python\agent_service\tool_execution.py`  
  Python sidecar 内部统一工具调用协议。

- `D:\Software Project\Alita\python\tests\test_markitdown_tool.py`  
  MarkItDown 适配器单元测试。

- `D:\Software Project\Alita\python\tests\test_tool_execution.py`  
  工具执行协议单元测试。

### Modify

- `D:\Software Project\Alita\src-tauri\src\tools.rs`  
  扩展 manifest schema，读取工具运行时、能力、依赖、安全策略和节点模板。

- `D:\Software Project\Alita\src-tauri\src\preferences.rs`  
  扩展 `ToolSummary`，让首选项展示更多工具元数据。

- `D:\Software Project\Alita\src-tauri\tests\tool_manifest_tests.rs`  
  覆盖新 manifest 字段和 MarkItDown manifest 加载。

- `D:\Software Project\Alita\src-tauri\tests\preferences_tests.rs`  
  覆盖首选项工具摘要中的 MarkItDown 信息。

- `D:\Software Project\Alita\python\agent_service\graph.py`  
  生成 `document.markitdown_convert` 工具节点。

- `D:\Software Project\Alita\python\agent_service\execution.py`  
  让文档解析节点通过 `ToolExecutor` 调用 MarkItDown。

- `D:\Software Project\Alita\python\tests\test_graph.py`  
  更新节点图断言。

- `D:\Software Project\Alita\python\tests\test_execution.py`  
  增加执行器调用工具协议的测试，保留现有端到端文档流测试。

- `D:\Software Project\Alita\python\pyproject.toml`  
  加入 MarkItDown 依赖。

- `D:\Software Project\Alita\scripts\build-sidecar.ps1`  
  让 PyInstaller 收集 MarkItDown。

- `D:\Software Project\Alita\src\shared\types.ts`  
  扩展 `ToolSummary` 前端类型。

- `D:\Software Project\Alita\src\features\preferences\PreferencesDialog.tsx`  
  展示工具来源、运行时、许可证、权限和能力。

- `D:\Software Project\Alita\src\features\preferences\PreferencesDialog.test.tsx`  
  覆盖 MarkItDown 工具展示。

---

## Task 1: 扩展 Rust 工具 Manifest 协议

**Files:**

- Modify: `D:\Software Project\Alita\src-tauri\src\tools.rs`
- Modify: `D:\Software Project\Alita\src-tauri\tests\tool_manifest_tests.rs`

- [ ] **Step 1: 写失败测试，确认新字段能被读取**

在 `src-tauri\tests\tool_manifest_tests.rs` 增加：

```rust
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

    let loaded = ToolManifest::from_path(&manifest_path).expect("manifest should load");

    assert_eq!(loaded.runtime.as_deref(), Some("python_sidecar"));
    assert_eq!(loaded.capabilities, vec!["document.convert.markdown"]);
    assert_eq!(loaded.package.as_ref().unwrap().name, "markitdown");
    assert_eq!(loaded.operations[0].name, "convert_local_file");
    assert_eq!(loaded.security_policy["network"], false);
    assert_eq!(loaded.node_templates[0]["displayName"], "文档转 Markdown");
}
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
cargo test --test tool_manifest_tests loads_extended_manifest_fields
```

Expected: FAIL，错误应指向 `ToolManifest` 没有 `runtime`、`capabilities`、`package`、`operations` 等字段。

- [ ] **Step 3: 实现 manifest 扩展字段**

在 `src-tauri\src\tools.rs` 中增加结构：

```rust
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ToolPackageInfo {
    pub name: String,
    pub source: String,
    #[serde(default)]
    pub upstream_url: Option<String>,
    #[serde(default)]
    pub locked_version: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ToolOperation {
    pub name: String,
    pub description: String,
}
```

扩展 `ToolManifest`：

```rust
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
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
    #[serde(default)]
    pub runtime: Option<String>,
    #[serde(default)]
    pub package: Option<ToolPackageInfo>,
    #[serde(default)]
    pub capabilities: Vec<String>,
    #[serde(default)]
    pub operations: Vec<ToolOperation>,
    #[serde(default)]
    pub dependency_policy: Value,
    #[serde(default)]
    pub security_policy: Value,
    #[serde(default)]
    pub node_templates: Vec<Value>,
}
```

在 `validate()` 末尾追加：

```rust
        if self
            .capabilities
            .iter()
            .any(|capability| capability.trim().is_empty())
        {
            return Err("capabilities must not contain empty values".to_string());
        }

        if self
            .operations
            .iter()
            .any(|operation| operation.name.trim().is_empty())
        {
            return Err("operations must not contain empty names".to_string());
        }

        validate_optional_object("dependency_policy", &self.dependency_policy)?;
        validate_optional_object("security_policy", &self.security_policy)?;
```

增加 helper：

```rust
fn validate_optional_object(field_name: &str, value: &Value) -> Result<(), String> {
    if value.is_null() || value.is_object() {
        return Ok(());
    }

    Err(format!("{field_name} must be a JSON object when present"))
}
```

- [ ] **Step 4: 运行 manifest 测试**

Run:

```powershell
cargo test --test tool_manifest_tests
```

Expected: PASS。

- [ ] **Step 5: 检查点**

记录：Rust manifest 协议已支持外部工具元数据。当前不是 git 仓库，不执行 commit。

---

## Task 2: 新增 MarkItDown 工具包 Manifest

**Files:**

- Create: `D:\Software Project\Alita\tool-packages\markitdown\manifest.json`
- Create: `D:\Software Project\Alita\tool-packages\markitdown\README.md`
- Modify: `D:\Software Project\Alita\src-tauri\tests\tool_manifest_tests.rs`

- [ ] **Step 1: 写失败测试，确认 MarkItDown manifest 会被加载**

在 `src-tauri\tests\tool_manifest_tests.rs` 增加：

```rust
#[test]
fn loads_markitdown_manifest() {
    let manifest = ToolManifest::from_path("../tool-packages/markitdown/manifest.json")
        .expect("markitdown manifest should load");

    assert_eq!(manifest.tool_id, "document.markitdown_convert");
    assert_eq!(manifest.source_type, "external_python_package");
    assert_eq!(manifest.runtime.as_deref(), Some("python_sidecar"));
    assert_eq!(manifest.package.as_ref().unwrap().name, "markitdown");
    assert!(manifest
        .capabilities
        .contains(&"document.convert.markdown".to_string()));
    assert!(manifest.permissions.contains(&"read_project_files".to_string()));
    assert_eq!(manifest.security_policy["network"], false);
    assert_eq!(manifest.security_policy["plugins"], false);
}
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
cargo test --test tool_manifest_tests loads_markitdown_manifest
```

Expected: FAIL，错误为 manifest 文件不存在。

- [ ] **Step 3: 创建 MarkItDown manifest**

创建 `tool-packages\markitdown\manifest.json`：

```json
{
  "tool_id": "document.markitdown_convert",
  "name": "MarkItDown 文档转 Markdown",
  "description": "把本地文档转换为适合模型读取的 Markdown 文本。",
  "version": "0.1.0",
  "source_type": "external_python_package",
  "license": "MIT",
  "runtime": "python_sidecar",
  "package": {
    "name": "markitdown",
    "source": "github",
    "upstreamUrl": "https://github.com/microsoft/markitdown",
    "lockedVersion": "latest-compatible"
  },
  "entrypoint": "python/tools/markitdown_tool.py",
  "capabilities": ["document.convert.markdown"],
  "operations": [
    {
      "name": "convert_local_file",
      "description": "把单个本地文件转换为 Markdown artifact。"
    }
  ],
  "input_schema": {
    "type": "object",
    "required": ["operation", "input_path", "output_path"],
    "properties": {
      "operation": {
        "type": "string",
        "enum": ["convert_local_file"]
      },
      "input_path": {
        "type": "string",
        "description": "项目内文件或用户明确导入的附件路径。"
      },
      "output_path": {
        "type": "string",
        "description": "写入 artifacts/converted 目录下的 Markdown 路径。"
      }
    }
  },
  "output_schema": {
    "type": "object",
    "required": ["text", "artifacts"],
    "properties": {
      "text": {
        "type": "string",
        "description": "转换后的 Markdown 正文。"
      },
      "artifacts": {
        "type": "array",
        "items": { "type": "string" },
        "description": "生成的 Markdown artifact 路径。"
      },
      "metadata": {
        "type": "object",
        "description": "转换来源、转换器和输出格式。"
      }
    }
  },
  "permissions": [
    "read_project_files",
    "write_project_outputs",
    "run_python_plugin"
  ],
  "examples": [
    {
      "title": "转换 Word 文档",
      "input": {
        "operation": "convert_local_file",
        "input_path": "inputs/report.docx",
        "output_path": "artifacts/converted/report.md"
      }
    },
    {
      "title": "转换 PDF 文档",
      "input": {
        "operation": "convert_local_file",
        "input_path": "inputs/brief.pdf",
        "output_path": "artifacts/converted/brief.md"
      }
    }
  ],
  "error_codes": [
    "unsupported_format",
    "input_not_found",
    "path_outside_project",
    "network_input_forbidden",
    "dependency_missing",
    "conversion_failed",
    "output_write_failed",
    "timeout"
  ],
  "timeout_policy": {
    "seconds": 120
  },
  "artifact_policy": {
    "writes_to": "artifacts/converted"
  },
  "dependency_policy": {
    "python": ["markitdown[pdf,docx,pptx,xlsx]"]
  },
  "security_policy": {
    "network": false,
    "plugins": false,
    "allowedInput": "project_or_attachment_file",
    "allowedOutput": "project_artifacts_converted",
    "maxFileSizeMb": 100
  },
  "node_templates": [
    {
      "nodeType": "fixed_tool",
      "displayName": "文档转 Markdown",
      "inputPorts": [{ "id": "document-input", "label": "文档", "dataType": "document" }],
      "outputPorts": [{ "id": "markdown-output", "label": "Markdown", "dataType": "text" }]
    }
  ]
}
```

- [ ] **Step 4: 创建 README**

创建 `tool-packages\markitdown\README.md`：

```markdown
# MarkItDown 文档转 Markdown 工具

来源：https://github.com/microsoft/markitdown

第一版用途：把用户明确导入的本地文档转换为 Markdown，供 Alita后续模型节点读取。

第一版限制：

- 只处理本地文件。
- 不处理 URL。
- 不启用 MarkItDown 插件。
- 不启用 Azure Document Intelligence、远程 OCR 或音频转写。
- 输出只能写入当前工程的 `artifacts/converted/` 目录。

权限：

- `read_project_files`
- `write_project_outputs`
- `run_python_plugin`
```

- [ ] **Step 5: 运行 manifest 测试**

Run:

```powershell
cargo test --test tool_manifest_tests
```

Expected: PASS。

- [ ] **Step 6: 检查点**

记录：MarkItDown 工具包 manifest 已可被 Rust 读取。

---

## Task 3: 实现 Python MarkItDown 适配器

**Files:**

- Create: `D:\Software Project\Alita\python\tools\markitdown_tool.py`
- Create: `D:\Software Project\Alita\python\tests\test_markitdown_tool.py`

- [ ] **Step 1: 写失败测试，覆盖成功转换**

创建 `python\tests\test_markitdown_tool.py`：

```python
from pathlib import Path

import pytest

from tools import markitdown_tool
from tools.markitdown_tool import convert_local_file


class FakeConversionResult:
    text_content = "# 转换结果\n\n正文"


class FakeMarkItDown:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def convert_local(self, path: str) -> FakeConversionResult:
        self.paths.append(path)
        return FakeConversionResult()


def test_converts_local_file_to_markdown_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "input.docx"
    source.write_bytes(b"docx")
    output = tmp_path / "artifacts" / "converted" / "input.md"
    fake = FakeMarkItDown()
    monkeypatch.setattr(markitdown_tool, "_create_markitdown", lambda: fake)

    result = convert_local_file(
        input_path=str(source),
        output_path=str(output),
        project_path=str(tmp_path / "project.alita"),
        allowed_roots=[str(tmp_path)],
    )

    assert result.text == "# 转换结果\n\n正文"
    assert result.artifacts == [str(output)]
    assert output.read_text(encoding="utf-8") == "# 转换结果\n\n正文"
    assert fake.paths == [str(source.resolve())]
    assert result.metadata["converter"] == "markitdown"
```

- [ ] **Step 2: 写失败测试，覆盖安全边界**

继续在同一文件增加：

```python
def test_rejects_network_inputs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="network_input_forbidden"):
        convert_local_file(
            input_path="https://example.com/file.pdf",
            output_path=str(tmp_path / "out.md"),
            project_path=str(tmp_path / "project.alita"),
            allowed_roots=[str(tmp_path)],
        )


def test_rejects_path_outside_allowed_roots(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    blocked = tmp_path / "blocked"
    allowed.mkdir()
    blocked.mkdir()
    source = blocked / "input.pdf"
    source.write_bytes(b"%PDF")

    with pytest.raises(ValueError, match="path_outside_project"):
        convert_local_file(
            input_path=str(source),
            output_path=str(allowed / "artifacts" / "converted" / "input.md"),
            project_path=str(allowed / "project.alita"),
            allowed_roots=[str(allowed)],
        )


def test_rejects_unsupported_file_suffix(tmp_path: Path) -> None:
    source = tmp_path / "input.exe"
    source.write_bytes(b"binary")

    with pytest.raises(ValueError, match="unsupported_format:.exe"):
        convert_local_file(
            input_path=str(source),
            output_path=str(tmp_path / "out.md"),
            project_path=str(tmp_path / "project.alita"),
            allowed_roots=[str(tmp_path)],
        )


def test_rejects_output_outside_artifacts_converted(tmp_path: Path) -> None:
    source = tmp_path / "input.pdf"
    source.write_bytes(b"%PDF")

    with pytest.raises(ValueError, match="output_write_failed:outside_artifacts_converted"):
        convert_local_file(
            input_path=str(source),
            output_path=str(tmp_path / "outside.md"),
            project_path=str(tmp_path / "project.alita"),
            allowed_roots=[str(tmp_path)],
        )
```

- [ ] **Step 3: 运行测试确认失败**

Run:

```powershell
python -m pytest python\tests\test_markitdown_tool.py -v
```

Expected: FAIL，错误为 `tools.markitdown_tool` 不存在。

- [ ] **Step 4: 实现适配器**

创建 `python\tools\markitdown_tool.py`：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".txt",
    ".md",
    ".html",
    ".htm",
    ".csv",
    ".json",
    ".xml",
}
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class MarkItDownResult:
    text: str
    artifacts: list[str]
    metadata: dict[str, str] = field(default_factory=dict)


def convert_local_file(
    *,
    input_path: str,
    output_path: str,
    project_path: str,
    allowed_roots: list[str],
) -> MarkItDownResult:
    if _is_network_input(input_path):
        raise ValueError("network_input_forbidden")

    source = Path(input_path).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise ValueError(f"input_not_found:{input_path}")

    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"unsupported_format:{suffix}")

    if source.stat().st_size > MAX_FILE_SIZE_BYTES:
        raise ValueError("conversion_failed:file_too_large")

    roots = [Path(root).expanduser().resolve() for root in allowed_roots]
    if not _is_inside_any(source, roots):
        raise ValueError(f"path_outside_project:{source}")

    project_dir = Path(project_path).expanduser().resolve().parent
    artifacts_dir = project_dir / "artifacts" / "converted"
    output = Path(output_path).expanduser().resolve()
    if output.suffix.lower() != ".md":
        raise ValueError("output_write_failed:markdown_output_must_end_with_md")
    if not _is_inside_any(output, [artifacts_dir.resolve()]):
        raise ValueError("output_write_failed:outside_artifacts_converted")

    converter = _create_markitdown()
    try:
        converted = converter.convert_local(str(source))
        text = getattr(converted, "text_content", "")
    except Exception as error:
        raise ValueError(f"conversion_failed:{source.name}") from error

    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        output.write_text(text, encoding="utf-8")
    except OSError as error:
        raise ValueError(f"output_write_failed:{output}") from error

    return MarkItDownResult(
        text=text,
        artifacts=[str(output)],
        metadata={
            "source_path": str(source),
            "converter": "markitdown",
            "output_format": "markdown",
        },
    )


def _create_markitdown():
    try:
        from markitdown import MarkItDown
    except ImportError as error:
        raise ValueError("dependency_missing:markitdown") from error

    return MarkItDown(enable_plugins=False)


def _is_network_input(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https", "ftp", "s3"}:
        return True
    return value.startswith("\\\\")


def _is_inside_any(path: Path, roots: list[Path]) -> bool:
    return any(_is_relative_to(path, root) for root in roots)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
```

- [ ] **Step 5: 运行适配器测试**

Run:

```powershell
python -m pytest python\tests\test_markitdown_tool.py -v
```

Expected: PASS。

- [ ] **Step 6: 检查点**

记录：MarkItDown Python 适配器已通过本地转换与安全边界测试。

---

## Task 4: 增加 Python 工具执行协议

**Files:**

- Create: `D:\Software Project\Alita\python\agent_service\tool_execution.py`
- Create: `D:\Software Project\Alita\python\tests\test_tool_execution.py`

- [ ] **Step 1: 写失败测试，确认工具调用能路由到 MarkItDown**

创建 `python\tests\test_tool_execution.py`：

```python
from pathlib import Path

import pytest

from agent_service import tool_execution
from agent_service.tool_execution import ToolExecutor, ToolInvocation
from tools.markitdown_tool import MarkItDownResult


def test_tool_executor_routes_markitdown_conversion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "input.pdf"
    source.write_bytes(b"%PDF")
    project = tmp_path / "project.alita"
    output = tmp_path / "artifacts" / "converted" / "input.md"
    calls: list[dict] = []

    def fake_convert_local_file(**kwargs):
        calls.append(kwargs)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("# markdown", encoding="utf-8")
        return MarkItDownResult(
            text="# markdown",
            artifacts=[str(output)],
            metadata={"converter": "markitdown"},
        )

    monkeypatch.setattr(
        tool_execution,
        "convert_markitdown_local_file",
        fake_convert_local_file,
    )

    executor = ToolExecutor()
    result = executor.run(
        ToolInvocation(
            tool_id="document.markitdown_convert",
            operation="convert_local_file",
            arguments={
                "input_path": str(source),
                "output_path": str(output),
            },
            project_path=str(project),
            allowed_roots=[str(tmp_path)],
        )
    )

    assert result.values["text"] == "# markdown"
    assert result.artifacts == [str(output)]
    assert calls[0]["input_path"] == str(source)
```

- [ ] **Step 2: 写失败测试，确认未知工具被拒绝**

继续增加：

```python
def test_tool_executor_rejects_unknown_tool(tmp_path: Path) -> None:
    executor = ToolExecutor()

    with pytest.raises(ValueError, match="unsupported_tool:unknown.tool"):
        executor.run(
            ToolInvocation(
                tool_id="unknown.tool",
                operation="run",
                arguments={},
                project_path=str(tmp_path / "project.alita"),
                allowed_roots=[str(tmp_path)],
            )
        )
```

- [ ] **Step 3: 运行测试确认失败**

Run:

```powershell
python -m pytest python\tests\test_tool_execution.py -v
```

Expected: FAIL，错误为 `agent_service.tool_execution` 不存在。

- [ ] **Step 4: 实现工具执行协议**

创建 `python\agent_service\tool_execution.py`：

```python
from __future__ import annotations

from dataclasses import dataclass, field

from tools.markitdown_tool import convert_local_file as convert_markitdown_local_file


@dataclass(frozen=True)
class ToolInvocation:
    tool_id: str
    operation: str
    arguments: dict[str, object]
    project_path: str
    allowed_roots: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ToolResult:
    values: dict[str, str]
    artifacts: list[str]
    metadata: dict[str, str] = field(default_factory=dict)


class ToolExecutor:
    def run(self, invocation: ToolInvocation) -> ToolResult:
        if invocation.tool_id == "document.markitdown_convert":
            return self._run_markitdown(invocation)

        raise ValueError(f"unsupported_tool:{invocation.tool_id}")

    def _run_markitdown(self, invocation: ToolInvocation) -> ToolResult:
        if invocation.operation != "convert_local_file":
            raise ValueError(f"unsupported_operation:{invocation.operation}")

        result = convert_markitdown_local_file(
            input_path=str(invocation.arguments["input_path"]),
            output_path=str(invocation.arguments["output_path"]),
            project_path=invocation.project_path,
            allowed_roots=invocation.allowed_roots,
        )
        return ToolResult(
            values={"text": result.text},
            artifacts=result.artifacts,
            metadata=result.metadata,
        )
```

- [ ] **Step 5: 运行工具执行测试**

Run:

```powershell
python -m pytest python\tests\test_tool_execution.py -v
```

Expected: PASS。

- [ ] **Step 6: 检查点**

记录：Python sidecar 具备第一版统一工具调用入口。

---

## Task 5: 把文档流程节点接入 MarkItDown 工具执行

**Files:**

- Modify: `D:\Software Project\Alita\python\agent_service\graph.py`
- Modify: `D:\Software Project\Alita\python\agent_service\execution.py`
- Modify: `D:\Software Project\Alita\python\tests\test_graph.py`
- Modify: `D:\Software Project\Alita\python\tests\test_execution.py`

- [ ] **Step 1: 更新图生成测试**

在 `python\tests\test_graph.py` 的 `test_attachment_generates_node_graph_for_document_task` 里增加/替换断言：

```python
    parse_node = graph["nodes"][1]
    assert parse_node["nodeId"] == "document-parse"
    assert parse_node["displayName"] == "文档转 Markdown"
    assert parse_node["toolRef"] == "document.markitdown_convert"
    assert parse_node["outputPorts"][0]["label"] == "Markdown"
```

- [ ] **Step 2: 更新执行器测试，确认文档解析节点通过 ToolExecutor**

在 `python\tests\test_execution.py` 增加 fake tool runner：

```python
class FakeToolExecutor:
    def __init__(self) -> None:
        self.calls = []

    def run(self, invocation):
        self.calls.append(invocation)
        return NodeOutput(
            artifacts=[str(Path(invocation.arguments["output_path"]))],
            values={"text": "# Markdown\n\n正文"},
        )
```

增加测试：

```python
def test_document_parse_uses_markitdown_tool_executor(tmp_path: Path) -> None:
    source = tmp_path / "input.pdf"
    source.write_bytes(b"%PDF")
    request = build_document_flow_request(tmp_path, source)
    tool_executor = FakeToolExecutor()

    events = list(
        run_graph_events(
            request,
            model_client=FakeModelClient(),
            tool_executor=tool_executor,
        )
    )

    assert tool_executor.calls
    invocation = tool_executor.calls[0]
    assert invocation.tool_id == "document.markitdown_convert"
    assert invocation.operation == "convert_local_file"
    assert invocation.arguments["input_path"] == str(source)
    assert "artifacts" in str(invocation.arguments["output_path"])
    assert events[-1].type == "task.completed"
```

- [ ] **Step 3: 运行测试确认失败**

Run:

```powershell
python -m pytest python\tests\test_graph.py python\tests\test_execution.py -v
```

Expected: FAIL，图节点仍为旧名称/旧 `toolRef`，`run_graph_events` 还没有 `tool_executor` 参数。

- [ ] **Step 4: 更新 LangGraph 节点定义**

在 `python\agent_service\graph.py` 的 `document-parse` 节点改为：

```python
            _node(
                node_id="document-parse",
                node_type="fixed_tool",
                display_name="文档转 Markdown",
                status="waiting",
                input_ports=[_port("document-input", "文档", "document")],
                output_ports=[_port("markdown-output", "Markdown", "text")],
                dependencies=["document-input"],
                summary="把用户提供的本地文档转换为适合模型读取的 Markdown 正文。",
                position={"x": 260, "y": 190},
                tool_ref="document.markitdown_convert",
            ),
```

- [ ] **Step 5: 更新执行器依赖注入**

在 `python\agent_service\execution.py` 增加 import：

```python
from agent_service.tool_execution import ToolExecutor, ToolInvocation
```

修改 `DocumentFlowExecutor.__init__`：

```python
    def __init__(
        self,
        request: RunGraphRequest,
        *,
        model_client: ModelClient | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        self.request = request
        self.model_client = model_client or LlamaCppModelClient()
        self.tool_executor = tool_executor or ToolExecutor()
        self.project_dir = Path(request.project_path).parent
        self.artifact_dir = self.project_dir / "artifacts"
```

把 `document-parse` 分支替换为：

```python
        if node_id == "document-parse":
            texts: list[str] = []
            artifacts: list[str] = []
            for attachment in self.request.attachments:
                output_path = (
                    self.project_dir
                    / "artifacts"
                    / "converted"
                    / f"{Path(attachment.path).stem}.md"
                )
                result = self.tool_executor.run(
                    ToolInvocation(
                        tool_id="document.markitdown_convert",
                        operation="convert_local_file",
                        arguments={
                            "input_path": attachment.path,
                            "output_path": str(output_path),
                        },
                        project_path=self.request.project_path,
                        allowed_roots=self._allowed_roots(),
                    )
                )
                texts.append(result.values.get("text", ""))
                artifacts.extend(result.artifacts)

            return NodeOutput(
                artifacts=artifacts,
                values={"text": "\n\n".join(texts)},
            )
```

在类里增加：

```python
    def _allowed_roots(self) -> list[str]:
        roots = {str(self.project_dir)}
        roots.update(str(Path(attachment.path).parent) for attachment in self.request.attachments)
        return sorted(roots)
```

修改 `run_graph_events` 签名：

```python
def run_graph_events(
    request: RunGraphRequest,
    *,
    executor: NodeExecutor | None = None,
    model_client: ModelClient | None = None,
    tool_executor: ToolExecutor | None = None,
    registry: RunRegistry | None = None,
) -> Iterator[AgentEvent]:
```

修改 node executor 创建：

```python
    node_executor = executor or DocumentFlowExecutor(
        request,
        model_client=model_client,
        tool_executor=tool_executor,
    )
```

- [ ] **Step 6: 处理 FakeToolExecutor 返回类型**

如果 fake runner 返回 `ToolResult` 而不是 `NodeOutput`，保持执行器分支读取 `result.values` 和 `result.artifacts`。测试 fake 可以返回任意具备这两个属性的对象；优先在测试里 import `ToolResult`，让类型更清晰：

```python
from agent_service.tool_execution import ToolResult
```

并让 fake 返回：

```python
return ToolResult(
    values={"text": "# Markdown\n\n正文"},
    artifacts=[str(Path(invocation.arguments["output_path"]))],
    metadata={"converter": "fake"},
)
```

- [ ] **Step 7: 运行 Python 测试**

Run:

```powershell
python -m pytest python\tests\test_graph.py python\tests\test_execution.py python\tests\test_tool_execution.py python\tests\test_markitdown_tool.py -v
```

Expected: PASS。

- [ ] **Step 8: 检查点**

记录：生成的文档流程和执行流程已经通过 MarkItDown 工具协议连接。

---

## Task 6: 在首选项中展示外部工具元数据

**Files:**

- Modify: `D:\Software Project\Alita\src-tauri\src\preferences.rs`
- Modify: `D:\Software Project\Alita\src-tauri\tests\preferences_tests.rs`
- Modify: `D:\Software Project\Alita\src\shared\types.ts`
- Modify: `D:\Software Project\Alita\src\features\preferences\PreferencesDialog.tsx`
- Modify: `D:\Software Project\Alita\src\features\preferences\PreferencesDialog.test.tsx`

- [ ] **Step 1: 写 Rust 失败测试，确认 MarkItDown 摘要包含运行时和能力**

在 `src-tauri\tests\preferences_tests.rs` 增加：

```rust
#[test]
fn tool_summary_includes_markitdown_metadata() {
    let summaries = summarize_tool_manifests("../tool-packages", &AppPreferences::default());

    let markitdown = summaries
        .iter()
        .find(|tool| tool.tool_id == "document.markitdown_convert")
        .expect("markitdown tool should be listed");

    assert_eq!(markitdown.runtime.as_deref(), Some("python_sidecar"));
    assert_eq!(markitdown.package_name.as_deref(), Some("markitdown"));
    assert!(markitdown
        .capabilities
        .contains(&"document.convert.markdown".to_string()));
}
```

- [ ] **Step 2: 扩展 Rust `ToolSummary`**

在 `src-tauri\src\preferences.rs` 的 `ToolSummary` 增加：

```rust
    pub runtime: Option<String>,
    pub package_name: Option<String>,
    pub package_source: Option<String>,
    pub upstream_url: Option<String>,
    pub capabilities: Vec<String>,
```

在有效 manifest 分支填充：

```rust
                runtime: manifest.runtime,
                package_name: manifest.package.as_ref().map(|package| package.name.clone()),
                package_source: manifest.package.as_ref().map(|package| package.source.clone()),
                upstream_url: manifest
                    .package
                    .as_ref()
                    .and_then(|package| package.upstream_url.clone()),
                capabilities: manifest.capabilities,
```

在无效 manifest 分支填充：

```rust
                runtime: None,
                package_name: None,
                package_source: None,
                upstream_url: None,
                capabilities: Vec::new(),
```

- [ ] **Step 3: 运行 Rust 首选项测试**

Run:

```powershell
cargo test --test preferences_tests
```

Expected: PASS。

- [ ] **Step 4: 扩展前端类型**

在 `src\shared\types.ts` 的 `ToolSummary` 增加：

```ts
  runtime?: string;
  packageName?: string;
  packageSource?: string;
  upstreamUrl?: string;
  capabilities: string[];
```

- [ ] **Step 5: 写前端展示测试**

在 `src\features\preferences\PreferencesDialog.test.tsx` 的 `tools` 中追加 MarkItDown：

```ts
    {
      toolId: "document.markitdown_convert",
      name: "MarkItDown 文档转 Markdown",
      description: "把本地文档转换为适合模型读取的 Markdown 文本。",
      version: "0.1.0",
      sourceType: "external_python_package",
      license: "MIT",
      permissions: ["read_project_files", "write_project_outputs"],
      enabled: true,
      valid: true,
      runtime: "python_sidecar",
      packageName: "markitdown",
      packageSource: "github",
      upstreamUrl: "https://github.com/microsoft/markitdown",
      capabilities: ["document.convert.markdown"],
    },
```

在断言里增加：

```ts
    expect(markup).toContain("MarkItDown 文档转 Markdown");
    expect(markup).toContain("external_python_package");
    expect(markup).toContain("python_sidecar");
    expect(markup).toContain("MIT");
    expect(markup).toContain("document.convert.markdown");
```

- [ ] **Step 6: 更新首选项工具项 UI**

在 `PreferencesDialog.tsx` 的 `ToolItem` 里增加显示：

```tsx
        <span>运行时 {tool.runtime || "未知"}</span>
        <span>许可证 {tool.license || "未知"}</span>
        {tool.packageName ? <span>包 {tool.packageName}</span> : null}
        {tool.capabilities.length > 0 ? (
          <span>能力 {tool.capabilities.join("、")}</span>
        ) : null}
        {tool.permissions.length > 0 ? (
          <span>权限 {tool.permissions.join("、")}</span>
        ) : null}
        {tool.error ? <span>{tool.error}</span> : null}
```

- [ ] **Step 7: 运行前端测试**

Run:

```powershell
npm run frontend:test -- PreferencesDialog
```

Expected: PASS。

- [ ] **Step 8: 检查点**

记录：首选项可以展示 MarkItDown 外部工具元数据。

---

## Task 7: 加入 MarkItDown 依赖并验证打包

**Files:**

- Modify: `D:\Software Project\Alita\python\pyproject.toml`
- Modify: `D:\Software Project\Alita\scripts\build-sidecar.ps1`

- [ ] **Step 1: 更新 Python 依赖**

在 `python\pyproject.toml` 的 dependencies 加入：

```toml
  "markitdown[pdf,docx,pptx,xlsx]",
```

完整依赖段应保持类似：

```toml
dependencies = [
  "fastapi",
  "langgraph",
  "markitdown[pdf,docx,pptx,xlsx]",
  "pydantic",
  "python-docx",
  "uvicorn"
]
```

- [ ] **Step 2: 安装 editable 依赖**

Run:

```powershell
Push-Location python
python -m pip install -e ".[test,package]"
Pop-Location
```

Expected: pip 安装成功，`markitdown` 可以被 import。

- [ ] **Step 3: 快速确认 MarkItDown import**

Run:

```powershell
python -c "from markitdown import MarkItDown; print(MarkItDown)"
```

Expected: 输出包含 `MarkItDown` 类。

- [ ] **Step 4: 更新 sidecar 打包脚本**

在 `scripts\build-sidecar.ps1` 的 PyInstaller 参数中加入：

```powershell
        --collect-all "markitdown" `
```

如果后续 PyInstaller 报某个格式依赖缺失，再追加对应依赖的 `--collect-all`。第一轮不要提前扩大到无关包。

- [ ] **Step 5: 运行全量验证**

Run:

```powershell
cargo test
npm run frontend:lint
npm run frontend:test
python -m pytest python\tests -v
.\scripts\build-sidecar.ps1
npm run build
```

Expected: 全部 PASS，sidecar 和 Tauri release 构建成功。

- [ ] **Step 6: 桌面软件手动验证**

如果已有旧进程运行，先关闭：

```powershell
Get-Process | Where-Object { $_.ProcessName -in @('alita','alita-agent-sidecar','llama-server') } | Stop-Process -Force
```

启动 release 桌面软件：

```powershell
$exe = Join-Path (Get-Location) 'src-tauri\target\release\alita.exe'
Start-Process -FilePath $exe
```

手动验证：

- 打开首选项。
- 确认工具列表出现 `MarkItDown 文档转 Markdown`。
- 创建或打开一个工程。
- 在聊天区添加一个 DOCX 或 PDF。
- 发送“帮我整理一下这篇文档中的内容。”
- 右侧节点图中出现“文档转 Markdown”。
- 点击“运行流程”。
- 节点执行完成，并在聊天区生成 artifact 路径。
- 打开 artifact，确认是 Markdown 文件。

- [ ] **Step 7: 检查点**

记录：MarkItDown 工具已完成打包级验证，可以进入下一轮功能增强。

---

## Self-Review

- Spec coverage: 本计划覆盖 manifest 协议、MarkItDown 工具包、Python 适配器、工具执行协议、节点流程接入、首选项展示、打包验证和安全边界。
- Scope: 计划只实现第一版本地文件转 Markdown，不包含工具市场、远程 URL、插件生态、Azure OCR、音频转写、独立沙箱。
- Risk control: 路径校验、网络输入拒绝、插件禁用、输出目录限制、大小限制和标准错误码都在测试中覆盖。
- Type consistency: Rust `ToolManifest`、`ToolSummary`、TypeScript `ToolSummary`、Python `ToolInvocation` / `ToolResult` 名称保持一致。
- Verification: 每个任务都有单项验证，最后有全量 `cargo test`、`npm run frontend:lint`、`npm run frontend:test`、`python -m pytest`、`build-sidecar`、`npm run build`。



