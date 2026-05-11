from __future__ import annotations

from pathlib import Path

import pytest

from tools.markitdown_tool import convert_local_file


class FakeConversionResult:
    text_content = "# 转换结果\n\n正文"


class FakeMarkItDown:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def convert_local(self, source: str) -> FakeConversionResult:
        self.calls.append(source)
        return FakeConversionResult()


def test_converts_local_file_to_markdown_artifact(tmp_path, monkeypatch):
    project_path = tmp_path / "project"
    source = project_path / "source.docx"
    output = tmp_path / "artifacts" / "converted" / "source.md"
    project_path.mkdir()
    source.write_text("source content", encoding="utf-8")
    fake_converter = FakeMarkItDown()

    monkeypatch.setattr(
        "tools.markitdown_tool._create_markitdown", lambda: fake_converter
    )

    result = convert_local_file(
        str(source),
        str(output),
        str(project_path),
        allowed_roots=[str(project_path)],
    )

    assert result.text == "# 转换结果\n\n正文"
    assert output.read_text(encoding="utf-8") == "# 转换结果\n\n正文"
    assert result.artifacts == [str(output.resolve())]
    assert result.metadata == {
        "source_path": str(source.resolve()),
        "converter": "markitdown",
        "output_format": "markdown",
    }
    assert fake_converter.calls == [str(source.resolve())]


def test_rejects_network_inputs(tmp_path):
    output = tmp_path / "artifacts" / "converted" / "source.md"

    with pytest.raises(ValueError, match="network_input_forbidden"):
        convert_local_file(
            "https://example.com/source.pdf",
            str(output),
            str(tmp_path / "project"),
            allowed_roots=[str(tmp_path)],
        )


def test_rejects_unc_inputs_with_backslashes_and_forward_slashes(tmp_path):
    output = tmp_path / "artifacts" / "converted" / "source.md"

    for input_path in (r"\\server\share\file.pdf", "//server/share/file.pdf"):
        with pytest.raises(ValueError, match="network_input_forbidden"):
            convert_local_file(
                input_path,
                str(output),
                str(tmp_path / "project"),
                allowed_roots=[str(tmp_path)],
            )


def test_rejects_url_like_inputs_with_scheme_or_netloc(tmp_path):
    output = tmp_path / "artifacts" / "converted" / "source.md"

    for input_path in ("file://server/share/file.pdf", "data:text/plain,hello"):
        with pytest.raises(ValueError, match="network_input_forbidden"):
            convert_local_file(
                input_path,
                str(output),
                str(tmp_path / "project"),
                allowed_roots=[str(tmp_path)],
            )


def test_rejects_path_outside_allowed_roots(tmp_path):
    project_path = tmp_path / "project"
    outside = tmp_path / "outside" / "source.pdf"
    output = tmp_path / "artifacts" / "converted" / "source.md"
    outside.parent.mkdir()
    outside.write_text("source content", encoding="utf-8")
    project_path.mkdir()

    with pytest.raises(ValueError, match="path_outside_project"):
        convert_local_file(
            str(outside),
            str(output),
            str(project_path),
            allowed_roots=[str(project_path)],
        )


def test_rejects_unsupported_file_suffix(tmp_path):
    project_path = tmp_path / "project"
    source = project_path / "source.exe"
    output = tmp_path / "artifacts" / "converted" / "source.md"
    project_path.mkdir()
    source.write_text("source content", encoding="utf-8")

    with pytest.raises(ValueError, match=r"unsupported_format:\.exe"):
        convert_local_file(
            str(source),
            str(output),
            str(project_path),
            allowed_roots=[str(project_path)],
        )


def test_rejects_output_outside_artifacts_converted(tmp_path):
    project_path = tmp_path / "project"
    source = project_path / "source.pdf"
    output = project_path / "source.md"
    project_path.mkdir()
    source.write_text("source content", encoding="utf-8")

    with pytest.raises(
        ValueError, match="output_write_failed:outside_artifacts_converted"
    ):
        convert_local_file(
            str(source),
            str(output),
            str(project_path),
            allowed_roots=[str(project_path)],
        )
