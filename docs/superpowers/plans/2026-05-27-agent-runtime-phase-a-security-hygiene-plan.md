# Agent Runtime Phase A Security Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Alita's current Agent workbench safer and cleaner before changing the Agent runtime: sidecar auth fails closed, CORS/CSP are scoped, development bypass is explicit, Python package version matches the desktop app, and corrupted Chinese route keywords are removed.

**Architecture:** This phase is a behavior-preserving hardening pass around the existing FastAPI sidecar, Tauri shell, development scripts, and route keyword tables. Public Agent event schemas, graph node schemas, tool schemas, and frontend task flows stay unchanged. Packaged desktop runs continue to use the Tauri-generated sidecar token; unauthenticated sidecar access exists only when an explicit development environment flag is set.

**Tech Stack:** Python 3.10+, FastAPI, Pytest, React/Vitest, Tauri 2, Rust integration tests, PowerShell development scripts.

---

## Scope

In scope:

- Fail closed for all protected sidecar endpoints when `ALITA_SIDECAR_TOKEN` is missing.
- Add one explicit local development bypass flag: `ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV=1`.
- Keep `/health` unauthenticated so Tauri and scripts can detect whether port `8765` is already listening.
- Restrict sidecar CORS origins to known local frontend and Tauri origins.
- Add a non-null Tauri CSP that only permits local Agent/model services and local asset/media sources required by the app.
- Align `python/pyproject.toml` version with `package.json`, `src-tauri/tauri.conf.json`, and `src-tauri/Cargo.toml`.
- Remove mojibake Chinese document keywords from `python/agent_service/intent.py` and lock the cleanup with tests.
- Update development scripts and docs so local desktop development remains straightforward.

Out of scope:

- ReAct loop, PlannerV2 generalization, tool gateway migration, sandbox execution, research synthesis changes, memory, and frontend state decomposition.
- Any new public API endpoint, frontend UI redesign, or graph schema migration.
- Enforcing auth on `/health`.

## File Structure

### Create

- `scripts/dev-sidecar.ps1`
  - Starts the Python sidecar for browser/Vite development with `ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV=1` set only for that process.
- `python/tests/test_package_metadata.py`
  - Verifies Python sidecar, npm package, Tauri config, and Cargo package versions stay aligned.
- `src-tauri/tests/tauri_config_tests.rs`
  - Verifies `tauri.conf.json` has a scoped non-null CSP.

### Modify

- `python/agent_service/app.py`
  - Move sidecar security constants above app creation.
  - Replace wildcard CORS with explicit local origins.
  - Require either a valid sidecar token or explicit development bypass.
- `python/tests/test_app.py`
  - Add an autouse test fixture for explicit development bypass.
  - Add fail-closed auth tests.
  - Add CORS allow/deny tests.
- `scripts/dev-desktop.ps1`
  - Set the explicit unauthenticated development bypass for the sidecar process it starts.
- `package.json`
  - Route `npm run sidecar:dev` through `scripts/dev-sidecar.ps1`.
- `docs/mvp-verification.md`
  - Replace the raw sidecar command with `npm run sidecar:dev` and explain the bypass flag.
- `docs/windows-desktop-runbook.md`
  - Add a security note for development sidecar auth.
- `python/pyproject.toml`
  - Update version from `0.27.0` to `0.28.0`.
- `python/agent_service/intent.py`
  - Remove corrupted Chinese keywords and duplicate entries in document action/reference keyword tables.
- `python/tests/test_intent.py`
  - Add tests that protect the keyword tables from mojibake regressions.
- `src-tauri/tauri.conf.json`
  - Replace `"csp": null` with a scoped CSP string.

### Read-Only Regression Targets

- `src/features/task/useTaskEvents.ts`
- `src/features/task/useTaskEvents.test.ts`
- `src-tauri/src/sidecar.rs`
- `src-tauri/src/agent_client.rs`
- `src-tauri/tests/sidecar_tests.rs`
- `python/tests/test_agent_routing_integration.py`
- `python/tests/test_tool_gateway.py`
- `python/tests/test_model_tool_adapter.py`
- `python/tests/test_planner_v2.py`

---

## Task 0: Baseline Verification

**Files:**
- Read: `python/agent_service/app.py`
- Read: `python/tests/test_app.py`
- Read: `python/agent_service/intent.py`
- Read: `python/tests/test_intent.py`
- Read: `scripts/dev-desktop.ps1`
- Read: `package.json`
- Read: `src-tauri/tauri.conf.json`

- [ ] **Step 1: Confirm the worktree state**

Run:

```powershell
git status --short --branch
```

Expected:

```text
## main...origin/main [ahead 2]
?? docs/superpowers/plans/2026-05-27-agent-runtime-development-guide.md
?? docs/superpowers/plans/2026-05-27-agent-runtime-optimization-plan.md
?? docs/superpowers/plans/2026-05-27-agent-runtime-phase-a-security-hygiene-plan.md
```

If other user changes are present, keep them. Do not reset or checkout files.

- [ ] **Step 2: Run focused Python baseline**

Run:

```powershell
python -m pytest -q python\tests\test_app.py python\tests\test_intent.py
```

Expected:

```text
... passed
```

- [ ] **Step 3: Run focused frontend baseline**

Run:

```powershell
npm run frontend:test -- src/features/task/useTaskEvents.test.ts src/app/backendEvents.test.ts
```

Expected:

```text
Test Files  2 passed
```

- [ ] **Step 4: Run focused Rust baseline**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml --test sidecar_tests
```

Expected:

```text
test result: ok
```

If Rust is blocked by missing `link.exe`, run:

```powershell
npm run check:desktop-prereqs
```

Expected: the script names the missing Windows desktop build prerequisite. Record the blocker in the final implementation note.

---

## Task 1: Add Sidecar Auth And CORS Failing Tests

**Files:**
- Modify: `python/tests/test_app.py`
- Test: `python/tests/test_app.py`

- [ ] **Step 1: Add `pytest` import and an explicit development bypass fixture**

At the top of `python/tests/test_app.py`, change the imports to:

```python
from fastapi.testclient import TestClient
import pytest

from agent_service.app import app
from agent_service.schemas import ScriptReviewState
from agent_service.script_review import script_review_fingerprint
```

Add this fixture below the imports:

```python
@pytest.fixture(autouse=True)
def allow_unauthenticated_dev_sidecar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALITA_SIDECAR_TOKEN", raising=False)
    monkeypatch.setenv("ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV", "1")
```

This keeps existing tests readable while making every unauthenticated request opt in through the new development flag.

- [ ] **Step 2: Add fail-closed auth tests**

Append these tests before `test_agent_endpoints_require_sidecar_token_when_configured`:

```python
def test_agent_endpoints_reject_requests_when_token_missing_and_dev_bypass_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALITA_SIDECAR_TOKEN", raising=False)
    monkeypatch.delenv("ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV", raising=False)
    client = TestClient(app)

    response = client.post(
        "/agent/message",
        json={"task_id": "task-auth-missing", "content": "hello", "attachments": []},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "sidecar token is not configured"


def test_agent_endpoints_allow_explicit_unauthenticated_dev_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALITA_SIDECAR_TOKEN", raising=False)
    monkeypatch.setenv("ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV", "1")
    client = TestClient(app)

    response = client.post(
        "/agent/message",
        json={"task_id": "task-dev-bypass", "content": "hello", "attachments": []},
    )

    assert response.status_code == 200
```

- [ ] **Step 3: Add CORS allow/deny tests**

Append these tests after the auth tests:

```python
def test_cors_allows_known_local_frontend_origin() -> None:
    client = TestClient(app)

    response = client.options(
        "/agent/message",
        headers={
            "Origin": "http://127.0.0.1:1420",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-alita-sidecar-token",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:1420"


def test_cors_does_not_allow_unknown_origin() -> None:
    client = TestClient(app)

    response = client.options(
        "/agent/message",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-alita-sidecar-token",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
```

- [ ] **Step 4: Run the new tests and verify they fail**

Run:

```powershell
python -m pytest -q python\tests\test_app.py
```

Expected:

```text
FAILED python/tests/test_app.py::test_agent_endpoints_reject_requests_when_token_missing_and_dev_bypass_disabled
FAILED python/tests/test_app.py::test_cors_allows_known_local_frontend_origin
```

The auth test fails because the current sidecar silently allows missing tokens. The CORS test fails because the current middleware returns `*` instead of the explicit local origin.

---

## Task 2: Implement Fail-Closed Sidecar Auth And Scoped CORS

**Files:**
- Modify: `python/agent_service/app.py`
- Test: `python/tests/test_app.py`

- [ ] **Step 1: Move sidecar constants above app creation**

In `python/agent_service/app.py`, place these constants above `app = FastAPI(...)`:

```python
SIDECAR_TOKEN_ENV = "ALITA_SIDECAR_TOKEN"
SIDECAR_DEV_BYPASS_ENV = "ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV"
SIDECAR_TOKEN_HEADER = "X-Alita-Sidecar-Token"
ALLOWED_CORS_ORIGINS = [
    "http://127.0.0.1:1420",
    "http://localhost:1420",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://tauri.localhost",
    "tauri://localhost",
]
```

Remove the old duplicate `SIDECAR_TOKEN_ENV` and `SIDECAR_TOKEN_HEADER` declarations below the middleware.

- [ ] **Step 2: Replace wildcard CORS middleware**

Replace the current middleware block with:

```python
app = FastAPI(title="Alita Agent Sidecar")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_CORS_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", SIDECAR_TOKEN_HEADER],
)
```

- [ ] **Step 3: Add a strict environment flag parser**

Add this helper above `require_sidecar_token`:

```python
def _env_flag_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}
```

- [ ] **Step 4: Replace the auth dependency**

Replace `require_sidecar_token` with:

```python
def require_sidecar_token(
    sidecar_token: str | None = Header(default=None, alias=SIDECAR_TOKEN_HEADER),
) -> None:
    expected_token = os.getenv(SIDECAR_TOKEN_ENV)
    if not expected_token:
        if _env_flag_enabled(SIDECAR_DEV_BYPASS_ENV):
            return
        raise HTTPException(status_code=401, detail="sidecar token is not configured")

    if sidecar_token != expected_token:
        raise HTTPException(status_code=401, detail="invalid sidecar token")
```

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m pytest -q python\tests\test_app.py
```

Expected:

```text
... passed
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add python/agent_service/app.py python/tests/test_app.py
git commit -m "fix: tighten sidecar auth and cors defaults"
```

Expected: one commit containing only the sidecar auth/CORS code and tests.

---

## Task 3: Make Development Sidecar Bypass Explicit

**Files:**
- Create: `scripts/dev-sidecar.ps1`
- Modify: `scripts/dev-desktop.ps1`
- Modify: `package.json`
- Modify: `docs/mvp-verification.md`
- Modify: `docs/windows-desktop-runbook.md`

- [ ] **Step 1: Create `scripts/dev-sidecar.ps1`**

Create the file with this content:

```powershell
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$previousBypass = $env:ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV
$env:ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV = "1"

Push-Location (Join-Path $repoRoot "python")
try {
    python -m uvicorn agent_service.app:app --host 127.0.0.1 --port 8765
}
finally {
    if ($null -eq $previousBypass) {
        Remove-Item Env:\ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV -ErrorAction SilentlyContinue
    }
    else {
        $env:ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV = $previousBypass
    }
    Pop-Location
}
```

- [ ] **Step 2: Update `package.json`**

Change the `sidecar:dev` script to:

```json
"sidecar:dev": "powershell -ExecutionPolicy Bypass -File scripts/dev-sidecar.ps1"
```

- [ ] **Step 3: Update `scripts/dev-desktop.ps1` sidecar launch**

Inside the block that starts the Python sidecar, wrap `Start-Process` with explicit bypass inheritance:

```powershell
        $previousSidecarBypass = $env:ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV
        $env:ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV = "1"
        try {
            $sidecarProcess = Start-Process `
                -FilePath "python" `
                -ArgumentList @("-m", "uvicorn", "agent_service.app:app", "--host", "127.0.0.1", "--port", "$sidecarPort") `
                -WorkingDirectory (Join-Path $repoRoot "python") `
                -PassThru `
                -WindowStyle Hidden
        }
        finally {
            if ($null -eq $previousSidecarBypass) {
                Remove-Item Env:\ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV -ErrorAction SilentlyContinue
            }
            else {
                $env:ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV = $previousSidecarBypass
            }
        }
```

Keep `$sidecarStartedHere = $true` after this block, exactly where it already is.

- [ ] **Step 4: Update `docs/mvp-verification.md` startup instructions**

Replace the raw sidecar startup block under `## 启动服务` with:

```markdown
1. 启动 Python Agent sidecar：

   ```powershell
   npm run sidecar:dev
   ```

   这个脚本只在本地开发进程中设置 `ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV=1`。打包后的桌面程序仍然通过 Tauri 生成的 `ALITA_SIDECAR_TOKEN` 访问 sidecar。
```

- [ ] **Step 5: Update `docs/windows-desktop-runbook.md` development note**

After the `npm run desktop:dev` explanation, add:

```markdown
安全说明：开发脚本启动的 Python sidecar 会显式设置 `ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV=1`，用于兼容浏览器/Vite 开发调试。生产打包版本不会设置这个绕过开关，而是由 Tauri 为 sidecar 注入 `ALITA_SIDECAR_TOKEN`。
```

- [ ] **Step 6: Verify package script shape**

Run:

```powershell
node -e "const p=require('./package.json'); if(!p.scripts['sidecar:dev'].includes('scripts/dev-sidecar.ps1')) process.exit(1); console.log(p.scripts['sidecar:dev'])"
```

Expected:

```text
powershell -ExecutionPolicy Bypass -File scripts/dev-sidecar.ps1
```

- [ ] **Step 7: Run focused sidecar tests again**

Run:

```powershell
python -m pytest -q python\tests\test_app.py
```

Expected:

```text
... passed
```

- [ ] **Step 8: Commit**

Run:

```powershell
git add scripts/dev-sidecar.ps1 scripts/dev-desktop.ps1 package.json docs/mvp-verification.md docs/windows-desktop-runbook.md
git commit -m "chore: make sidecar dev bypass explicit"
```

Expected: one commit containing only development script and documentation updates.

---

## Task 4: Align Release Versions

**Files:**
- Create: `python/tests/test_package_metadata.py`
- Modify: `python/pyproject.toml`

- [ ] **Step 1: Add a version alignment test**

Create `python/tests/test_package_metadata.py` with:

```python
from __future__ import annotations

import json
from pathlib import Path
import re


VERSION_PATTERN = re.compile(r'^version = "([^"]+)"$', re.MULTILINE)


def test_python_sidecar_version_matches_desktop_versions() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    package_version = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))[
        "version"
    ]
    tauri_version = json.loads(
        (repo_root / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    )["version"]
    cargo_version = _toml_version(repo_root / "src-tauri" / "Cargo.toml")
    sidecar_version = _toml_version(repo_root / "python" / "pyproject.toml")

    assert sidecar_version == package_version
    assert sidecar_version == tauri_version
    assert sidecar_version == cargo_version


def _toml_version(path: Path) -> str:
    match = VERSION_PATTERN.search(path.read_text(encoding="utf-8"))
    assert match is not None, f"{path} must contain a version field"
    return match.group(1)
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```powershell
python -m pytest -q python\tests\test_package_metadata.py
```

Expected:

```text
FAILED python/tests/test_package_metadata.py::test_python_sidecar_version_matches_desktop_versions
```

The failure should show `0.27.0` from `python/pyproject.toml` compared with `0.28.0`.

- [ ] **Step 3: Update the Python sidecar version**

In `python/pyproject.toml`, change:

```toml
version = "0.27.0"
```

to:

```toml
version = "0.28.0"
```

- [ ] **Step 4: Run the version test**

Run:

```powershell
python -m pytest -q python\tests\test_package_metadata.py
```

Expected:

```text
1 passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/pyproject.toml python/tests/test_package_metadata.py
git commit -m "chore: align sidecar package version"
```

Expected: one commit containing only version metadata and its regression test.

---

## Task 5: Remove Mojibake Document Routing Keywords

**Files:**
- Modify: `python/tests/test_intent.py`
- Modify: `python/agent_service/intent.py`

- [ ] **Step 1: Import the module for private keyword table checks**

In `python/tests/test_intent.py`, add this import near the existing imports:

```python
from agent_service import intent
```

- [ ] **Step 2: Add mojibake protection tests**

Append these tests near the existing document routing tests:

```python
def test_document_keyword_tables_do_not_contain_mojibake_tokens() -> None:
    keyword_dump = "\n".join(
        [*intent._DOCUMENT_ACTIONS, *intent._DOCUMENT_REFERENCES]
    )

    for marker in ["澶", "鏁", "鎬", "鎽", "鎻", "鍒", "鏀", "缈", "闄", "璧", "鍥", "闊", "瑙", "琛"]:
        assert marker not in keyword_dump


def test_chinese_document_request_without_attachment_requires_document_file() -> None:
    decision = classify_route(UserMessage(task_id="cn-doc-missing", content="请总结这个文档"))

    assert decision.intent.kind == IntentKind.NEED_INPUT
    assert decision.missing_inputs == ["document_file"]


def test_chinese_document_request_with_attachment_routes_to_task() -> None:
    decision = classify_route(
        UserMessage(
            task_id="cn-doc-task",
            content="请整理附件并导出报告",
            attachments=[
                Attachment(
                    attachment_id="doc-1",
                    name="notes.docx",
                    path=r"C:\Users\Drew\Desktop\notes.docx",
                    size_bytes=128,
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            ],
        )
    )

    assert decision.intent.kind == IntentKind.TASK
    assert decision.missing_inputs == []
```

- [ ] **Step 3: Run the test and verify the mojibake check fails**

Run:

```powershell
python -m pytest -q python\tests\test_intent.py::test_document_keyword_tables_do_not_contain_mojibake_tokens
```

Expected:

```text
FAILED python/tests/test_intent.py::test_document_keyword_tables_do_not_contain_mojibake_tokens
```

- [ ] **Step 4: Replace document keyword tables**

In `python/agent_service/intent.py`, replace `_DOCUMENT_ACTIONS` and `_DOCUMENT_REFERENCES` with:

```python
_DOCUMENT_ACTIONS = [
    "summarize",
    "summary",
    "organize",
    "extract",
    "process",
    "convert",
    "translate",
    "rewrite",
    "analyze",
    "generate",
    "export",
    "处理",
    "整理",
    "总结",
    "摘要",
    "提取",
    "分析",
    "改写",
    "翻译",
    "生成",
    "导出",
    "转换",
]

_DOCUMENT_REFERENCES = [
    "document",
    "file",
    "attachment",
    "attached",
    "material",
    "report",
    "image",
    "audio",
    "video",
    "spreadsheet",
    "pdf",
    "doc",
    "docx",
    "ppt",
    "pptx",
    "xls",
    "xlsx",
    "文档",
    "文件",
    "附件",
    "资料",
    "报告",
    "图片",
    "图像",
    "音频",
    "视频",
    "表格",
]
```

- [ ] **Step 5: Run intent tests**

Run:

```powershell
python -m pytest -q python\tests\test_intent.py
```

Expected:

```text
... passed
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add python/agent_service/intent.py python/tests/test_intent.py
git commit -m "fix: clean document routing keywords"
```

Expected: one commit containing only intent keyword cleanup and tests.

---

## Task 6: Add A Scoped Tauri CSP

**Files:**
- Create: `src-tauri/tests/tauri_config_tests.rs`
- Modify: `src-tauri/tauri.conf.json`

- [ ] **Step 1: Add a Tauri config security test**

Create `src-tauri/tests/tauri_config_tests.rs` with:

```rust
use std::fs;

use serde_json::Value;

#[test]
fn tauri_csp_is_set_and_scoped_to_local_services() {
    let manifest_dir = env!("CARGO_MANIFEST_DIR");
    let config_path = format!("{manifest_dir}/tauri.conf.json");
    let raw_config = fs::read_to_string(config_path).unwrap();
    let config: Value = serde_json::from_str(&raw_config).unwrap();

    let csp = config["app"]["security"]["csp"]
        .as_str()
        .expect("tauri csp must be a non-null string");

    assert!(csp.contains("default-src 'self'"));
    assert!(csp.contains("connect-src 'self' http://127.0.0.1:8765 http://localhost:8765 http://127.0.0.1:8766 http://localhost:8766 ws://127.0.0.1:1420 ws://localhost:1420"));
    assert!(csp.contains("img-src 'self' asset: http://asset.localhost data: blob:"));
    assert!(csp.contains("media-src 'self' asset: http://asset.localhost data: blob:"));
    assert!(!csp.contains("default-src *"));
    assert!(!csp.contains("connect-src *"));
}
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml --test tauri_config_tests
```

Expected:

```text
FAILED tauri_csp_is_set_and_scoped_to_local_services
```

The failure should state that the CSP is not a string because the current config uses `null`.

- [ ] **Step 3: Set the CSP in `src-tauri/tauri.conf.json`**

Replace:

```json
"csp": null
```

with:

```json
"csp": "default-src 'self'; connect-src 'self' http://127.0.0.1:8765 http://localhost:8765 http://127.0.0.1:8766 http://localhost:8766 ws://127.0.0.1:1420 ws://localhost:1420; img-src 'self' asset: http://asset.localhost data: blob:; media-src 'self' asset: http://asset.localhost data: blob:; font-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'"
```

Rationale for each source:

- `127.0.0.1:8765` and `localhost:8765`: Python Agent sidecar.
- `127.0.0.1:8766` and `localhost:8766`: local llama.cpp model runtime.
- `ws://127.0.0.1:1420` and `ws://localhost:1420`: Vite/Tauri dev server websocket.
- `asset:` and `http://asset.localhost`: Tauri local asset protocol used by file previews.
- `data:` and `blob:` for image/media previews generated from local artifacts.
- `'unsafe-inline'` only for styles because the current frontend and third-party viewers use inline style injection.

- [ ] **Step 4: Run the Tauri config test**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml --test tauri_config_tests
```

Expected:

```text
test result: ok
```

- [ ] **Step 5: Run existing sidecar Rust tests**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml --test sidecar_tests
```

Expected:

```text
test result: ok
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add src-tauri/tauri.conf.json src-tauri/tests/tauri_config_tests.rs
git commit -m "fix: scope tauri content security policy"
```

Expected: one commit containing only Tauri CSP config and test.

---

## Task 7: Full Regression And Manual Smoke Checks

**Files:**
- Read: `scripts/verify-mvp.ps1`
- Read: `docs/mvp-verification.md`
- Read: `docs/windows-desktop-runbook.md`

- [ ] **Step 1: Run focused Python regression**

Run:

```powershell
python -m pytest -q python\tests\test_app.py python\tests\test_intent.py python\tests\test_package_metadata.py python\tests\test_agent_routing_integration.py python\tests\test_tool_gateway.py python\tests\test_model_tool_adapter.py python\tests\test_planner_v2.py
```

Expected:

```text
... passed
```

- [ ] **Step 2: Run frontend regression**

Run:

```powershell
npm run frontend:test -- src/features/task/useTaskEvents.test.ts src/app/backendEvents.test.ts
```

Expected:

```text
Test Files  2 passed
```

- [ ] **Step 3: Run Rust regression**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml --test sidecar_tests --test tauri_config_tests
```

Expected:

```text
test result: ok
```

- [ ] **Step 4: Run full MVP verification**

Run:

```powershell
.\scripts\verify-mvp.ps1
```

Expected:

```text
Python tests pass.
Rust tests pass.
Frontend typecheck passes.
```

If the script uses different wording, accept successful zero exit status and no failed test summary.

- [ ] **Step 5: Manual sidecar auth smoke check**

Start a development sidecar:

```powershell
npm run sidecar:dev
```

In a second PowerShell window, run:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8765/health
```

Expected:

```text
status
------
ok
```

Then stop the sidecar with `Ctrl+C`.

- [ ] **Step 6: Manual fail-closed smoke check**

Run a raw sidecar without the development bypass:

```powershell
cd python
python -m uvicorn agent_service.app:app --host 127.0.0.1 --port 8765
```

In a second PowerShell window, run:

```powershell
Invoke-WebRequest -Uri http://127.0.0.1:8765/agent/message -Method POST -ContentType "application/json" -Body '{"task_id":"manual-auth","content":"hello","attachments":[]}'
```

Expected: HTTP `401` with response detail `sidecar token is not configured`.

Then stop the raw sidecar with `Ctrl+C`.

- [ ] **Step 7: Manual desktop development smoke check**

Run:

```powershell
npm run desktop:dev
```

Expected:

- The `Alita` desktop window opens.
- The sidecar health check passes on `127.0.0.1:8765`.
- Sending `hello` returns a normal chat response path, not HTTP `401`.
- Sending `请总结这个文件` without an attachment asks for a document file.

- [ ] **Step 8: Confirm no uncommitted implementation drift remains**

Run:

```powershell
git status --short
```

Expected: no modified implementation files remain outside the commits from Tasks 2, 3, 4, 5, and 6. If this command shows a modified file from one of those tasks, return to that task, rerun its focused tests, and use that task's exact `git add`/`git commit` command.

---

## Completion Criteria

Phase A is complete when all statements are true:

- `python/agent_service/app.py` rejects protected requests with HTTP `401` when neither `ALITA_SIDECAR_TOKEN` nor `ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV=1` is present.
- Existing packaged Tauri sidecar behavior still works through `ALITA_SIDECAR_TOKEN`.
- Browser/Vite and `npm run desktop:dev` development flows remain available through an explicit development bypass.
- Sidecar CORS no longer uses `allow_origins=["*"]`.
- `src-tauri/tauri.conf.json` no longer has `"csp": null`.
- Python, npm, Tauri, and Cargo versions are all `0.28.0`.
- `_DOCUMENT_ACTIONS` and `_DOCUMENT_REFERENCES` no longer contain mojibake tokens.
- The focused Python, frontend, and Rust test commands in Task 7 pass, or the final note records a local toolchain blocker with the failing command output.

## Handoff Notes For Phase B

After this plan lands, Phase B can introduce `AgentRunState`/runtime contracts without mixing in security cleanup. Phase B must treat the stricter sidecar auth as the new default and keep `ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV` confined to development scripts and tests.
