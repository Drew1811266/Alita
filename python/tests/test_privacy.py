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
