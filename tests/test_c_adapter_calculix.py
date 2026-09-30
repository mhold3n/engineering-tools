"""CalculiX-preCICE participant tests.

Agents: these tests never execute a live CalculiX binary. `shutil.which`
and `subprocess.run` are replaced. Plain `ccx` is the A/B solver and must
not satisfy `find_calculix_participant`. The adapter config filename the
CalculiX-preCICE adapter reads from the case directory is `config.yml`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engineering_tools.c_adapter_calculix import (
    find_calculix_participant,
    prepare_solid_participant,
    run_step,
)


def test_find_calculix_participant_ignores_plain_ccx(monkeypatch: pytest.MonkeyPatch) -> None:
    """ccx_preCICE, ccx_precice, and calculix-precice absent → None even if ccx exists."""

    def _which(name: str) -> str | None:
        if name == "ccx":
            return "/usr/bin/ccx"
        return None

    monkeypatch.setattr("engineering_tools.c_adapter_calculix.shutil.which", _which)
    assert find_calculix_participant() is None


def test_find_calculix_participant_prefers_ccx_preCICE(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """First hit wins: ccx_preCICE before ccx_precice and calculix-precice."""
    preferred = tmp_path / "ccx_preCICE"
    preferred.write_text("", encoding="utf-8")
    later = tmp_path / "ccx_precice"
    later.write_text("", encoding="utf-8")

    def _which(name: str) -> str | None:
        if name == "ccx_preCICE":
            return str(preferred)
        if name == "ccx_precice":
            return str(later)
        if name == "calculix-precice":
            return str(tmp_path / "calculix-precice")
        if name == "ccx":
            return "/usr/bin/ccx"
        return None

    monkeypatch.setattr("engineering_tools.c_adapter_calculix.shutil.which", _which)
    assert find_calculix_participant() == preferred


def test_find_calculix_participant_falls_back_to_ccx_precice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When ccx_preCICE is absent, the next documented name is ccx_precice."""
    fallback = tmp_path / "ccx_precice"
    fallback.write_text("", encoding="utf-8")

    def _which(name: str) -> str | None:
        if name == "ccx_precice":
            return str(fallback)
        return None

    monkeypatch.setattr("engineering_tools.c_adapter_calculix.shutil.which", _which)
    assert find_calculix_participant() == fallback


def test_prepare_solid_participant_writes_traction_and_displacement(tmp_path: Path) -> None:
    """config.yml names participant Solid, reads Traction, writes Displacement."""
    work = tmp_path / "c-solid"
    work.mkdir()
    config_xml = tmp_path / "precice-config.xml"
    config_xml.write_text("<precice-configuration/>\n", encoding="utf-8")

    written = prepare_solid_participant(work, config_xml)

    assert written == work / "config.yml"
    text = written.read_text(encoding="utf-8")
    assert "Solid" in text
    assert "Displacement" in text
    assert "Force" in text
    assert "precice-config" in text
    assert str(config_xml) in text


def test_run_step_launches_ccx_preCICE_not_ccx_or_precice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Documented argv: ccx_preCICE -i <deck stem> -precice-participant Solid."""
    binary = tmp_path / "bin" / "ccx_preCICE"
    binary.parent.mkdir()
    binary.write_text("", encoding="utf-8")
    work = tmp_path / "c-solid"
    work.mkdir()
    (work / "c-solid.inp").write_text("*HEADING\n", encoding="utf-8")
    launched: list[list[str]] = []

    def _which(name: str) -> str | None:
        if name == "ccx_preCICE":
            return str(binary)
        return None

    def _run(argv: list[str], **_kwargs: object) -> object:
        launched.append(list(argv))

        class _Proc:
            returncode = 0

        return _Proc()

    monkeypatch.setattr("engineering_tools.c_adapter_calculix.shutil.which", _which)
    monkeypatch.setattr("engineering_tools.c_adapter_calculix.subprocess.run", _run)

    assert run_step(work, 0) is True
    assert launched == [[str(binary), "-i", "c-solid", "-precice-participant", "Solid"]]
    assert Path(launched[0][0]).name not in {"precice", "ccx"}


def test_solid_argv_prefixes_mpirun_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """OpenMPI hosts wrap ccx_preCICE; CI fakes without mpirun do not."""
    from engineering_tools.c_adapter_calculix import solid_participant_argv

    binary = tmp_path / "bin" / "ccx_preCICE"
    mpirun = tmp_path / "bin" / "mpirun"
    binary.parent.mkdir()
    binary.write_text("", encoding="utf-8")
    mpirun.write_text("", encoding="utf-8")
    work = tmp_path / "c-solid"
    work.mkdir()
    (work / "c-solid.inp").write_text("*HEADING\n", encoding="utf-8")

    def _which(name: str) -> str | None:
        if name == "ccx_preCICE":
            return str(binary)
        if name == "mpirun":
            return str(mpirun)
        return None

    monkeypatch.setattr("engineering_tools.c_adapter_calculix.shutil.which", _which)
    monkeypatch.delenv("OMPI_COMM_WORLD_SIZE", raising=False)
    argv = solid_participant_argv(work)
    assert argv == [
        str(mpirun),
        "--oversubscribe",
        "-n",
        "1",
        str(binary),
        "-i",
        "c-solid",
        "-precice-participant",
        "Solid",
    ]
    monkeypatch.setenv("OMPI_COMM_WORLD_SIZE", "1")
    nested = solid_participant_argv(work)
    assert nested == [str(binary), "-i", "c-solid", "-precice-participant", "Solid"]
