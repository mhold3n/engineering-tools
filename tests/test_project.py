"""Tests for project initialization."""

from __future__ import annotations

import json
from pathlib import Path

from engineering_tools.project import init_project


def test_init_project_creates_layout(tmp_path: Path) -> None:
    root = tmp_path / "my-part"
    result = init_project(root, name="My Part")

    assert result == root.resolve()
    assert (root / "jobs").is_dir()
    assert (root / "artifacts").is_dir()
    assert (root / "README.md").is_file()
    assert (root / "ATTRIBUTION.md").is_file()

    marker = root / ".engineering-tools.json"
    assert marker.is_file()
    data = json.loads(marker.read_text(encoding="utf-8"))
    assert data["name"] == "My Part"
    assert data["version"] == 1
    assert "jobs" in data["layout"]
    assert "artifacts" in data["layout"]


def test_init_project_idempotent_readme(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    init_project(root)
    readme = root / "README.md"
    readme.write_text("custom\n", encoding="utf-8")
    init_project(root)
    assert readme.read_text(encoding="utf-8") == "custom\n"
