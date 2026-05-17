from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess


DEFAULT_TIMEOUT_SECONDS = 90


@dataclass(frozen=True)
class TypstCompileResult:
    source_path: str
    pdf_path: str
    artifacts: list[str]
    metadata: dict[str, str]


def compile_report_pdf(
    *,
    title: str,
    outline: str,
    report: str,
    source_output_path: str,
    pdf_output_path: str,
    project_path: str,
    allowed_roots: list[str],
    typst_binary: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> TypstCompileResult:
    project_file = Path(project_path).expanduser().resolve()
    typst_root = (project_file.parent / "artifacts" / "typst").resolve()
    source_output = Path(source_output_path).expanduser().resolve()
    pdf_output = Path(pdf_output_path).expanduser().resolve()

    if source_output.suffix.lower() != ".typ":
        raise ValueError("output_write_failed:source_must_end_with_typ")
    if pdf_output.suffix.lower() != ".pdf":
        raise ValueError("output_write_failed:pdf_must_end_with_pdf")
    if not _is_relative_to(source_output, typst_root):
        raise ValueError("output_write_failed:outside_artifacts_typst")
    if not _is_relative_to(pdf_output, typst_root):
        raise ValueError("output_write_failed:outside_artifacts_typst")

    binary = _resolve_typst_binary(typst_binary)
    if not binary:
        raise ValueError("dependency_missing:typst")

    source = _render_typst_report(title=title, outline=outline, report=report)
    try:
        source_output.parent.mkdir(parents=True, exist_ok=True)
        source_output.write_text(source, encoding="utf-8")
    except OSError as error:
        raise ValueError(f"output_write_failed:{source_output}") from error

    try:
        completed = subprocess.run(
            _typst_command(binary, source_output, pdf_output),
            cwd=str(typst_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as error:
        raise ValueError("dependency_missing:typst") from error
    except subprocess.TimeoutExpired as error:
        raise ValueError("timeout:typst_compile") from error

    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "typst_compile_failed").strip()
        raise ValueError(f"compile_failed:{message}")

    if not pdf_output.is_file():
        raise ValueError("compile_failed:pdf_missing")

    return TypstCompileResult(
        source_path=str(source_output),
        pdf_path=str(pdf_output),
        artifacts=[str(source_output), str(pdf_output)],
        metadata={
            "compiler": "typst",
            "source_format": "typst",
            "output_format": "pdf",
        },
    )


def _resolve_typst_binary(typst_binary: str | None) -> str | None:
    configured = (typst_binary or os.getenv("ALITA_TYPST_BIN", "")).strip()
    if configured:
        return configured
    return shutil.which("typst")


def _typst_command(binary: str, source_output: Path, pdf_output: Path) -> list[str]:
    if os.name == "nt" and Path(binary).suffix.lower() in {".bat", ".cmd"}:
        return ["cmd", "/c", binary, "compile", str(source_output), str(pdf_output)]
    return [binary, "compile", str(source_output), str(pdf_output)]


def _render_typst_report(*, title: str, outline: str, report: str) -> str:
    safe_title = _escape_typst_markup(title.strip() or "Alita Report")
    return "\n".join(
        [
            f"#set document(title: {_typst_string(title.strip() or 'Alita Report')})",
            "#set page(margin: 2cm)",
            "#set text(size: 11pt, lang: \"zh\")",
            "",
            f"= {safe_title}",
            "",
            "== 整理内容",
            "",
            _escape_typst_markup(outline.strip() or "无整理内容。"),
            "",
            "== 报告正文",
            "",
            _escape_typst_markup(report.strip() or "无报告正文。"),
            "",
        ]
    )


def _typst_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _escape_typst_markup(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    escaped: list[str] = []
    for character in normalized:
        if character in {"\\", "#", "*", "_", "[", "]", "$", "<", ">", "@", "=", "~", "`"}:
            escaped.append(f"\\{character}")
        else:
            escaped.append(character)
    return "".join(escaped)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
