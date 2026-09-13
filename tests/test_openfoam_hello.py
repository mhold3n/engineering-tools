"""Tests for normalized OpenFOAM blockMesh probe."""

from __future__ import annotations

import os
from pathlib import Path

from engineering_tools.hello_probes import probe_openfoam


def executable(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


def test_openfoam_probe_runs_direct_block_mesh(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(
        binary_dir / "blockMesh",
        "mkdir -p constant/polyMesh\nprintf points > constant/polyMesh/points\n",
    )
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    result = probe_openfoam(project=tmp_path / "project")
    assert result["status"] == "ok"
    assert result["locator"].endswith("blockMesh")
    assert any(path.endswith("constant/polyMesh/points") for path in result["outputs"])


def test_openfoam_probe_falls_back_to_foam_exec(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(
        binary_dir / "foamExec",
        'test "$1" = blockMesh || exit 9\nmkdir -p constant/polyMesh\ntouch constant/polyMesh/points\n',
    )
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    result = probe_openfoam()
    assert result["status"] == "ok"
    assert "foamExec" in result["locator"]


def test_openfoam_probe_requires_mesh_artifact(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(binary_dir / "blockMesh", "exit 0\n")
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    result = probe_openfoam()
    assert result["status"] == "broken"
    assert "constant/polyMesh/points" in result["message"]


def test_openfoam_probe_missing_is_typed(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/nonexistent-etools-path")
    result = probe_openfoam()
    assert result["status"] == "missing"
    assert result["outputs"] == []
