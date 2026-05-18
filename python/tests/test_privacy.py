from __future__ import annotations

from agent_service.privacy import PrivacyGuardResult, sanitize_for_web_search


def test_redacts_windows_paths_and_adjacent_project_name_but_keeps_public_intent() -> None:
    local_path = r"D:\Software Project\Alita\src\app\App.tsx"
    user_path = r"C:\Users\Drew\Projects\Alita\python\agent_service\graph.py"
    text = (
        f"In Alita, compare LangGraph routing docs with code in {local_path} "
        f"and {user_path}."
    )

    result = sanitize_for_web_search(text)

    assert result == PrivacyGuardResult(
        sanitizedText=(
            "In [LOCAL_PATH], compare LangGraph routing docs with code in "
            "[LOCAL_PATH] and [LOCAL_PATH]."
        ),
        removedCategories=["LOCAL_PATH"],
        blocked=False,
        reason=None,
    )
    assert "Alita" not in result.sanitizedText
    assert local_path not in result.sanitizedText
    assert user_path not in result.sanitizedText


def test_redacts_posix_paths() -> None:
    local_path = "/home/drew/Alita/python/agent_service/graph.py"

    result = sanitize_for_web_search(
        f"Search current LangGraph conditional edge behavior for {local_path}"
    )

    assert "[LOCAL_PATH]" in result.sanitizedText
    assert local_path not in result.sanitizedText
    assert "LangGraph conditional edge behavior" in result.sanitizedText
    assert result.removedCategories == ["LOCAL_PATH"]
    assert result.blocked is False


def test_preserves_https_urls_without_marking_them_as_local_paths() -> None:
    url = "https://docs.python.org/3/library/pathlib.html"

    result = sanitize_for_web_search(
        f"Search {url} for PurePath examples"
    )

    assert result.sanitizedText == f"Search {url} for PurePath examples"
    assert result.removedCategories == []
    assert result.blocked is False


def test_redacts_windows_path_with_spaced_filename() -> None:
    local_path = r"C:\Users\Drew\Projects\Alita\my file.txt"

    result = sanitize_for_web_search(
        f"Search errors in {local_path} about LangGraph"
    )

    assert result.sanitizedText == "Search errors in [LOCAL_PATH] about LangGraph"
    assert local_path not in result.sanitizedText
    assert "my" not in result.sanitizedText
    assert "file.txt" not in result.sanitizedText
    assert result.removedCategories == ["LOCAL_PATH"]
    assert result.blocked is False


def test_redacts_windows_directory_path_without_file_extension() -> None:
    local_path = r"C:\Users\Drew\Projects\Alita"

    result = sanitize_for_web_search(f"Search issues in {local_path} about LangGraph")

    assert result.sanitizedText == "Search issues in [LOCAL_PATH] about LangGraph"
    assert local_path not in result.sanitizedText
    assert "Alita" not in result.sanitizedText
    assert result.removedCategories == ["LOCAL_PATH"]
    assert result.blocked is False


def test_preserves_public_terms_after_windows_directory_path() -> None:
    local_path = r"C:\Users\Drew\Projects\Alita"

    result = sanitize_for_web_search(f"Search {local_path} LangGraph routing docs")

    assert result.sanitizedText == "Search [LOCAL_PATH] LangGraph routing docs"
    assert local_path not in result.sanitizedText
    assert "LangGraph routing docs" in result.sanitizedText
    assert result.removedCategories == ["LOCAL_PATH"]
    assert result.blocked is False


def test_preserves_latest_usage_query_after_windows_directory_path() -> None:
    local_path = r"C:\Users\Drew\Projects\Alita"

    result = sanitize_for_web_search(f"Search {local_path} latest official usage")

    assert result.sanitizedText == "Search [LOCAL_PATH] latest official usage"
    assert local_path not in result.sanitizedText
    assert "latest official usage" in result.sanitizedText
    assert result.removedCategories == ["LOCAL_PATH"]
    assert result.blocked is False


def test_redacts_windows_directory_path_with_spaced_final_segment() -> None:
    local_path = r"C:\Users\Drew\My Project"

    result = sanitize_for_web_search(f"Search issues in {local_path} about LangGraph")

    assert result.sanitizedText == "Search issues in [LOCAL_PATH] about LangGraph"
    assert local_path not in result.sanitizedText
    assert "Project" not in result.sanitizedText
    assert result.removedCategories == ["LOCAL_PATH"]
    assert result.blocked is False


def test_redacts_arbitrary_spaced_windows_directory_before_preposition() -> None:
    local_path = r"C:\Users\Drew\Secret Folder"

    result = sanitize_for_web_search(f"Search issues in {local_path} about LangGraph")

    assert result.sanitizedText == "Search issues in [LOCAL_PATH] about LangGraph"
    assert local_path not in result.sanitizedText
    assert "Folder" not in result.sanitizedText
    assert "about LangGraph" in result.sanitizedText
    assert result.removedCategories == ["LOCAL_PATH"]
    assert result.blocked is False


def test_redacts_arbitrary_spaced_windows_directory_before_for_phrase() -> None:
    local_path = r"C:\Users\Drew\Private Repo"

    result = sanitize_for_web_search(f"Search issues in {local_path} for LangGraph docs")

    assert result.sanitizedText == "Search issues in [LOCAL_PATH] for LangGraph docs"
    assert local_path not in result.sanitizedText
    assert "Repo" not in result.sanitizedText
    assert "for LangGraph docs" in result.sanitizedText
    assert result.removedCategories == ["LOCAL_PATH"]
    assert result.blocked is False


def test_redacts_spaced_windows_directory_before_latest_usage_query() -> None:
    local_path = r"C:\Users\Drew\Private Repo"

    result = sanitize_for_web_search(f"Search {local_path} latest official usage")

    assert result.sanitizedText == "Search [LOCAL_PATH] latest official usage"
    assert local_path not in result.sanitizedText
    assert "Repo" not in result.sanitizedText
    assert "latest official usage" in result.sanitizedText
    assert result.removedCategories == ["LOCAL_PATH"]
    assert result.blocked is False


def test_redacts_multiword_windows_directory_before_preposition() -> None:
    local_path = r"C:\Users\Drew\Very Secret Folder"

    result = sanitize_for_web_search(f"Search issues in {local_path} about LangGraph")

    assert result.sanitizedText == "Search issues in [LOCAL_PATH] about LangGraph"
    assert local_path not in result.sanitizedText
    assert "Very" not in result.sanitizedText
    assert "Secret" not in result.sanitizedText
    assert "Folder" not in result.sanitizedText
    assert "about LangGraph" in result.sanitizedText
    assert result.removedCategories == ["LOCAL_PATH"]
    assert result.blocked is False


def test_redacts_multiword_windows_directory_at_end_of_query() -> None:
    local_path = r"C:\Users\Drew\Very Secret Folder"

    result = sanitize_for_web_search(f"Search issues in {local_path}")

    assert result.sanitizedText == "Search issues in [LOCAL_PATH]"
    assert local_path not in result.sanitizedText
    assert "Very" not in result.sanitizedText
    assert "Secret" not in result.sanitizedText
    assert "Folder" not in result.sanitizedText
    assert result.removedCategories == ["LOCAL_PATH"]
    assert result.blocked is False


def test_redacts_lowercase_multiword_windows_directory_before_latest_usage_query() -> None:
    local_path = r"C:\Users\Drew\very secret folder"

    result = sanitize_for_web_search(f"Search {local_path} latest official usage")

    assert result.sanitizedText == "Search [LOCAL_PATH] latest official usage"
    assert local_path not in result.sanitizedText
    assert "secret" not in result.sanitizedText
    assert "folder" not in result.sanitizedText
    assert "latest official usage" in result.sanitizedText
    assert result.removedCategories == ["LOCAL_PATH"]
    assert result.blocked is False


def test_redacts_model_paths_and_model_filenames() -> None:
    model_path = r"C:\models\qwen\qwen2.5-coder.gguf"
    model_name = "Qwen3-ASR-1.7B"

    result = sanitize_for_web_search(
        f"Find public benchmark notes for {model_path} and {model_name}"
    )

    assert result.sanitizedText == (
        "Find public benchmark notes for [MODEL_PATH] and [MODEL_PATH]"
    )
    assert model_path not in result.sanitizedText
    assert model_name not in result.sanitizedText
    assert result.removedCategories == ["MODEL_PATH"]
    assert result.blocked is False


def test_redacts_model_path_with_spaced_filename() -> None:
    model_path = r"C:\models\qwen\my model.gguf"

    result = sanitize_for_web_search(f"Find benchmark for {model_path}")

    assert result.sanitizedText == "Find benchmark for [MODEL_PATH]"
    assert model_path not in result.sanitizedText
    assert "my" not in result.sanitizedText
    assert "model.gguf" not in result.sanitizedText
    assert result.removedCategories == ["MODEL_PATH"]
    assert result.blocked is False


def test_redacts_model_directory_path_without_model_file_extension() -> None:
    model_path = r"C:\models\qwen"

    result = sanitize_for_web_search(
        f"Find setup notes for {model_path} and Qwen benchmarks"
    )

    assert result.sanitizedText == (
        "Find setup notes for [MODEL_PATH] and [MODEL_PATH] benchmarks"
    )
    assert model_path not in result.sanitizedText
    assert r"C:\models" not in result.sanitizedText
    assert result.removedCategories == ["MODEL_PATH"]
    assert result.blocked is False


def test_preserves_latest_usage_query_after_model_directory_path() -> None:
    model_path = r"C:\models\qwen"

    result = sanitize_for_web_search(f"Search {model_path} latest official usage")

    assert result.sanitizedText == "Search [MODEL_PATH] latest official usage"
    assert model_path not in result.sanitizedText
    assert "latest official usage" in result.sanitizedText
    assert result.removedCategories == ["MODEL_PATH"]
    assert result.blocked is False


def test_redacts_model_directory_path_with_spaced_final_segment() -> None:
    model_path = r"C:\models\my model"

    result = sanitize_for_web_search(f"Find setup notes for {model_path}")

    assert result.sanitizedText == "Find setup notes for [MODEL_PATH]"
    assert model_path not in result.sanitizedText
    assert "model" not in result.sanitizedText
    assert result.removedCategories == ["MODEL_PATH"]
    assert result.blocked is False


def test_redacts_multiword_model_directory_before_preposition() -> None:
    model_path = r"C:\models\very secret model"

    result = sanitize_for_web_search(f"Find setup notes for {model_path} about Qwen")

    assert result.sanitizedText == "Find setup notes for [MODEL_PATH] about [MODEL_PATH]"
    assert model_path not in result.sanitizedText
    assert "very" not in result.sanitizedText
    assert "secret" not in result.sanitizedText
    assert "model" not in result.sanitizedText
    assert result.removedCategories == ["MODEL_PATH"]
    assert result.blocked is False


def test_redacts_multiline_file_like_pasted_content() -> None:
    pasted_content = """Here is the traceback:
Traceback (most recent call last):
  File "D:\\Software Project\\Alita\\python\\agent_service\\graph.py", line 42, in route
    return state["missing"]
KeyError: 'missing'
def route(state):
    if state.get("requires_web"):
        return "web"
"""

    result = sanitize_for_web_search(
        f"Search public LangGraph KeyError troubleshooting.\n{pasted_content}"
    )

    assert "[LOCAL_FILE_CONTENT]" in result.sanitizedText
    assert "Traceback" not in result.sanitizedText
    assert "return state" not in result.sanitizedText
    assert "agent_service" not in result.sanitizedText
    assert "LangGraph KeyError troubleshooting" in result.sanitizedText
    assert set(result.removedCategories) == {"LOCAL_FILE_CONTENT"}
    assert result.blocked is False


def test_redacts_multiline_python_code_paste_after_public_intent() -> None:
    pasted_content = """Search public Python import error
import os
from pathlib import Path
print(Path.cwd())"""

    result = sanitize_for_web_search(pasted_content)

    assert result.sanitizedText == (
        "Search public Python import error [LOCAL_FILE_CONTENT]"
    )
    assert "import os" not in result.sanitizedText
    assert "from pathlib" not in result.sanitizedText
    assert "print(" not in result.sanitizedText
    assert result.removedCategories == ["LOCAL_FILE_CONTENT"]
    assert result.blocked is False


def test_redacts_timestamp_prefixed_log_block_after_public_intent() -> None:
    pasted_content = """Search public HTTP 500 cause
2026-05-18 10:00:01 ERROR request failed
2026-05-18 10:00:02 INFO retrying"""

    result = sanitize_for_web_search(pasted_content)

    assert result.sanitizedText == "Search public HTTP 500 cause [LOCAL_FILE_CONTENT]"
    assert "2026-05-18" not in result.sanitizedText
    assert "request failed" not in result.sanitizedText
    assert "retrying" not in result.sanitizedText
    assert result.removedCategories == ["LOCAL_FILE_CONTENT"]
    assert result.blocked is False


def test_redacts_emails_and_obvious_tokens_without_leaking_reason() -> None:
    email = "drew@example.com"
    openai_token = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
    github_token = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"

    result = sanitize_for_web_search(
        f"Search docs for auth failures from {email} using {openai_token} and {github_token}"
    )

    assert result.sanitizedText == (
        "Search docs for auth failures from [EMAIL] using [SECRET] and [SECRET]"
    )
    assert email not in result.sanitizedText
    assert openai_token not in result.sanitizedText
    assert github_token not in result.sanitizedText
    assert result.removedCategories == ["EMAIL", "SECRET"]
    assert result.blocked is False
    assert result.reason is None


def test_sanitizes_chinese_query_mixing_local_and_public_terms() -> None:
    path = r"C:\Users\Drew\Projects\Alita\python\agent_service\graph.py"

    result = sanitize_for_web_search(
        f"请搜索 {path} 里提到的 LangGraph intent routing 最新官方用法"
    )

    assert result.sanitizedText == (
        "请搜索 [LOCAL_PATH] 里提到的 LangGraph intent routing 最新官方用法"
    )
    assert path not in result.sanitizedText
    assert "LangGraph intent routing 最新官方用法" in result.sanitizedText
    assert result.removedCategories == ["LOCAL_PATH"]
    assert result.blocked is False


def test_blocks_when_sanitization_leaves_too_little_meaningful_content() -> None:
    secret = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
    path = r"C:\Users\Drew\Projects\Alita\python\agent_service\graph.py"

    result = sanitize_for_web_search(f"{path}\n{secret}\ndrew@example.com")

    assert result.sanitizedText == "[LOCAL_PATH] [SECRET] [EMAIL]"
    assert set(result.removedCategories) == {"LOCAL_PATH", "SECRET", "EMAIL"}
    assert result.blocked is True
    assert result.reason == "Query contains too little non-sensitive content for web search."
    assert path not in result.reason
    assert secret not in result.reason
    assert "drew@example.com" not in result.reason


def test_blocks_empty_input_and_only_redaction_labels() -> None:
    empty = sanitize_for_web_search("")
    labels_only = sanitize_for_web_search("[LOCAL_PATH] [SECRET]")

    assert empty.blocked is True
    assert empty.sanitizedText == ""
    assert empty.removedCategories == []
    assert empty.reason == "Query is empty after privacy sanitization."

    assert labels_only.blocked is True
    assert labels_only.sanitizedText == "[LOCAL_PATH] [SECRET]"
    assert labels_only.removedCategories == []
    assert labels_only.reason == "Query contains too little non-sensitive content for web search."
