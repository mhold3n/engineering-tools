"""Tests for project initialization and registry."""

from __future__ import annotations

import json
from pathlib import Path

from engineering_tools.project import init_project
from engineering_tools.registry import list_projects, load_registry, registry_path


def test_init_project_creates_layout(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "etools-home"
    monkeypatch.setenv("ETOOLS_HOME", str(home))

    root = tmp_path / "my-part"
    result = init_project(root, name="My Part")

    assert result == root.resolve()
    assert (root / "jobs").is_dir()
    assert (root / "artifacts").is_dir()
    assert (root / ".engineering-tools").is_dir()
    assert (root / "README.md").is_file()
    assert (root / "ATTRIBUTION.md").is_file()

    marker = root / ".engineering-tools.json"
    assert marker.is_file()
    data = json.loads(marker.read_text(encoding="utf-8"))
    assert data["name"] == "My Part"
    assert data["version"] == 1
    assert "jobs" in data["layout"]
    assert "artifacts" in data["layout"]


def test_init_project_idempotent_readme(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "etools-home"))
    root = tmp_path / "proj"
    init_project(root)
    readme = root / "README.md"
    readme.write_text("custom\n", encoding="utf-8")
    init_project(root)
    assert readme.read_text(encoding="utf-8") == "custom\n"


def test_init_registers_project_no_duplicates(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "etools-home"
    monkeypatch.setenv("ETOOLS_HOME", str(home))

    root = tmp_path / "part-a"
    init_project(root, name="Part A")
    init_project(root, name="Part A Renamed")

    data = load_registry()
    assert registry_path().is_file()
    assert registry_path().is_relative_to(home.resolve())
    projects = data["projects"]
    assert len(projects) == 1
    assert projects[0]["name"] == "Part A Renamed"
    assert Path(projects[0]["path"]).resolve() == root.resolve()
    assert "created" in projects[0]
    assert "updated" in projects[0]

    listed = list_projects()
    assert len(listed) == 1
