"""Tests for packaged FreeCAD hello sample and normalized probe."""

from __future__ import annotations

import os
from pathlib import Path

from engineering_tools.hello_probes import load_freecad_sample, probe_freecad


def test_load_freecad_sample_mentions_hellobox():
    text = load_freecad_sample()
    assert "HelloBox" in text
    assert "Part::Box" in text


def test_freecad_probe_runs_fake_freecad(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    # No ccx — force FreeCAD path (keep /usr/bin:/bin so fake script can call touch)
    fc = fake_bin / "FreeCADCmd"
    fc.write_text(
        "#!/bin/sh\n"
        "# fake FreeCADCmd: argv1=script argv2=output.FCStd\n"
        "out=\"$2\"\n"
        "touch \"$out\"\n"
        "echo engineering-tools: FreeCAD hello_box OK\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fc.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + "/usr/bin:/bin")

    result = probe_freecad(project=tmp_path / "project")
    assert result["id"] == "freecad"
    assert result["status"] == "ok"
    assert result["locator"]
    assert result["credit"]
    assert any(path.endswith(".FCStd") for path in result["outputs"])


def test_freecad_probe_marks_nonzero_execution_broken(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    command = fake_bin / "FreeCADCmd"
    command.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
    command.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + "/usr/bin:/bin")

    assert probe_freecad()["status"] == "broken"


def test_freecad_probe_missing_is_typed(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent-etools-path")
    assert probe_freecad()["status"] == "missing"
