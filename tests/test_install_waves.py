"""Wave membership and install CLI coverage tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engineering_tools.cli import main
from engineering_tools.install_waves import INSTALL_WAVES, all_wave_component_ids
from engineering_tools.manifest import load_manifest


def test_wave_membership_covers_non_3dx_mapping_components_exactly() -> None:
    data = load_manifest()
    inventory = {item["id"]: item for item in data["inventory"]}

    def deferred(inventory_id: str) -> bool:
        row = inventory[inventory_id]
        return "3dexperience" in row["id"].lower() or "3dexperience" in row["name"].lower()

    expected: set[str] = set()
    for mapping in data["mappings"]:
        if deferred(mapping["inventory_id"]):
            continue
        expected.update(mapping["components"])

    waved = all_wave_component_ids()
    assert len(waved) == 53
    assert len(waved) == len(set(waved))
    assert set(waved) == expected
    # engineering-tools is first-party CLI kernel, installed outside the wave list.
    assert "engineering-tools" not in set(waved)


def test_install_cli_unknown_wave(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path))
    code = main(["install", "--wave", "no-such-wave"])
    assert code != 0
    err = capsys.readouterr().err
    assert "unknown wave" in err.lower() or "no-such-wave" in err


def test_install_cli_unknown_component(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path))
    code = main(["install", "definitely-missing-component"])
    assert code != 0
    captured = capsys.readouterr()
    assert "unknown component" in (captured.err + captured.out).lower()


def test_install_cli_wave_continues_after_failure(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "state"))
    # Mega-ops recipes are still unimplemented → typed failures, continue-on-fail.
    worktree = tmp_path / "repo"
    worktree.mkdir()
    monkeypatch.chdir(worktree)
    code = main(["install", "--wave", "6-mega-ops", "--json"])
    assert code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert len(payload["results"]) == len(INSTALL_WAVES["6-mega-ops"])
    assert all(row["status"] == "failed" for row in payload["results"])
