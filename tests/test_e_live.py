"""Phase E live couple: Solid+Fluid Popen, CAD probes, fixture bands.

Agents: pytest uses PATH fakes. No process named precice. Live XML is
Force/Displacement/Temperature on interface and Heat-Flux on interface-faces.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from engineering_tools.e_adapter_calculix import CI_SOLID_MSH2
from engineering_tools.e_cad import import_identity
from engineering_tools.e_scenario import reference_model


def _executable(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _e_live_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, solid_frd: Path) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    windows = "printf 'Time window completed\\nTime window completed\\n'\n"
    copy_frd = f"cp '{solid_frd}' ./e-solid.frd\n"
    fixture = tmp_path / "ci.msh"
    fixture.write_text(CI_SOLID_MSH2, encoding="utf-8")
    # PATH gmsh copies this fixture; it does not execute Merge of vessel.step.
    _executable(binary_dir / "ccx", "exit 0\n")
    _executable(
        binary_dir / "ccx_preCICE",
        "case \"$1\" in -v|--version) echo 'This is Version 2.21'; exit 0;; esac\n"
        + copy_frd
        + windows
        + "exit 0\n",
    )
    _executable(
        binary_dir / "rhoPimpleFoam",
        "case \"$1\" in -help|-h) echo 'Usage: rhoPimpleFoam'; exit 0;; esac\n"
        + windows
        + "mkdir -p ./0.01\n"
        + "printf 'internalField uniform 101000;\\n' > ./0.01/p\n"
        + "printf 'internalField uniform 350;\\n' > ./0.01/T\n"
        + "exit 0\n",
    )
    _executable(
        binary_dir / "gmshToFoam",
        "mkdir -p constant/polyMesh\n"
        "printf 'FoamFile { class dictionary; }\\n' > constant/polyMesh/boundary\n"
        "exit 0\n",
    )
    _executable(
        binary_dir / "gmsh",
        f'if [ "$1" = "--version" ]; then echo 4.13.1; exit 0; fi\n'
        f'out=""\n'
        f'while [ $# -gt 0 ]; do\n'
        f'  if [ "$1" = "-o" ]; then shift; out="$1"; fi\n'
        f'  shift\n'
        f'done\n'
        f'if [ -z "$out" ]; then echo "gmsh fake requires -o" >&2; exit 1; fi\n'
        f'cp "{fixture}" "$out"\n'
        f"exit 0\n",
    )
    _executable(binary_dir / "precice-tools", "echo 3.4.1\n")
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    monkeypatch.setenv("ETOOLS_E_MOCK_SOLVERS", "1")
    monkeypatch.setenv("OMPI_COMM_WORLD_SIZE", "1")


def _e_frd(path: Path) -> None:
    # CI wedge msh nodes 1-3 inner wall, 4-6 outer.
    lines = ["    2C"]
    nodes = {
        1: (-0.02, -0.005, 0.0),
        2: (-0.02, 0.005, 0.0),
        3: (-0.02, 0.0, 0.04),
        4: (-0.025, -0.005, 0.0),
        5: (-0.025, 0.005, 0.0),
        6: (-0.025, 0.0, 0.04),
    }
    for nid, xyz in nodes.items():
        lines.append(f" -1         {nid} {xyz[0]:.5e} {xyz[1]:.5e} {xyz[2]:.5e}")
    lines.append(" -3")
    lines.append(" -4  DISP        4    1")
    for nid in (1, 2, 3):
        lines.append(f" -1         {nid} 1.00000e-08 0.00000e+00 0.00000e+00")
    lines.append(" -3")
    lines.append(" -4  FORC        4    1")
    for nid in (1, 2, 3):
        lines.append(f" -1         {nid} 3.00000e+00 0.00000e+00 0.00000e+00")
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

    ident = import_identity()
    solid = tmp_path / "e-solid"
    solid.mkdir()
    msh = solid / "solid.msh"
    msh.write_text(CI_SOLID_MSH2, encoding="utf-8")
    write_e_solid_inp(solid / "e-solid.inp", ident, msh=msh)
    _e_frd(solid / "e-solid.frd")
    fluid = tmp_path / "e-fluid"
    fluid.mkdir()
    (fluid / "fluid.msh").write_text(CI_SOLID_MSH2, encoding="utf-8")
    fluid_probes = sample_e_fluid_probes(fluid)
    solid_probes = sample_e_solid_probes(solid)
    assert fluid_probes["face.inner_wall.interface_locations"]["value"] == pytest.approx(1.0)
    assert "face.inner_wall" in str(fluid_probes["face.inner_wall.interface_locations"].get("patch"))
    assert solid_probes["face.inner_wall.displacement"]["value"] == pytest.approx(1.0e-8)
    assert solid_probes["face.inner_wall.integrated_force"]["value"] == pytest.approx(9.0)


def test_incomplete_interface_disp_or_forc_is_missing(tmp_path: Path) -> None:
    from engineering_tools.e_adapter_calculix import sample_e_solid_probes, write_e_solid_inp

    ident = import_identity()
    solid = tmp_path / "e-solid"
    solid.mkdir()
    msh = solid / "solid.msh"
    msh.write_text(CI_SOLID_MSH2, encoding="utf-8")
    write_e_solid_inp(solid / "e-solid.inp", ident, msh=msh)
    _e_frd(solid / "e-solid.frd")
    text = (solid / "e-solid.frd").read_text(encoding="utf-8")
    lines = text.splitlines()
    dropped_disp = [line for line in lines if not (line.startswith(" -1         3") and "1.00000e-08" in line)]
    (solid / "e-solid.frd").write_text("\n".join(dropped_disp) + "\n", encoding="utf-8")
    assert sample_e_solid_probes(solid) == {}
    _e_frd(solid / "e-solid.frd")
    text = (solid / "e-solid.frd").read_text(encoding="utf-8")
    lines = text.splitlines()
    dropped_forc = []
    forc_mode = False
    for line in lines:
        if line.startswith(" -4  FORC"):
            forc_mode = True
        if forc_mode and line.startswith(" -1         3"):
            continue
        if line.startswith(" -3") and forc_mode:
            forc_mode = False
        dropped_forc.append(line)
    (solid / "e-solid.frd").write_text("\n".join(dropped_forc) + "\n", encoding="utf-8")
    probes = sample_e_solid_probes(solid)
    assert "face.inner_wall.displacement" in probes
    assert "face.inner_wall.integrated_force" not in probes


def test_run_e_session_path_fakes_are_not_engineering_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engineering_tools.e_facade import run_e_session

    frd = tmp_path / "seed.frd"
    _e_frd(frd)
    _e_live_tools(tmp_path, monkeypatch, solid_frd=frd)
    session = run_e_session(tmp_path / "e-out", reference_model())
    assert session["e_ok"] is False
    assert session.get("live") is False
    assert session.get("status") == "mock"
    assert int(session["solid_interface_vertices"]) == 3
    assert int(session["fluid_interface_locations"]) == 1
    xml = (tmp_path / "e-out" / "precice-config.xml").read_text()
    assert "Force" in xml
    assert "Traction" not in xml
    assert "Temperature" in xml
    assert "Heat-Flux" in xml
    assert 'exchange data="Heat-Flux" mesh="interface-faces"' in xml
    assert 'write-data name="Heat-Flux" mesh="interface"' not in xml
    assert 'read-data name="Heat-Flux" mesh="interface"' not in xml
    iface_block = xml.split('<mesh name="interface"', 1)[1].split("</mesh>", 1)[0]
    assert "Heat-Flux" not in iface_block
    yml = (tmp_path / "e-out" / "e-solid" / "config.yml").read_text()
    assert "nodes-mesh: interface" in yml
    assert "faces-mesh: interface-faces" in yml
    assert "write-data" not in yml
    assert "read-data: [Force]" in yml
    assert "Heat-Flux" in yml
    inp = (tmp_path / "e-out" / "e-solid" / "e-solid.inp").read_text()
    assert "*COUPLED TEMPERATURE-DISPLACEMENT" in inp
    assert "*DFLUX" in inp
    assert "*CONDUCTIVITY" in inp
    assert "*RIGID BODY" not in inp
    assert "1, 6" not in inp
    for nid in (7, 8, 9, 10):
        assert f"{nid}, 1, 3, 0." in inp
    t_field = (tmp_path / "e-out" / "e-fluid" / "0" / "T").read_text()
    wall = t_field.split("face.inner_wall", 1)[1]
    assert "fixedValue" in wall.split("lid", 1)[0]
    graph_text = json.dumps(session["field_graph"])
    assert "Heat-Flux" in graph_text
    assert session["checkpoint_events"] == []
    assert session["capabilities_used"] == ["path_mock"]
    assert session["constitutive_executed"] == "linear_elastic"
    assert "heat_flux" not in session["not_executed"]
    assert "temperature_dependent_elastic" in session["not_executed"]
    assert "rigid_body" not in session["not_executed"]
    assert "prescribed_rigid_motion" not in session["not_executed"]
    materials = session["problem"]["materials"]
    assert all(row.get("constitutive_model") != "temperature_dependent_elastic" for row in materials)
    assert any(row.get("constitutive_model") == "linear_elastic" and row.get("E_Pa") == 2.0e11 for row in materials)
    assert any(row.get("constitutive_model") == "rigid" for row in materials)
    motions = session["problem"]["boundary_conditions"]["region_motion"]
    allowed = set(import_identity()["entity_ids"])
    assert all(row.get("entity_id") in allowed for row in motions)
    assert all(row.get("entity_id") != "body.shell_lid" for row in motions)
    by_id = {row["entity_id"]: row for row in motions}
    assert by_id["body.shell"]["motion_model"] == "deformable_motion"
    assert by_id["body.lid"]["motion_model"] == "prescribed_rigid_motion"
    assert by_id["body.gas"]["motion_model"] == "fixed"
    assert by_id["body.shell"]["mesh_set"] == "body.shell"
    assert by_id["body.lid"]["mesh_set"] == "body.lid"
    assert session["problem"]["geometry_source"] == "vessel_step"
    assert session["problem"]["mesh_bound_to_cad_fingerprint"] is False
    assert session["solver_convergence"] is None
    assert session["coupling_convergence"] is False
    probes = session["probes"]
    assert "face.inner_wall.pressure" not in probes
    assert probes["face.inner_wall.displacement"]["value"] == pytest.approx(1.0e-8)
    err = session.get("mapping_error") or {}
    assert err.get("relative") != 0.0 or err.get("relative") is None
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
        "case \"$1\" in -help|-h) echo 'Usage: rhoPimpleFoam'; exit 0;; esac\n"
        "printf 'Time window completed\\nTime window completed\\n'\n"
        "mkdir -p ./0.01\n"
        "printf 'internalField uniform 0;\\n' > ./0.01/p\n"
        "printf 'internalField uniform 350;\\n' > ./0.01/T\n"
        "exit 0\n",
    )
    session = run_e_session(tmp_path / "e-zero-p", reference_model())
    assert session["e_ok"] is False
    assert session["status"] == "mock"


def test_version_probe_does_not_write_cwd_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil

    from engineering_tools.e_facade import _backend_versions

    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    _executable(
        binary_dir / "rhoPimpleFoam",
        "mkdir -p ./0.01\nprintf 'leaked\\n' > ./0.01/p\nexit 0\n",
    )
    _executable(binary_dir / "ccx_preCICE", "printf 'This is Version 2.21\\n' >&2; : > ./e-solid.frd; exit 0\n")
    _executable(binary_dir / "gmsh", "echo 4.13.1\n")
    _executable(binary_dir / "precice-tools", "echo 3.4.1\n")
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    monkeypatch.delenv("WM_PROJECT_VERSION", raising=False)
    monkeypatch.setattr("engineering_tools.e_facade._ESI_FOAM", tmp_path / "missing-esi")
    original_which = shutil.which

    def _which(name: str, path: str | None = None) -> str | None:
        if name == "foamVersion":
            return None
        return original_which(name, path=path)

    monkeypatch.setattr("engineering_tools.e_facade.shutil.which", _which)
    _backend_versions()
    cwd = Path.cwd()
    assert not (cwd / "0.01").exists()
    assert not (cwd / "e-solid.frd").exists()
    assert not (tmp_path / "0.01").exists()
    assert not (tmp_path / "e-solid.frd").exists()
