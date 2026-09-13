"""Tests for packaged CalculiX sample and normalized probe."""

from __future__ import annotations

import os
from pathlib import Path

from engineering_tools.hello_probes import load_calculix_sample, probe_calculix


def test_load_calculix_sample_contains_c3d8():
    text = load_calculix_sample()
    assert "*ELEMENT, TYPE=C3D8" in text
    assert "hello_beam" in text.lower() or "engineering-tools" in text.lower()


def test_calculix_probe_runs_fake_ccx(tmp_path, monkeypatch):
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

    result = probe_calculix(project=tmp_path / "project")
    assert result["id"] == "calculix"
    assert result["status"] == "ok"
    assert result["locator"]
    assert result["credit"]
    assert any(path.endswith(".frd") for path in result["outputs"])


def test_calculix_probe_marks_nonzero_execution_broken(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ccx = fake_bin / "ccx"
    ccx.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
    ccx.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + "/usr/bin:/bin")

    assert probe_calculix()["status"] == "broken"


def test_calculix_probe_missing_is_typed(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent-etools-path")
    assert probe_calculix()["status"] == "missing"
