from __future__ import annotations

from pathlib import Path

from agent_service.sandbox import SandboxRequest, run_sandboxed_python


def test_sandbox_reads_allowed_project_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = project / "data.csv"
    source.write_text("a,b\n1,2\n", encoding="utf-8")
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    result = run_sandboxed_python(
        SandboxRequest(
            script=(
                "import json, sys\n"
                "payload=json.load(sys.stdin)\n"
                "text=open(payload['path'], encoding='utf-8').read()\n"
                "print(json.dumps({'values': {'rows': len(text.splitlines())}}))\n"
            ),
            arguments={"path": str(source)},
            project_path=str(project / "project.alita"),
            allowed_roots=[str(project)],
            artifact_dir=str(artifact_dir),
        )
    )

    assert result.ok is True
    assert result.values == {"rows": 2}


def test_sandbox_rejects_network_import_when_network_denied(tmp_path: Path) -> None:
    result = run_sandboxed_python(
        SandboxRequest(
            script="import socket\nprint('{}')\n",
            project_path=str(tmp_path / "project.alita"),
            allowed_roots=[str(tmp_path)],
            artifact_dir=str(tmp_path / "artifacts"),
        )
    )

    assert result.ok is False
    assert result.error_code == "network_import_denied"


def test_sandbox_rejects_artifact_outside_artifact_dir(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    outside = tmp_path / "outside.txt"

    result = run_sandboxed_python(
        SandboxRequest(
            script=(
                "import json\n"
                f"print(json.dumps({{'artifacts': [r'{outside}']}}))\n"
            ),
            project_path=str(tmp_path / "project.alita"),
            allowed_roots=[str(tmp_path)],
            artifact_dir=str(artifact_dir),
        )
    )

    assert result.ok is False
    assert result.error_code == "artifact_path_not_allowed"
