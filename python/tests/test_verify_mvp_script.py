from pathlib import Path


def test_verify_mvp_script_fails_on_native_command_errors() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = (repo_root / "scripts" / "verify-mvp.ps1").read_text(encoding="utf-8")

    helper_start = script.index("function Invoke-CheckedCommand")
    helper_end = script.index("$repoRoot = Resolve-Path", helper_start)
    helper_body = script[helper_start:helper_end]

    assert "$LASTEXITCODE" in helper_body
    assert "throw" in helper_body
