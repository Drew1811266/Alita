# 插件化工具体系与 MarkItDown 接入设计

## 1. 背景

Alita的核心不是让用户直接操作工具，而是让 AI Agent 理解用户目标后，调用工具节点完成生产任务。当前项目已经有一个最小工具体系：

- Rust 侧通过 `src-tauri/src/tools.rs` 读取 `tool-packages/document/manifest.json`。
- Python 侧通过 `python/tools/document_tool.py` 提供基础文档读写能力。
- LangGraph 侧在 `python/agent_service/graph.py` 生成文档处理节点图。
- 节点执行侧在 `python/agent_service/execution.py` 按节点 ID 执行文档读取、模型整理、报告生成和导出。

这个基础可用，但还不是完整的可插拔工具体系。工具依赖、执行适配器、权限边界、版本信息、节点模板、启停状态、错误协议还没有统一抽象。

MarkItDown 适合作为第一个外部开源工具接入。它是 Microsoft 开源的 Python 工具，目标是把 PDF、Word、Excel、PowerPoint、HTML、CSV、JSON、XML、ZIP 等文件转换为适合 LLM 使用的 Markdown。官方文档也明确提醒它会以当前进程权限执行 I/O，因此必须限制输入路径、调用更窄的本地转换 API，并谨慎处理不可信输入。

参考来源：

- https://github.com/microsoft/markitdown

## 2. 已确认决策

- 工具必须是模块化、可插拔的组件。
- 自研工具和外部开源工具都应通过同一套工具包协议接入。
- 工具主要面向 AI 调用，不要求每个工具都有独立图形界面。
- 第一版以本地优先为原则。
- MarkItDown 第一阶段只作为本地文件转 Markdown 工具，不启用 URL 抓取、三方插件、Azure Document Intelligence、远程 OCR 或音频转写。
- 第一版先做轻量隔离：同一个 Python sidecar 环境内运行，但通过 manifest、适配器、权限校验和标准错误码隔离工具边界。
- 后续再升级到强隔离：独立虚拟环境、独立进程、资源限制、工具安装/卸载与版本锁定。

## 3. 目标

1. 建立统一的工具包结构，让每个工具独立声明能力、入口、依赖、权限、输入输出和错误码。
2. 让 Rust、Python、前端都能从工具 manifest 获得一致的工具信息。
3. 把 MarkItDown 接成一个固定工具节点，供 Agent 在文档处理流程中调用。
4. 让 MarkItDown 输出 Markdown 文本和项目 artifact 文件，供后续模型节点继续处理。
5. 在首选项中能看到已安装工具、工具来源、版本、许可证和权限范围。

## 4. 非目标

第一版不做以下事情：

- 不做工具市场、在线下载、自动升级。
- 不允许工具自由访问网络。
- 不启用 MarkItDown 插件生态。
- 不把 MarkItDown 当作万能文档处理器替代所有文档工具。
- 不做每个工具的可视化 UI。
- 不做完整容器级沙箱。
- 不做批量目录转换。

## 5. 推荐方案

采用“Manifest 驱动的轻量工具包体系”。

每个工具都是一个独立工具包：

```text
tool-packages/
  document/
    manifest.json
  markitdown/
    manifest.json
    README.md

python/
  tools/
    document_tool.py
    markitdown_tool.py
```

核心原则：

- `manifest.json` 是工具对软件和 Agent 的公开契约。
- `python/tools/<tool>_tool.py` 是工具执行适配器。
- 工具之间不直接互相调用。
- 节点执行器只通过统一 `ToolInvocation -> ToolResult` 协议调用工具。
- 前端只展示工具 manifest 和节点运行结果，不依赖工具内部实现。

这个方案比直接把 MarkItDown 写进 `document_tool.py` 更稳，因为它能证明“外部开源工具也能作为独立组件接入”。它也比一开始就上独立进程沙箱更现实，因为当前项目还处在 MVP 到 V2 的过渡阶段。

## 6. 工具包协议

现有 manifest 字段继续保留：

- `tool_id`
- `name`
- `description`
- `version`
- `source_type`
- `license`
- `entrypoint`
- `input_schema`
- `output_schema`
- `permissions`
- `examples`
- `error_codes`
- `timeout_policy`
- `artifact_policy`

新增建议字段：

- `runtime`: 工具运行时，例如 `python_sidecar`。
- `package`: 工具包信息，例如来源、上游仓库、锁定版本。
- `capabilities`: Agent 可理解的能力标签，例如 `document.convert.markdown`。
- `operations`: 工具可调用操作列表，例如 `convert_local_file`。
- `dependency_policy`: 依赖安装策略和可选依赖集合。
- `security_policy`: 路径、网络、插件、最大文件大小、输出目录限制。
- `node_templates`: 工具在节点画布中的默认节点模板。

第一版 Rust 可以先允许这些字段作为结构化 JSON 读取，不要求一次性做复杂校验。关键字段必须校验，安全字段必须在 Python 执行前再次校验。

## 7. MarkItDown 工具设计

工具 ID：

```text
document.markitdown_convert
```

工具来源：

```text
external_python_package
```

Python 入口：

```text
python/tools/markitdown_tool.py
```

第一版操作：

```text
convert_local_file
```

输入：

```json
{
  "operation": "convert_local_file",
  "input_path": "项目内或已导入附件的文件路径",
  "output_path": "artifacts/converted/<文件名>.md"
}
```

输出：

```json
{
  "text": "转换后的 Markdown 正文",
  "artifacts": ["artifacts/converted/<文件名>.md"],
  "metadata": {
    "source_path": "原始文件路径",
    "converter": "markitdown",
    "output_format": "markdown"
  }
}
```

第一版支持格式：

- PDF
- DOCX
- PPTX
- XLSX
- TXT
- MD
- HTML
- CSV
- JSON
- XML

依赖建议：

```text
markitdown[pdf,docx,pptx,xlsx]
```

不建议第一版直接使用 `markitdown[all]`，因为它会扩大依赖体积和打包风险。后续如果需要 Outlook、音频转写、YouTube、Azure Document Intelligence，再作为独立能力开关加入。

## 8. 安全边界

MarkItDown 工具必须满足以下限制：

- 只允许读取项目文件或聊天区明确导入的附件文件。
- 只允许写入当前工程的 `artifacts/converted/` 目录。
- 禁止 URL、网络地址、UNC 网络路径和远程资源。
- 禁用 MarkItDown 插件：`enable_plugins=False`。
- 优先调用本地文件转换能力，避免使用过于宽泛的远程 URI 转换入口。
- 设定单文件大小上限，第一版建议 100MB。
- 设定超时时间，第一版建议 120 秒。
- 所有错误转成标准错误码返回给节点执行系统。

标准错误码：

- `unsupported_format`
- `input_not_found`
- `path_outside_project`
- `network_input_forbidden`
- `dependency_missing`
- `conversion_failed`
- `output_write_failed`
- `timeout`

## 9. Agent 与节点集成

文档类任务生成流程图时，`document-parse` 节点应从“基础文档解析”升级为“文档转 Markdown”节点：

```text
文档输入 -> MarkItDown 转 Markdown -> 整理内容 / 生成报告 -> 导出文件
```

节点展示信息：

- 类型：工具
- 名称：文档转 Markdown
- 工具引用：`document.markitdown_convert`
- 功能：把本地文档转换成适合模型读取的 Markdown
- 输入端口：文档
- 输出端口：Markdown 正文

如果 MarkItDown 不支持某个格式，节点应失败并显示简短错误。后续 Agent 可以基于失败原因尝试选择其他工具或请求用户换文件。

## 10. 执行系统集成

当前 `DocumentFlowExecutor` 直接按节点 ID 写死逻辑。下一步应增加一个轻量 `ToolExecutor`：

```text
GraphNode.toolRef
  -> ToolRegistry 查找 manifest
  -> ToolExecutor 加载 Python 适配器
  -> Adapter 执行 operation
  -> ToolResult 写入节点运行记录
```

第一版可以只把 MarkItDown 和现有 document 工具纳入这个路径，不强制迁移所有模型节点。模型节点继续走 `model_client`。

建议新增 Python 协议：

```python
@dataclass(frozen=True)
class ToolInvocation:
    tool_id: str
    operation: str
    arguments: dict[str, object]
    project_path: str

@dataclass(frozen=True)
class ToolResult:
    values: dict[str, str]
    artifacts: list[str]
    metadata: dict[str, str]
```

## 11. 首选项展示

首选项中的“工具/节点”列表应展示：

- 工具名称
- 工具 ID
- 来源：内置 / 外部开源
- 版本
- 许可证
- 状态：已启用 / 未启用 / 依赖缺失
- 权限：读取工程文件、写入产物、运行 Python 工具
- 支持能力：例如文档转 Markdown

第一版可以只读 manifest 展示状态，不做安装/卸载。依赖缺失时显示为“不可用”，并在执行时返回 `dependency_missing`。

## 12. 测试策略

Rust 测试：

- 验证 MarkItDown manifest 可加载。
- 验证新增 manifest 字段不会破坏现有 document manifest。
- 验证关键字段为空时仍会失败。

Python 测试：

- 验证本地文件转换会写入 Markdown artifact。
- 验证 URL 输入会被拒绝。
- 验证项目外路径会被拒绝。
- 验证依赖缺失时返回 `dependency_missing`。
- 验证转换异常会返回 `conversion_failed`。

执行流测试：

- 构造带附件的文档任务。
- 运行节点流程。
- 验证 `document.markitdown_convert` 节点完成。
- 验证后续模型节点拿到 Markdown 文本。
- 验证最终导出文件包含整理结果和报告正文。

打包验证：

- 运行 Python 测试。
- 构建 sidecar。
- 构建 Tauri release。
- 启动桌面软件。
- 用一个 DOCX 或 PDF 附件执行文档流程。

## 13. 分阶段实施

第一阶段：工具包协议扩展。

- 扩展 manifest 结构和测试。
- 明确工具权限、安全策略、依赖策略字段。
- 首选项继续读取本地工具包目录。

第二阶段：MarkItDown 工具接入。

- 新增 `tool-packages/markitdown/manifest.json`。
- 新增 `python/tools/markitdown_tool.py`。
- 增加本地路径、输出路径、格式、超时和错误处理。
- 增加 Python 单元测试。

第三阶段：节点执行接入。

- 新增轻量 ToolRegistry / ToolExecutor。
- 让文档解析节点调用 `document.markitdown_convert`。
- 保留现有 `document_tool.py` 作为基础读写工具。

第四阶段：首选项展示完善。

- 展示 MarkItDown 工具来源、版本、许可证、权限和启用状态。
- 当依赖缺失时给出清晰状态。

第五阶段：打包与验证。

- 更新 sidecar 打包脚本。
- 验证 release 桌面软件能调用 MarkItDown。
- 用真实文件完成一轮端到端测试。

## 14. 风险与控制

- 依赖体积风险：不使用 `markitdown[all]`，先选择文档类常用 extras。
- 打包风险：PyInstaller 可能需要显式收集 MarkItDown 及其格式依赖。
- 安全风险：禁止 URL 和插件，限制输入输出路径。
- 兼容风险：如果某些 PDF 转换质量不稳定，节点应保留失败信息并允许后续接入 OCR 或其他解析工具。
- 架构风险：不要把 MarkItDown 混进基础 document 工具，避免第一个外部工具就破坏插件边界。

## 15. 验收标准

- 软件可以在首选项中识别 MarkItDown 工具。
- Agent 生成的文档流程图中可以出现 MarkItDown 工具节点。
- 用户导入 DOCX、PDF、PPTX 或 XLSX 后，流程执行能先生成 Markdown artifact。
- 后续模型节点能基于 Markdown 正文生成整理内容和报告。
- URL 输入、项目外路径、依赖缺失、转换失败都有明确错误。
- 现有文档工具和已有节点执行能力不被破坏。



