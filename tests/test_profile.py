"""Tests for tool detection / profile summary."""

from __future__ import annotations

from pathlib import Path

from engineering_tools.profile import (
    BASE_PROFILE,
    detect_profile,
    detect_tool,
    summarize_profile,
)


def test_detect_with_fake_ccx(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ccx = fake_bin / "ccx"
    ccx.write_text("#!/bin/sh\necho fake-ccx\n", encoding="utf-8")
    ccx.chmod(0o755)

    path_env = str(fake_bin)
    detected = detect_profile(path_env=path_env)
    by_name = {d.name: d for d in detected}

    assert by_name["CalculiX"].found is True
    assert by_name["CalculiX"].binary == "ccx"
    assert by_name["CalculiX"].path == str(ccx)
    assert by_name["FreeCAD"].found is False
    assert by_name["Gmsh"].found is False

    summary = summarize_profile(detected)
    assert summary["found_count"] == 1
    assert summary["found"] == ["CalculiX"]
    assert summary["missing_count"] == len(BASE_PROFILE) - 1
    assert "CalculiX" not in summary["missing"]


def test_detect_missing_tools_empty_path() -> None:
    detected = detect_profile(path_env="")
    assert all(not d.found for d in detected)
    summary = summarize_profile(detected)
    assert summary["found_count"] == 0
    assert summary["missing_count"] == len(BASE_PROFILE)
    assert summary["total"] == len(BASE_PROFILE)


def test_detect_tool_single(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gmsh = fake_bin / "gmsh"
    gmsh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    gmsh.chmod(0o755)

    spec = next(s for s in BASE_PROFILE if s.name == "Gmsh")
    result = detect_tool(spec, path_env=str(fake_bin))
    assert result.found is True
    assert result.binary == "gmsh"
