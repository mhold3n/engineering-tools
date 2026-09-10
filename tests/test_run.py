"""Tests for etools run (custom decks)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from engineering_tools.cli import main
from engineering_tools.jobs import jobs_log_path, read_jobs
from engineering_tools.project import init_project
from engineering_tools.registry import list_projects


def _fake_ccx(tmp_path: Path, monkeypatch) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    ccx = fake_bin / "ccx"
    ccx.write_text(
        "#!/bin/sh\n"
        "job=\"$1\"\ntouch \"${job}.frd\" \"${job}.dat\"\nexit 0\n",
        encoding="utf-8",
    )
    ccx.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))
    return fake_bin


def _fake_freecad(tmp_path: Path, monkeypatch) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    fc = fake_bin / "FreeCADCmd"
    fc.write_text(
        "#!/bin/sh\n"
        "out=\"$2\"\n"
        "touch \"$out\"\n"
        "echo freecad-run-ok\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fc.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + "/usr/bin:/bin")
    return fake_bin


def test_run_calculix_logs_job_and_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "etools-home"))
    _fake_ccx(tmp_path, monkeypatch)

    project = tmp_path / "run-proj"
    init_project(project)

    inp = tmp_path / "custom_beam.inp"
    inp.write_text("*HEADING\ncustom\n", encoding="utf-8")

    code = main(
        [
            "run",
            "--tool",
            "calculix",
            "--input",
            str(inp),
            "--project",
            str(project),
        ]
    )
    assert code == 0

    jobs = read_jobs(project, limit=5)
    assert len(jobs) == 1
    record = jobs[0]
    assert record["command"] == "run"
    assert record["tool"] == "calculix"
    assert record["status"] == "ok"
    assert record["input"] == str(inp.resolve())
    assert record["credit"]
    assert isinstance(record["outputs"], list)
    assert any(str(p).endswith(".frd") for p in record["outputs"])

    art = project / "artifacts"
    run_dirs = [p for p in art.iterdir() if p.is_dir() and p.name.startswith("run-")]
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "custom_beam.inp").is_file()
    assert (run_dirs[0] / "custom_beam.frd").is_file()

    entry = list_projects()[0]
    assert Path(entry["path"]).resolve() == project.resolve()


def test_run_shorthand_calculix(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "etools-home"))
    _fake_ccx(tmp_path, monkeypatch)
    project = tmp_path / "sh"
    init_project(project)
    inp = project / "deck.inp"
    inp.write_text("*HEADING\n", encoding="utf-8")

    code = main(["run", "calculix", str(inp), "--project", str(project), "--json"])
    assert code == 0
    jobs = read_jobs(project)
    assert jobs[0]["command"] == "run"
    assert jobs[0]["tool"] == "calculix"


def test_run_freecad(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "etools-home"))
    _fake_freecad(tmp_path, monkeypatch)
    project = tmp_path / "fc-run"
    init_project(project)
    script = tmp_path / "make_box.py"
    script.write_text("print('hi')\n", encoding="utf-8")

    code = main(
        [
            "run",
            "--tool",
            "freecad",
            "--input",
            str(script),
            "--project",
            str(project),
        ]
    )
    assert code == 0
    jobs = read_jobs(project)
    assert jobs[0]["tool"] == "freecad"
    assert jobs[0]["status"] == "ok"
    assert jobs_log_path(project).is_file()


def test_run_missing_tool(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "etools-home"))
    monkeypatch.setenv("PATH", "/nonexistent-etools-path")
    project = tmp_path / "missing"
    init_project(project)
    inp = tmp_path / "x.inp"
    inp.write_text("*HEADING\n", encoding="utf-8")
    code = main(
        ["run", "--tool", "calculix", "--input", str(inp), "--project", str(project)]
    )
    assert code == 1
    jobs = read_jobs(project)
    assert jobs[0]["status"] == "fail"
    assert "not found" in jobs[0]["message"].lower() or "ccx" in jobs[0]["message"].lower()
