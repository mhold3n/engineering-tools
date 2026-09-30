"""Tests for the OpenFOAM cavity probe: blockMesh then a short icoFoam solve."""

from __future__ import annotations

import os
from pathlib import Path

from engineering_tools.hello_probes import probe_openfoam


def executable(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _mesh_and_solve(binary_dir: Path) -> None:
    executable(
        binary_dir / "blockMesh",
        "mkdir -p constant/polyMesh\nprintf points > constant/polyMesh/points\n",
    )
    executable(
        binary_dir / "icoFoam",
        "mkdir -p 0.1\nprintf 'internalField uniform (0 0 0);\\n' > 0.1/U\n",
    )


def test_openfoam_probe_runs_mesh_then_ico_foam(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    _mesh_and_solve(binary_dir)
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    result = probe_openfoam(project=tmp_path / "project")
    assert result["status"] == "ok"
    assert result["locator"].endswith("icoFoam")
    assert any(path.endswith("0.1/U") for path in result["outputs"])


def test_openfoam_probe_falls_back_to_foam_exec(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(
        binary_dir / "foamExec",
        """
case "$1" in
  blockMesh)
    mkdir -p constant/polyMesh
    touch constant/polyMesh/points
    ;;
  icoFoam)
    mkdir -p 0.1
    printf 'internalField\\n' > 0.1/U
    ;;
  *) exit 9 ;;
esac
""",
    )
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    result = probe_openfoam()
    assert result["status"] == "ok"
    assert "foamExec icoFoam" in result["locator"]


def test_openfoam_probe_requires_mesh_artifact(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(binary_dir / "blockMesh", "exit 0\n")
    executable(binary_dir / "icoFoam", "exit 0\n")
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    result = probe_openfoam()
    assert result["status"] == "broken"
    assert "constant/polyMesh/points" in result["message"]


def test_openfoam_probe_requires_velocity_field(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(binary_dir / "blockMesh", "mkdir -p constant/polyMesh\ntouch constant/polyMesh/points\n")
    executable(binary_dir / "icoFoam", "exit 0\n")
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    result = probe_openfoam()
    assert result["status"] == "broken"
    assert "velocity field" in result["message"]


def test_openfoam_probe_missing_is_typed(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/nonexistent-etools-path")
    result = probe_openfoam()
    assert result["status"] == "missing"
    assert result["outputs"] == []
