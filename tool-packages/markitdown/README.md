# MarkItDown 工具包

## 来源

第一版集成 Microsoft MarkItDown，来源为 https://github.com/microsoft/markitdown，按外部 Python 包通过 `python_sidecar` 运行。

## 第一版用途

该工具包提供 `document.markitdown_convert`，用于把项目内或附件中的本地文档转换为适合模型读取的 Markdown 文本，并把结果写入 `artifacts/converted`。

第一版操作为 `convert_local_file`，面向单个本地文件转换。计划覆盖 Word、PDF、PowerPoint、Excel 等 MarkItDown 依赖组合支持的常见文档格式。

## 第一版限制

第一版不允许网络输入，不启用 MarkItDown 插件扩展，不处理远程 URL，也不在 manifest 层承诺批量转换。单个输入文件大小上限为 100 MB，转换超时时间为 120 秒。

## 权限

该工具包需要以下权限：

- `read_project_files`：读取项目内或附件中的输入文档。
- `write_project_outputs`：写入转换后的 Markdown artifact。
- `run_python_plugin`：通过 Python sidecar 调用外部 MarkItDown 包执行转换。
