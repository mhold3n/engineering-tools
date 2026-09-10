"""Tests for packaged FreeCAD hello sample."""

from __future__ import annotations

import os
from pathlib import Path

from engineering_tools.hello import load_freecad_sample, run_hello


def test_load_freecad_sample_mentions_hellobox():
    text = load_freecad_sample()
    assert "HelloBox" in text
    assert "Part::Box" in text


def test_hello_runs_fake_freecad(tmp_path, monkeypatch):
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

    project = tmp_path / "proj"
    project.mkdir()
    (project / "artifacts").mkdir()

    result = run_hello(project=str(project))
    assert result["ok"] is True
    assert result["backend"] == "FreeCAD"
    assert "FreeCAD" in result["message"]
    assert (project / "artifacts" / "freecad-hello" / "hello_box.py").is_file()
    assert (project / "artifacts" / "freecad-hello" / "hello_box.FCStd").is_file()
