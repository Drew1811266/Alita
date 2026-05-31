from __future__ import annotations

from pathlib import Path

from agent_service.sandbox import (
    SandboxRequest,
    job_object_backend_available,
    run_sandboxed_python,
)


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
    assert result.security_model == "constrained_subprocess_runner"
    assert (
        result.security_boundary
        == "preflight_and_runtime_limits_not_os_isolation"
    )
    assert result.backend == "subprocess"
    assert result.is_os_isolated is False
    assert result.is_process_tree_limited is False
    assert result.backend_capabilities == {
        "windows_job_object_available": job_object_backend_available(),
        "process_tree_limited": False,
        "os_isolated": False,
    }


def test_sandbox_job_object_probe_is_windows_only() -> None:
    import os

    assert job_object_backend_available() is (os.name == "nt")


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


def test_sandbox_rejects_dynamic_network_import_when_network_denied(
    tmp_path: Path,
) -> None:
    result = run_sandboxed_python(
        SandboxRequest(
            script="__import__('socket')\nprint('{}')\n",
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


def test_sandbox_times_out_long_running_script(tmp_path: Path) -> None:
    result = run_sandboxed_python(
        SandboxRequest(
            script="import time\ntime.sleep(2)\nprint('{}')\n",
            project_path=str(tmp_path / "project.alita"),
            allowed_roots=[str(tmp_path)],
            artifact_dir=str(tmp_path / "artifacts"),
            timeout_seconds=0.1,
        )
    )

    assert result.ok is False
    assert result.error_code == "timeout"


def test_sandbox_rejects_project_path_escape_argument(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    result = run_sandboxed_python(
        SandboxRequest(
            script=(
                "import json, sys\n"
                "payload=json.load(sys.stdin)\n"
                "open(payload['path']).read()\n"
                "print(json.dumps({'values': {'ok': True}}))\n"
            ),
            arguments={"path": str(outside)},
            project_path=str(project / "project.alita"),
            allowed_roots=[str(project)],
            artifact_dir=str(tmp_path / "artifacts"),
        )
    )

    assert result.ok is False
    assert result.error_code == "path_not_allowed"


def test_sandbox_rejects_script_over_max_bytes(tmp_path: Path) -> None:
    result = run_sandboxed_python(
        SandboxRequest(
            script="# " + ("x" * 128),
            project_path=str(tmp_path / "project.alita"),
            allowed_roots=[str(tmp_path)],
            artifact_dir=str(tmp_path / "artifacts"),
            max_script_bytes=32,
        )
    )

    assert result.ok is False
    assert result.error_code == "script_too_large"


def test_sandbox_rejects_stdout_over_max_bytes(tmp_path: Path) -> None:
    result = run_sandboxed_python(
        SandboxRequest(
            script="print('x' * 128)\n",
            project_path=str(tmp_path / "project.alita"),
            allowed_roots=[str(tmp_path)],
            artifact_dir=str(tmp_path / "artifacts"),
            max_output_bytes=32,
        )
    )

    assert result.ok is False
    assert result.error_code == "output_too_large"


def test_sandbox_rejects_too_many_artifacts(tmp_path: Path) -> None:
    result = run_sandboxed_python(
        SandboxRequest(
            script=(
                "import json\n"
                "print(json.dumps({'artifacts': ['a.txt', 'b.txt']}))\n"
            ),
            project_path=str(tmp_path / "project.alita"),
            allowed_roots=[str(tmp_path)],
            artifact_dir=str(tmp_path / "artifacts"),
            max_artifacts=1,
        )
    )

    assert result.ok is False
    assert result.error_code == "too_many_artifacts"


def test_sandbox_rejects_artifact_over_max_bytes(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    output = artifact_dir / "large.txt"

    result = run_sandboxed_python(
        SandboxRequest(
            script=(
                "import json, sys\n"
                "payload=json.load(sys.stdin)\n"
                "open(payload['artifact'], 'w', encoding='utf-8').write('x' * 128)\n"
                "print(json.dumps({'artifacts': [payload['artifact']]}))\n"
            ),
            arguments={"artifact": str(output)},
            project_path=str(tmp_path / "project.alita"),
            allowed_roots=[str(tmp_path), str(artifact_dir)],
            artifact_dir=str(artifact_dir),
            max_artifact_bytes=32,
        )
    )

    assert result.ok is False
    assert result.error_code == "artifact_too_large"


def test_sandbox_rejects_direct_file_api_outside_allowed_roots(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    result = run_sandboxed_python(
        SandboxRequest(
            script=(
                f"open(r'{outside}', encoding='utf-8').read()\n"
                "print('{}')\n"
            ),
            project_path=str(project / "project.alita"),
            allowed_roots=[str(project)],
            artifact_dir=str(tmp_path / "artifacts"),
        )
    )

    assert result.ok is False
    assert result.error_code == "forbidden_file_api"


def test_sandbox_rejects_path_read_text_outside_allowed_roots(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    result = run_sandboxed_python(
        SandboxRequest(
            script=(
                "from pathlib import Path\n"
                f"Path(r'{outside}').read_text(encoding='utf-8')\n"
                "print('{}')\n"
            ),
            project_path=str(project / "project.alita"),
            allowed_roots=[str(project)],
            artifact_dir=str(tmp_path / "artifacts"),
        )
    )

    assert result.ok is False
    assert result.error_code == "forbidden_file_api"


def test_sandbox_rejects_path_write_text_outside_artifact_dir(tmp_path: Path) -> None:
    project = tmp_path / "project"
    artifact_dir = tmp_path / "artifacts"
    outside_artifact = tmp_path / "outside.txt"
    project.mkdir()
    artifact_dir.mkdir()

    result = run_sandboxed_python(
        SandboxRequest(
            script=(
                "from pathlib import Path\n"
                f"Path(r'{outside_artifact}').write_text('escape', encoding='utf-8')\n"
                "print('{}')\n"
            ),
            project_path=str(project / "project.alita"),
            allowed_roots=[str(project), str(tmp_path)],
            artifact_dir=str(artifact_dir),
        )
    )

    assert result.ok is False
    assert result.error_code == "forbidden_file_api"


def test_sandbox_rejects_socket_call_when_network_is_not_allowed(
    tmp_path: Path,
) -> None:
    result = run_sandboxed_python(
        SandboxRequest(
            script="socket.socket()\nprint('{}')\n",
            project_path=str(tmp_path / "project.alita"),
            allowed_roots=[str(tmp_path)],
            artifact_dir=str(tmp_path / "artifacts"),
        )
    )

    assert result.ok is False
    assert result.error_code == "network_call_denied"


def test_sandbox_rejects_secret_environment_access(tmp_path: Path) -> None:
    result = run_sandboxed_python(
        SandboxRequest(
            script="import os\nos.getenv('OPENAI_API_KEY')\nprint('{}')\n",
            project_path=str(tmp_path / "project.alita"),
            allowed_roots=[str(tmp_path)],
            artifact_dir=str(tmp_path / "artifacts"),
        )
    )

    assert result.ok is False
    assert result.error_code == "secret_env_denied"


def test_sandbox_rejects_process_launch_api(tmp_path: Path) -> None:
    result = run_sandboxed_python(
        SandboxRequest(
            script="import os\nos.system('echo hi')\nprint('{}')\n",
            project_path=str(tmp_path / "project.alita"),
            allowed_roots=[str(tmp_path)],
            artifact_dir=str(tmp_path / "artifacts"),
        )
    )

    assert result.ok is False
    assert result.error_code == "process_launch_denied"
