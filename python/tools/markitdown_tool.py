from __future__ import annotations

from dataclasses import dataclass
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
NETWORK_SCHEMES = {"http", "https", "ftp", "s3"}


@dataclass(frozen=True)
class MarkItDownResult:
    text: str
    artifacts: list[str]
    metadata: dict[str, str]


def convert_local_file(
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

    output = Path(output_path).expanduser().resolve()
    if output.suffix.lower() != ".md":
        raise ValueError("output_write_failed:output_must_end_with_md")

    converted_root = (
        Path(project_path).expanduser().resolve().parent / "artifacts" / "converted"
    ).resolve()
    if not _is_relative_to(output, converted_root):
        raise ValueError("output_write_failed:outside_artifacts_converted")

    converter = _create_markitdown()
    try:
        conversion = converter.convert_local(str(source))
        text = conversion.text_content
    except Exception as error:
        raise ValueError(f"conversion_failed:{source.name}") from error

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
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


def _is_network_input(input_path: str) -> bool:
    if input_path.startswith(("\\\\", "//")):
        return True

    parsed = urlparse(input_path)
    if parsed.netloc:
        return True

    scheme = parsed.scheme.lower()
    if not scheme:
        return False

    is_windows_drive = (
        len(scheme) == 1 and scheme.isalpha() and len(input_path) > 1 and input_path[1] == ":"
    )
    if is_windows_drive:
        return False

    return scheme in NETWORK_SCHEMES or bool(scheme)


def _is_inside_any(path: Path, roots: list[Path]) -> bool:
    return any(_is_relative_to(path, root) for root in roots)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
