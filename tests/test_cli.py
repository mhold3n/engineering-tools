"""CLI smoke tests via engineering_tools.cli.main."""

from __future__ import annotations

import json
from pathlib import Path

from engineering_tools.cli import main


def test_doctor_returns_int() -> None:
    code = main(["doctor"])
    assert code in (0, 1)


def test_profile_alias() -> None:
    code = main(["profile"])
    assert code in (0, 1)


def test_init_creates_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "etools-home"))
    target = tmp_path / "cli-part"
    code = main(["init", str(target), "--name", "CLI Part"])
    assert code == 0
    assert (target / ".engineering-tools.json").is_file()
    assert (target / ".engineering-tools").is_dir()
    assert (target / "jobs").is_dir()
    assert (target / "artifacts").is_dir()


def test_hello_json_is_parseable_and_packaged_manifest_is_red(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "state"))
    code = main(["hello", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert code == 1
    # Inventory is audited; Alpha stays red until product capability probes cover mappings.
    assert report["inventory_state"] == "audited"
    # Inventory is audited; Alpha stays red until product capability probes cover mappings.
    assert report["status"] == "incomplete"
    assert report["ok"] is False

def test_hello_with_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "etools-home"))
    proj = tmp_path / "p"
    proj.mkdir()
    code = main(["hello", "--project", str(proj)])
    assert code in (0, 1)
    # Even without init, hello --project should append a job log when project given
    assert (proj / ".engineering-tools" / "jobs.jsonl").is_file()
