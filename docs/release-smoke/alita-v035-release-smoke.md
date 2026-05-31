# Alita v0.35 Release Smoke Checklist

This checklist records manual release evidence for live dependencies and desktop UI paths. It is not an automated CI gate and may require network access, local models, desktop interaction, API keys, or machine-specific tools.

Date:
Commit:
Tester:
Windows version:
Evidence folder: `docs/test-results/v035-release-smoke-YYYYMMDD-HHMMSS`

## Desktop Launch Smoke

1. Run `npm run check:desktop-prereqs`.
2. Run `npm run desktop:dev`.
3. Expected: a Windows desktop window titled `Alita` opens.
4. Save screenshot as `desktop-launch.png`.

## Project File Smoke

1. Create `D:\Temp\alita-smoke\v035.alita`.
2. Send `你好，记录一条 smoke 消息。`.
3. Save the project.
4. Close and reopen the application.
5. Open `D:\Temp\alita-smoke\v035.alita`.
6. Expected: chat message, project path, saved state, and graph area restore.
7. Save the `.alita` file copy as `project-after-reopen.alita`.

## Local Model Smoke

1. Set `ALITA_LLAMA_MODEL_PATH` to a local GGUF model.
2. Run `npm run desktop:dev`.
3. Send `用一句话回复：本地模型 smoke 通过。`.
4. Expected: model response is streamed or returned without sidecar error.
5. Save sidecar log excerpt as `local-model-sidecar.log`.

## Document Artifact Smoke

1. Attach a small `.md` or `.docx` file.
2. Send `帮我整理成中文报告并导出 PDF。`.
3. Run the generated graph.
4. Expected: Markdown and PDF/Typst artifacts are created, or a clear Typst dependency error appears.
5. Save artifact preview screenshot as `document-artifact-preview.png`.

## Research Artifact Smoke

1. Ask `请调研 Alita v0.35 当前 Agent Runtime 测试覆盖情况，并生成研究报告。`.
2. Choose `Research flow`.
3. Run graph.
4. Expected: Markdown report artifact contains citations such as `[S1]`.
5. Save report as `research-report.md`.

## Live Network Smoke

1. Without `ALITA_BRAVE_SEARCH_API_KEY`, ask a simple current web question.
2. Expected: DuckDuckGo fallback is used or a safe network failure is shown.
3. With `ALITA_BRAVE_SEARCH_API_KEY`, ask the same question.
4. Expected: Brave provider is used.
5. Ask `今天上海天气怎么样？`.
6. Expected: weather path is used instead of generic search.
7. Save provider/result notes as `live-network-provider-summary.md`.

## API Key Redaction Smoke

1. Configure an API provider with a test key.
2. Save preferences.
3. Inspect `.alita`, preferences JSON, run history, and visible UI.
4. Expected: the raw key is not present.
5. Save grep output summary as `api-key-redaction.txt`.

## ASR Smoke

1. Configure Qwen3-ASR model directory.
2. Record a 3-second Chinese sentence.
3. Expected: transcribed text appears in the chat draft.
4. Save screenshot as `asr-transcription.png`.

## Artifact Preview Smoke

1. Open Markdown/text artifact preview.
2. Open PDF artifact preview.
3. Open image artifact preview.
4. Open audio/video artifact preview if sample exists.
5. Expected: each preview is non-empty or gives a precise unsupported-format message.
6. Save screenshots as `artifact-preview-markdown.png`, `artifact-preview-pdf.png`, and one media/unsupported screenshot.

## Runtime Resume Smoke

1. Run a document or research graph until checkpoints are recorded.
2. Trigger a recoverable failure by disabling one tool.
3. Re-enable the tool.
4. Resume from latest checkpoint.
5. Expected: completed nodes are not repeated, and final artifact is present.
6. Save run-history or trace excerpt as `runtime-resume-trace.jsonl` and screenshot as `runtime-resume.png`.

## MCP Stdio Smoke

1. Configure the test echo MCP stdio server with command `python python/tests/fixtures/mcp_stdio_server.py`.
2. Refresh tools.
3. Run a task using the echo tool.
4. Expected: tool discovery and call complete with authority records.
5. Save tool discovery screenshot as `mcp-tool-discovery.png`.
6. Save the relevant run trace or node-run JSON containing `authority.decision_recorded` / `tool.call` records as `mcp-authority-trace.jsonl`.
