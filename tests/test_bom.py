"""Tests for BOM-lite."""

from __future__ import annotations

import json
from pathlib import Path

from engineering_tools.bom import add_item, bom_path, list_items, load_bom, remove_item
from engineering_tools.cli import main
from engineering_tools.project import init_project


def test_init_creates_empty_bom(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "etools-home"))
    project = tmp_path / "part"
    init_project(project, name="Part")
    path = bom_path(project)
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["items"] == []


def test_bom_add_list_remove(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "etools-home"))
    project = tmp_path / "bom-proj"
    init_project(project)

    item = add_item(
        project,
        part="Bracket",
        qty=2,
        unit="ea",
        material="AL6061",
        source="McMaster",
        notes="left/right",
    )
    assert item["id"]
    assert item["part"] == "Bracket"
    assert item["qty"] == 2
    assert item["material"] == "AL6061"
    assert "updated" in item

    items = list_items(project)
    assert len(items) == 1
    assert items[0]["id"] == item["id"]

    data = load_bom(project)
    assert data["version"] == 1
    assert len(data["items"]) == 1

    removed = remove_item(project, item_id=item["id"])
    assert removed["part"] == "Bracket"
    assert list_items(project) == []


def test_bom_remove_by_part(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "etools-home"))
    project = tmp_path / "bom2"
    init_project(project)
    add_item(project, part="Bolt", qty=4)
    remove_item(project, part="Bolt")
    assert list_items(project) == []


def test_bom_cli(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "etools-home"))
    project = tmp_path / "cli-bom"
    assert main(["init", str(project), "--name", "CLI BOM"]) == 0

    code = main(
        [
            "bom",
            "add",
            str(project),
            "--part",
            "Plate",
            "--qty",
            "1",
            "--material",
            "SS304",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "Added BOM item" in out
    assert "Plate" in out

    assert main(["bom", str(project), "--json"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert len(data["items"]) == 1
    item_id = data["items"][0]["id"]

    assert main(["bom", "remove", str(project), "--id", item_id]) == 0
    capsys.readouterr()  # discard remove output
    assert main(["bom", str(project), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["items"] == []
