"""D-FSI mesh and façade tests. No live pimpleFoam except fakes."""

import json
import os
from pathlib import Path

import pytest

from engineering_tools.c_adapter_openfoam import prepare_fluid_participant
from engineering_tools.c_backend_precice import generate_precice_config, tight_d_policy
from engineering_tools.c_fsi_meshes import write_c_fluid_case
from engineering_tools.d_fsi_meshes import (
    D_NX,
    D_NY,
    D_NZ,
    LID_U_X_M_S,
    apply_d_chamber_fields,
    d_canonical_xyz_m,
    write_d_fluid_case,
    write_d_solid_inp,
)
from engineering_tools.damper_params import load_params
from tests.test_c_fsi import _ab_snapshot_source
def _d_patch_samples(monkeypatch: pytest.MonkeyPatch, probes: dict) -> None:
    def _sample(_out: Path) -> dict:
        return probes

    monkeypatch.setattr("engineering_tools.c_adapter_calculix.sample_c_probes", _sample)
    monkeypatch.setattr("engineering_tools.c_adapter_openfoam.sample_d_probes", _sample)


def _executable(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _d_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PATH fakes that complete 20 tight D windows."""
    from engineering_tools.c_parity import load_d_fsi_bands

    n = int(load_d_fsi_bands()["n_steps"])
    windows = "printf '" + "Time window completed\\n" * n + "'\n"
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    _executable(binary_dir / "ccx", "exit 0\n")
    _executable(binary_dir / "ccx_preCICE", windows + "exit 0\n")
    _executable(
        binary_dir / "pimpleFoam",
        windows + "mkdir -p 0.1\nprintf 'internalField uniform 0.0666117647;\\n' > 0.1/p\nexit 0\n",
    )
    _executable(binary_dir / "blockMesh", "mkdir -p constant/polyMesh\ntouch constant/polyMesh/points\nexit 0\n")
    _executable(binary_dir / "precice-tools", "exit 0\n")
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")


def _d_matching_probes() -> dict:
    canonical = d_canonical_xyz_m(load_params())
    return {
        "housing.wall.pressure": {"value": 56.62, "xyz_m": canonical["housing.wall.pressure"]},
        "key.root.von_mises": {"value": 10.07e6, "xyz_m": canonical["key.root.von_mises"]},
        "housing.wall.displacement": {"value": 1e-6, "xyz_m": canonical["housing.wall.displacement"]},
        "housing.wall.traction": {"value": 56.62, "xyz_m": canonical["housing.wall.traction"]},
    }


def test_d_fluid_is_a_chamber_with_plus_x_interface(tmp_path: Path) -> None:
    params = load_params()
    case = tmp_path / "d-foam"
    write_d_fluid_case(params, case)
    foam = (case / "constant" / "polyMesh" / "blockMeshDict").read_text(encoding="utf-8")
    assert f"hex (0 1 2 3 4 5 6 7) ({D_NX} {D_NY} {D_NZ})" in foam
    assert "(0 4 7 3)" in foam
    wall = d_canonical_xyz_m(params)["housing.wall.pressure"]
    assert wall[0] == pytest.approx(-float(params["housing_id_mm"]) / 2000.0)


def test_d_chamber_fields_match_a_lid(tmp_path: Path) -> None:
    params = load_params()
    case = tmp_path / "d-foam"
    write_d_fluid_case(params, case)
    prepare_fluid_participant(case, tmp_path / "precice-config.xml")
    apply_d_chamber_fields(case)
    u_text = (case / "0" / "U").read_text(encoding="utf-8")
    assert f"({LID_U_X_M_S:g} 0 0)" in u_text
    assert "frontAndBack { type empty; }" in u_text
    assert "endTime         0.1;" in (case / "system" / "controlDict").read_text(encoding="utf-8")


def test_c_idle_lid_stays_noslip(tmp_path: Path) -> None:
    params = load_params()
    case = tmp_path / "c-foam"
    write_c_fluid_case(params, case)
    prepare_fluid_participant(case, tmp_path / "precice-config.xml")
    u_text = (case / "0" / "U").read_text(encoding="utf-8")
    assert "lid { type noSlip; }" in u_text
    assert "frontAndBack" not in u_text


def test_d_solid_is_sandwich_with_id_interface(tmp_path: Path) -> None:
    params = load_params()
    path = tmp_path / "d-solid.inp"
    write_d_solid_inp(params, path)
    text = path.read_text(encoding="utf-8")
    assert "*NSET, NSET=NinterfaceN" in text
    assert "9, 2, 60" in text or "17, 2, 60" in text or ", 2, 60.0" in text
    assert "*DLOAD" not in text
    assert "210000000000" in text or "2.10000000e+11" in text or "210000000000.0" in text


def test_tight_d_policy_xml_has_force_residual_and_aitken() -> None:
    xml = generate_precice_config(tight_d_policy())
    assert 'relative-convergence-measure data="Force"' in xml
    assert "acceleration:aitken" in xml
    assert 'data name="Force"' in xml
    assert '<max-time-windows value="20"/>' in xml
    from engineering_tools.c_backend_precice import default_policy

    c_xml = generate_precice_config(default_policy())
    assert 'relative-convergence-measure data="Force"' not in c_xml
    assert "acceleration:aitken" not in c_xml


def test_run_d_fsi_persists_ok_when_probes_follow_b(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engineering_tools.c_facade import run_d_fsi
    from engineering_tools.c_parity import load_d_fsi_bands

    _d_tools(tmp_path, monkeypatch)
    ab = tmp_path / "ab"
    _ab_snapshot_source(ab)
    _d_patch_samples(monkeypatch, _d_matching_probes())
    out = tmp_path / "d-fsi"
    session = run_d_fsi(ab_dir=ab, out=out, params=load_params())
    persisted = json.loads((out / "d-session.json").read_text(encoding="utf-8"))
    assert session["status"] == "ok"
    assert persisted["d_ok"] is True
    assert len(persisted["steps"]) == int(load_d_fsi_bands()["n_steps"])
    u_text = (out / "d-fluid" / "0" / "U").read_text(encoding="utf-8")
    assert f"({LID_U_X_M_S:g} 0 0)" in u_text


def test_run_d_fsi_broken_when_wall_pressure_is_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engineering_tools.c_facade import run_d_fsi

    probes = _d_matching_probes()
    probes["housing.wall.pressure"] = dict(probes["housing.wall.pressure"])
    probes["housing.wall.pressure"]["value"] = 0.0
    probes["housing.wall.traction"] = dict(probes["housing.wall.traction"])
    probes["housing.wall.traction"]["value"] = 0.0
    _d_tools(tmp_path, monkeypatch)
    _ab_snapshot_source(tmp_path / "ab")
    _d_patch_samples(monkeypatch, probes)
    session = run_d_fsi(ab_dir=tmp_path / "ab", out=tmp_path / "d-fsi", params=load_params())
    assert session["status"] == "broken"
    assert session["d_ok"] is False


def test_run_d_fsi_missing_without_pimplefoam(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engineering_tools.c_facade import run_d_fsi

    _d_tools(tmp_path, monkeypatch)
    (tmp_path / "bin" / "pimpleFoam").unlink()
    out = tmp_path / "d-fsi"
    session = run_d_fsi(ab_dir=tmp_path / "ab", out=out, params=load_params())
    assert session["status"] == "missing"
    assert session["d_ok"] is False
    assert (out / "d-session.json").is_file()
