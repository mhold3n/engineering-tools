"""Tests for PLM slice: registry, job history, projects/jobs CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path

from engineering_tools.cli import main
from engineering_tools.jobs import jobs_log_path, read_jobs
from engineering_tools.project import init_project
from engineering_tools.registry import list_projects, registry_path


def _fake_ccx_path(tmp_path: Path, monkeypatch) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ccx = fake_bin / "ccx"
    ccx.write_text(
        "#!/bin/sh\n"
        "job=\"$1\"\ntouch \"${job}.frd\" \"${job}.dat\"\nexit 0\n",
        encoding="utf-8",
    )
    ccx.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))
    return fake_bin


def test_hello_project_appends_job(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "etools-home"
    monkeypatch.setenv("ETOOLS_HOME", str(home))
    _fake_ccx_path(tmp_path, monkeypatch)

    project = tmp_path / "proj"
    init_project(project, name="Proj")

    code = main(["hello", "--project", str(project)])
    assert code == 0

    log = jobs_log_path(project)
    assert log.is_file()
    lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["command"] == "hello"
    assert record["status"] == "ok"
    assert record["tool"] == "CalculiX"
    assert isinstance(record["outputs"], list)
    assert record["credit"]
    assert "created" in record

    jobs = read_jobs(project, limit=5)
    assert len(jobs) == 1
    assert jobs[0]["id"] == record["id"]

    # registry updated timestamp bumped
    entry = list_projects()[0]
    assert Path(entry["path"]).resolve() == project.resolve()


def test_projects_and_jobs_cli(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "etools-home"
    monkeypatch.setenv("ETOOLS_HOME", str(home))
    _fake_ccx_path(tmp_path, monkeypatch)

    project = tmp_path / "cli-plm"
    assert main(["init", str(project), "--name", "CLI PLM"]) == 0
    assert main(["hello", "--project", str(project)]) == 0

    assert main(["projects", "--json"]) == 0
    # Capture via list_projects for assertions (CLI prints to stdout)
    projects = list_projects()
    assert len(projects) == 1
    assert projects[0]["name"] == "CLI PLM"

    assert main(["jobs", str(project), "--limit", "10"]) == 0
    assert main(["jobs", str(project), "--json"]) == 0
    jobs = read_jobs(project, limit=10)
    assert len(jobs) == 1
    assert jobs[0]["command"] == "hello"


def test_etools_home_isolation(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "isolated-home"
    monkeypatch.setenv("ETOOLS_HOME", str(home))
    real_home_marker = Path.home() / ".engineering-tools" / "registry.json"
    # We never create/write under the real home in this test; only under ETOOLS_HOME.
    before = real_home_marker.exists()

    project = tmp_path / "iso"
    init_project(project)
    assert registry_path().is_relative_to(home.resolve())
    assert registry_path().is_file()
    assert real_home_marker.exists() == before
