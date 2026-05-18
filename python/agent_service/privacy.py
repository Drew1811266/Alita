from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class PrivacyGuardResult:
    sanitizedText: str
    removedCategories: list[str]
    blocked: bool
    reason: str | None


_LOCAL_PATH_LABEL = "[LOCAL_PATH]"
_LOCAL_FILE_CONTENT_LABEL = "[LOCAL_FILE_CONTENT]"
_MODEL_PATH_LABEL = "[MODEL_PATH]"
_SECRET_LABEL = "[SECRET]"
_EMAIL_LABEL = "[EMAIL]"

_WINDOWS_PATH_RE = re.compile(
    r"(?<![\w])(?:[A-Za-z]:\\(?:[^\r\n\\/:*?\"<>|]+\\)+"
    r"(?:"
    r"[^\r\n\\/:*?\"<>|]*?\.[A-Za-z0-9][A-Za-z0-9_-]*"
    r"(?=$|[\s,;:!?)]|\.(?:$|\s))|"
    r"[^\s\r\n\\/:*?\"<>|.,;:!?)]*"
    r"(?=$|[\s,;:!?)]|\.(?:$|\s))"
    r"))"
)
_POSIX_PATH_RE = re.compile(r"(?<![\w:/])/(?:[^\s/]+/)+[^\s/]+")
_MODEL_NAME_RE = re.compile(
    r"\b(?:Qwen|Llama|Mistral|Mixtral|Phi|Gemma|DeepSeek|Claude|GPT|Whisper)"
    r"[A-Za-z0-9._-]*(?:-[A-Za-z0-9._-]+)*\b",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_SECRET_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|gho_[A-Za-z0-9_]{20,}|"
    r"ghu_[A-Za-z0-9_]{20,}|ghs_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b|"
    r"\b[A-Za-z_][A-Za-z0-9_]*_URL\s*[:=]\s*['\"]?"
    r"[A-Za-z][A-Za-z0-9+.-]*://[^\s:@/]+:[^\s@/]+@[^\s'\"]+['\"]?|"
    r"\b(?:DATABASE_URL|REDIS_URL|POSTGRES_URL)\s*[:=]\s*['\"]?[^\s'\"]{8,}['\"]?|"
    r"\b[A-Za-z_][A-Za-z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASS|API_KEY|ACCESS_KEY|"
    r"PRIVATE_KEY|KEY)[A-Za-z0-9_]*\s*[:=]\s*['\"]?[^\s'\"]{8,}['\"]?|"
    r"\b(?:[A-Za-z0-9]+_)*(?:api[_-]?key|token|password|secret)"
    r"\s*[:=]\s*['\"]?[A-Za-z0-9._~+/=-]{20,}['\"]?|"
    r"\b(?:Authorization\s*:\s*)?Bearer\s+[A-Za-z0-9._~+/=-]{20,}\b|"
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
    re.IGNORECASE,
)
_REDACTION_LABEL_RE = re.compile(
    r"\[(?:LOCAL_PATH|LOCAL_FILE_CONTENT|MODEL_PATH|SECRET|EMAIL)\]"
)
_MEANINGFUL_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)

_COMMON_LOCAL_COMPONENTS = {
    "app",
    "coder",
    "config",
    "desktop",
    "documents",
    "downloads",
    "drew",
    "file",
    "files",
    "home",
    "models",
    "project",
    "projects",
    "python",
    "src",
    "software",
    "users",
}
_PATH_BOUNDARY_PREPOSITIONS = {
    "and",
    "about",
    "for",
    "from",
    "in",
    "on",
    "using",
    "with",
}
_LOCAL_TAIL_NOUNS = {
    "archive",
    "cache",
    "checkpoint",
    "data",
    "dataset",
    "directory",
    "file",
    "files",
    "folder",
    "model",
    "notes",
    "project",
    "repo",
    "vault",
    "workspace",
}
_LOCAL_TAIL_PREFIXES = {
    "client",
    "confidential",
    "custom",
    "draft",
    "hidden",
    "internal",
    "local",
    "my",
    "new",
    "old",
    "private",
    "secret",
    "test",
    "very",
}
_COMMAND_ONLY_TOKENS = {
    "cat",
    "cd",
    "copy",
    "cp",
    "del",
    "dir",
    "echo",
    "f",
    "git",
    "log",
    "ls",
    "mkdir",
    "move",
    "mv",
    "python",
    "r",
    "rd",
    "rf",
    "rm",
    "rmdir",
    "status",
    "type",
}


def sanitize_for_web_search(text: str) -> PrivacyGuardResult:
    categories: list[str] = []
    project_names = _extract_project_names(text)

    sanitized = text.strip()
    sanitized = _redact_file_like_content(sanitized, categories)
    sanitized = _redact_model_paths(sanitized, categories)
    sanitized = _redact(_EMAIL_RE, sanitized, _EMAIL_LABEL, "EMAIL", categories)
    sanitized = _redact(_SECRET_RE, sanitized, _SECRET_LABEL, "SECRET", categories)
    sanitized = _redact_local_paths(sanitized, categories)
    sanitized = _redact_project_names(sanitized, project_names, categories)
    sanitized = _normalize_spaces(sanitized)

    reason = _block_reason(sanitized)
    return PrivacyGuardResult(
        sanitizedText=sanitized,
        removedCategories=categories,
        blocked=reason is not None,
        reason=reason,
    )


def _redact(
    pattern: re.Pattern[str],
    text: str,
    label: str,
    category: str,
    categories: list[str],
) -> str:
    redacted, count = pattern.subn(label, text)
    if count:
        _add_category(categories, category)
    return redacted


def _redact_file_like_content(text: str, categories: list[str]) -> str:
    lines = text.splitlines()
    if len(lines) < 3:
        return text

    start = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if _looks_like_file_content_line(stripped):
            start = index
            break

    if start is None:
        return text

    prefix = "\n".join(lines[:start]).strip()
    _add_category(categories, "LOCAL_FILE_CONTENT")
    if not prefix:
        return _LOCAL_FILE_CONTENT_LABEL
    return f"{prefix}\n{_LOCAL_FILE_CONTENT_LABEL}"


def _looks_like_file_content_line(line: str) -> bool:
    if not line:
        return False
    return (
        line.startswith(("Traceback", "File ", "def ", "class ", "return ", "KeyError"))
        or bool(re.match(r"^(?:INFO|DEBUG|WARN|WARNING|ERROR|CRITICAL)\b", line))
        or bool(
            re.match(
                r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\s+"
                r"(?:INFO|DEBUG|WARN|WARNING|ERROR|CRITICAL)\b",
                line,
            )
        )
        or bool(re.match(r"^(?:import|from)\s+\w+", line))
        or bool(re.match(r"^print\s*\(", line))
        or bool(re.match(r"^\s*(?:if|for|while|try|except|with)\b.*:", line))
    )


def _redact_model_paths(text: str, categories: list[str]) -> str:
    def replace_path(match: re.Match[str]) -> str:
        value = _extend_spaced_path_suffix(match, text)
        if _is_model_path(value):
            _add_category(categories, "MODEL_PATH")
            return _MODEL_PATH_LABEL
        return value

    text = _replace_matches(_WINDOWS_PATH_RE, text, replace_path)
    text = _replace_matches(_POSIX_PATH_RE, text, replace_path)
    return _redact(_MODEL_NAME_RE, text, _MODEL_PATH_LABEL, "MODEL_PATH", categories)


def _redact_local_paths(text: str, categories: list[str]) -> str:
    text = _redact_path_pattern(_WINDOWS_PATH_RE, text, categories)
    return _redact_path_pattern(_POSIX_PATH_RE, text, categories)


def _redact_path_pattern(
    pattern: re.Pattern[str],
    text: str,
    categories: list[str],
) -> str:
    def replace(match: re.Match[str]) -> str:
        value = _extend_spaced_path_suffix(match, text)
        punctuation = ""
        while value.endswith((".", ",", ";", ":", "!", "?")):
            punctuation = value[-1] + punctuation
            value = value[:-1]
        _add_category(categories, "LOCAL_PATH")
        return f"{_LOCAL_PATH_LABEL}{punctuation}"

    return _replace_matches(pattern, text, replace)


def _replace_matches(
    pattern: re.Pattern[str],
    text: str,
    replace: Callable[[re.Match[str]], str],
) -> str:
    parts: list[str] = []
    position = 0
    for match in pattern.finditer(text):
        if match.start() < position:
            continue
        end = _extended_match_end(match, text)
        parts.append(text[position : match.start()])
        parts.append(replace(match))
        position = end
    parts.append(text[position:])
    return "".join(parts)


def _extend_spaced_path_suffix(match: re.Match[str], text: str) -> str:
    return text[match.start() : _extended_match_end(match, text)]


def _extended_match_end(match: re.Match[str], text: str) -> int:
    if not _is_extensionless_path_directory_match(match):
        return match.end()

    tokens = _following_words(text, match.end())
    if not tokens:
        return match.end()

    boundary_index = _boundary_token_index(tokens)
    if boundary_index is not None:
        return tokens[boundary_index - 1][1] if boundary_index > 0 else match.end()

    prefix_tail_end = _local_prefix_tail_end(match, tokens)
    if prefix_tail_end is not None:
        return prefix_tail_end

    local_tail_index = _local_tail_noun_index(match, tokens)
    if local_tail_index is not None:
        return tokens[local_tail_index][1]

    if _tokens_reach_query_end(tokens, text) and _looks_like_path_tail_at_end(tokens):
        return tokens[-1][1]

    return match.end()


def _is_extensionless_path_directory_match(match: re.Match[str]) -> bool:
    final_component = _final_path_component(match.group(0))
    return "." not in final_component


def _following_words(text: str, start: int) -> list[tuple[str, int]]:
    words: list[tuple[str, int]] = []
    position = start
    while True:
        match = re.match(
            r"\s+([A-Za-z][A-Za-z0-9_-]*)(?:/[^\s,;:!?)]*)?",
            text[position:],
        )
        if match is None:
            return words
        position += len(match.group(0))
        words.append((match.group(1), position))


def _boundary_token_index(tokens: list[tuple[str, int]]) -> int | None:
    for index, (word, _end) in enumerate(tokens):
        if word.lower() in _PATH_BOUNDARY_PREPOSITIONS:
            return index
    return None


def _local_tail_noun_index(
    match: re.Match[str],
    tokens: list[tuple[str, int]],
) -> int | None:
    for index, (word, _end) in enumerate(tokens):
        if word.lower() in _LOCAL_TAIL_NOUNS and (
            index > 0 or _final_component_is_local_tail_prefix(match)
        ):
            return index
    return None


def _local_prefix_tail_end(
    match: re.Match[str],
    tokens: list[tuple[str, int]],
) -> int | None:
    if not _final_component_is_local_tail_prefix(match):
        return None

    consumed: list[tuple[str, int]] = []
    for word, end in tokens[:3]:
        normalized = word.lower()
        if normalized in _LOCAL_TAIL_PREFIXES:
            consumed.append((word, end))
            continue
        if normalized in _LOCAL_TAIL_NOUNS:
            return end
        consumed.append((word, end))
        break

    if len(consumed) >= 2:
        return consumed[-1][1]
    return None


def _final_component_is_local_tail_prefix(match: re.Match[str]) -> bool:
    final_component = _final_path_component(match.group(0))
    return final_component.lower() in _LOCAL_TAIL_PREFIXES


def _final_path_component(path: str) -> str:
    return re.split(r"[\\/]+", path.rstrip(".,;:!?"))[-1]


def _tokens_reach_query_end(tokens: list[tuple[str, int]], text: str) -> bool:
    return not text[tokens[-1][1] :].strip()


def _looks_like_path_tail_at_end(tokens: list[tuple[str, int]]) -> bool:
    words = [word for word, _end in tokens]
    if all(word[:1].isupper() for word in words):
        return True
    return words[-1].lower() in _LOCAL_TAIL_NOUNS


def _is_model_path(value: str) -> bool:
    normalized = value.lower()
    return (
        "\\models\\" in normalized
        or "/models/" in normalized
        or normalized.endswith((".gguf", ".safetensors", ".onnx", ".bin", ".pt"))
    )


def _extract_project_names(text: str) -> set[str]:
    names: set[str] = set()
    for pattern in (_WINDOWS_PATH_RE, _POSIX_PATH_RE):
        for match in pattern.finditer(text):
            for component in re.split(r"[\\/]+", match.group(0)):
                cleaned = re.sub(r"\.[A-Za-z0-9._-]+$", "", component)
                for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", cleaned):
                    lowered = word.lower()
                    if lowered not in _COMMON_LOCAL_COMPONENTS:
                        names.add(word)
    return names


def _redact_project_names(text: str, names: set[str], categories: list[str]) -> str:
    redacted = text
    for name in sorted(names, key=len, reverse=True):
        redacted, count = re.subn(
            rf"\b((?:in|inside|within|from|for)\s+){re.escape(name)}(?=\s*[,;:])",
            rf"\1{_LOCAL_PATH_LABEL}",
            redacted,
            flags=re.IGNORECASE,
        )
        if count:
            _add_category(categories, "LOCAL_PATH")
    return redacted


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _block_reason(sanitized: str) -> str | None:
    if not sanitized:
        return "Query is empty after privacy sanitization."

    without_labels = _REDACTION_LABEL_RE.sub(" ", sanitized)
    meaningful_tokens = [
        token
        for token in _MEANINGFUL_TOKEN_RE.findall(without_labels)
        if _is_meaningful_query_token(token)
    ]
    if not meaningful_tokens:
        return "Query contains too little non-sensitive content for web search."
    return None


def _is_meaningful_query_token(token: str) -> bool:
    if len(token) <= 1 and not re.search(r"[\u4e00-\u9fff]", token):
        return False
    return token.lower() not in _COMMAND_ONLY_TOKENS


def _add_category(categories: list[str], category: str) -> None:
    if category not in categories:
        categories.append(category)
