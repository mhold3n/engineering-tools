"""Phase E live couple: Solid+Fluid Popen, CAD probes, fixture bands.

Agents: pytest uses PATH fakes. No process named precice. Live XML is
Force/Displacement only so OpenFOAM FSI and CalculiX adapters can join;
the session still records CAD thermal probes from field T.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from engineering_tools.e_cad import import_identity
from engineering_tools.e_scenario import reference_model


def _executable(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _e_live_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, solid_frd: Path) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    windows = "printf 'Time window completed\\nTime window completed\\n'\n"
    copy_frd = f"cp '{solid_frd}' e-solid.frd\n"
    _executable(binary_dir / "ccx", "exit 0\n")
    _executable(binary_dir / "ccx_preCICE", copy_frd + windows + "exit 0\n")
    _executable(
        binary_dir / "rhoPimpleFoam",
        windows
        + "mkdir -p 0.01\n"
        + "printf 'internalField uniform 101325;\\n' > 0.01/p\n"
        + "printf 'internalField uniform 350;\\n' > 0.01/T\n"
        + "exit 0\n",
    )
    _executable(binary_dir / "blockMesh", "mkdir -p constant/polyMesh\ntouch constant/polyMesh/points\nexit 0\n")
    _executable(binary_dir / "precice-tools", "exit 0\n")
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")


def _e_frd(path: Path) -> None:
    # SI deck nodes: NinterfaceN ids 2,4,6,8 at x=-0.02. DISP in metres.
    lines = ["    2C"]
    nodes = {
        1: (-0.025, -0.02, 0.0),
        2: (-0.02, -0.02, 0.0),
        3: (-0.025, 0.02, 0.0),
        4: (-0.02, 0.02, 0.0),
        5: (-0.025, -0.02, 0.04),
        6: (-0.02, -0.02, 0.04),
        7: (-0.025, 0.02, 0.04),
        8: (-0.02, 0.02, 0.04),
    }
    for nid, xyz in nodes.items():
        lines.append(f" -1         {nid} {xyz[0]:.5e} {xyz[1]:.5e} {xyz[2]:.5e}")
    lines.append(" -3")
    lines.append(" -4  DISP        4    1")
    for nid in (5, 6, 7, 8):
        lines.append(f" -1         {nid} 2.30630e-09 0.00000e+00 0.00000e+00")
    lines.append(" -3")
    lines.append(" -4  STRESS      6    1")
    for nid in nodes:
        lines.append(
            f" -1         {nid} 8.00000e+07 0.00000e+00 0.00000e+00 0.00000e+00 0.00000e+00 0.00000e+00"
        )
    lines.append(" -3")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_load_e_bands_has_n_steps_and_cad_probe_ids() -> None:
    from engineering_tools.e_parity import load_e_fsi_bands

    bands = load_e_fsi_bands()
    assert int(bands["n_steps"]) >= 2
    assert "face.inner_wall.pressure" in bands["parity"]
    assert "face.inner_wall.temperature" in bands["parity"]
    assert "face.inner_wall.displacement" in bands["parity"]


def test_sample_e_probes_read_inner_wall_si_fields(tmp_path: Path) -> None:
    from engineering_tools.e_adapter_calculix import sample_e_solid_probes, write_e_solid_inp
    from engineering_tools.e_adapter_openfoam import sample_e_fluid_probes
    from engineering_tools.e_mesh_fluid import write_fluid_block_mesh_dict

    ident = import_identity()
    solid = tmp_path / "e-solid"
    solid.mkdir()
    write_e_solid_inp(solid / "e-solid.inp", ident)
    _e_frd(solid / "e-solid.frd")
    fluid = tmp_path / "e-fluid"
    write_fluid_block_mesh_dict(fluid / "system" / "blockMeshDict")
    tdir = fluid / "0.01"
    tdir.mkdir(parents=True)
    (tdir / "p").write_text("internalField uniform 101325;\n", encoding="utf-8")
    (tdir / "T").write_text("internalField uniform 350;\n", encoding="utf-8")
    fluid_probes = sample_e_fluid_probes(fluid)
    solid_probes = sample_e_solid_probes(solid)
    assert fluid_probes["face.inner_wall.pressure"]["value"] == pytest.approx(101325.0)
    assert fluid_probes["face.inner_wall.temperature"]["value"] == pytest.approx(350.0)
    assert "inner_wall" in str(fluid_probes["face.inner_wall.pressure"].get("patch", "inner_wall"))
    assert solid_probes["face.inner_wall.displacement"]["value"] == pytest.approx(2.3063e-09, rel=1e-3)


def test_run_e_session_live_ok_with_fakes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engineering_tools.e_facade import run_e_session

    frd = tmp_path / "seed.frd"
    _e_frd(frd)
    _e_live_tools(tmp_path, monkeypatch, solid_frd=frd)
    session = run_e_session(tmp_path / "e-out", reference_model())
    assert session["e_ok"] is True
    assert session.get("live") is True
    xml = (tmp_path / "e-out" / "precice-config.xml").read_text()
    assert "Force" in xml
    assert "Traction" not in xml
    assert "Heat-Flux" not in xml
    probes = session["probes"]
    assert probes["face.inner_wall.pressure"]["value"] == pytest.approx(101325.0)
    assert probes["face.inner_wall.temperature"]["value"] == pytest.approx(350.0)
    assert probes["face.inner_wall.displacement"]["value"] == pytest.approx(2.3063e-09, rel=1e-3)
    assert (tmp_path / "e-out" / "e-fluid" / "participant.log").is_file()
    assert (tmp_path / "e-out" / "e-solid" / "participant.log").is_file()


def test_zero_live_pressure_fails_bands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engineering_tools.e_facade import run_e_session

    frd = tmp_path / "seed.frd"
    _e_frd(frd)
    _e_live_tools(tmp_path, monkeypatch, solid_frd=frd)
    binary_dir = tmp_path / "bin"
    _executable(
        binary_dir / "rhoPimpleFoam",
        "printf 'Time window completed\\nTime window completed\\n'\n"
        "mkdir -p 0.01\n"
        "printf 'internalField uniform 0;\\n' > 0.01/p\n"
        "printf 'internalField uniform 350;\\n' > 0.01/T\n"
        "exit 0\n",
    )
    session = run_e_session(tmp_path / "e-zero-p", reference_model())
    assert session["e_ok"] is False
    assert session["status"] == "broken"
