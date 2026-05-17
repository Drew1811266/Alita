from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools.typst_tool import compile_report_pdf


def test_compile_report_pdf_writes_typst_source_and_pdf_with_fake_typst(
    tmp_path: Path,
) -> None:
    typst_bin = _write_fake_typst_binary(tmp_path)
    source_path = tmp_path / "artifacts" / "typst" / "report.typ"
    pdf_path = tmp_path / "artifacts" / "typst" / "report.pdf"

    result = compile_report_pdf(
        title="Quarterly #1",
        outline="* sales increased",
        report="Revenue [draft] is $10.",
        source_output_path=str(source_path),
        pdf_output_path=str(pdf_path),
        project_path=str(tmp_path / "project.alita"),
        allowed_roots=[str(tmp_path)],
        typst_binary=str(typst_bin),
    )

    assert result.source_path == str(source_path)
    assert result.pdf_path == str(pdf_path)
    assert result.artifacts == [str(source_path), str(pdf_path)]
    assert result.metadata["compiler"] == "typst"
    assert source_path.exists()
    assert pdf_path.exists()
    source = source_path.read_text(encoding="utf-8")
    assert "= Quarterly \\#1" in source
    assert "Revenue \\[draft\\] is \\$10." in source


def test_compile_report_pdf_rejects_output_outside_project_artifacts(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="outside_artifacts_typst"):
        compile_report_pdf(
            title="Report",
            outline="outline",
            report="report",
            source_output_path=str(tmp_path / "outside.typ"),
            pdf_output_path=str(tmp_path / "artifacts" / "typst" / "report.pdf"),
            project_path=str(tmp_path / "project.alita"),
            allowed_roots=[str(tmp_path)],
            typst_binary=str(tmp_path / "typst"),
        )


def _write_fake_typst_binary(tmp_path: Path) -> Path:
    if os.name == "nt":
        script = tmp_path / "typst.cmd"
        script.write_text(
            "@echo off\r\n"
            "if \"%1\" NEQ \"compile\" exit /B 2\r\n"
            "copy /Y \"%2\" \"%3\" >NUL\r\n",
            encoding="utf-8",
        )
        return script

    script = tmp_path / "typst"
    script.write_text(
        "#!/usr/bin/env sh\n"
        "if [ \"$1\" != \"compile\" ]; then exit 2; fi\n"
        "cp \"$2\" \"$3\"\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script
