"""Tests for hello smoke paths and packaged CalculiX sample."""

from __future__ import annotations

import os
from pathlib import Path

from engineering_tools.hello import load_calculix_sample, run_hello


def test_load_calculix_sample_contains_c3d8():
    text = load_calculix_sample()
    assert "*ELEMENT, TYPE=C3D8" in text
    assert "hello_beam" in text.lower() or "engineering-tools" in text.lower()


def test_hello_runs_fake_ccx(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ccx = fake_bin / "ccx"
    ccx.write_text(
        "#!/bin/sh\n"
        "# fake CalculiX: accept job name, write empty .frd\n"
        "job=\"$1\"\ntouch \"${job}.frd\" \"${job}.dat\"\nexit 0\n",
        encoding="utf-8",
    )
    ccx.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))

    project = tmp_path / "proj"
    project.mkdir()
    (project / "artifacts").mkdir()

    result = run_hello(project=str(project))
    assert result["ok"] is True
    assert result["backend"] == "CalculiX"
    assert "CalculiX" in result["message"]
    assert (project / "artifacts" / "calculix-hello" / "hello_beam.inp").is_file()
    assert (project / "artifacts" / "calculix-hello" / "hello_beam.frd").is_file()


def test_hello_without_tools(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent-etools-path")
    result = run_hello()
    assert result["ok"] is False
    assert result["backend"] is None
