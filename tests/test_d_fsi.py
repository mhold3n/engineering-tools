"""D-FSI mesh and façade tests. No live pimpleFoam except fakes."""

import json
from pathlib import Path

import pytest

from engineering_tools.c_adapter_openfoam import prepare_fluid_participant
from engineering_tools.c_fsi_meshes import canonical_xyz_m, write_c_fluid_case
from engineering_tools.d_fsi_meshes import (
    D_HEX_CELLS,
    LID_U_X_M_S,
    apply_driven_lid_u,
    write_d_fluid_case,
    write_d_solid_inp,
)
from engineering_tools.damper_params import load_params
from tests.test_c_fsi import (
    _ab_snapshot_source,
    _c_tools,
    _matching_probes,
    _patch_samples,
)


def test_d_fluid_keeps_interface_and_lid(tmp_path: Path) -> None:
    params = load_params()
    case = tmp_path / "d-foam"
    write_d_fluid_case(params, case)
    foam = (case / "constant" / "polyMesh" / "blockMeshDict").read_text(encoding="utf-8")
    assert "interface" in foam
    assert "lid" in foam
    assert f"hex (0 1 2 3 4 5 6 7) ({D_HEX_CELLS} {D_HEX_CELLS} {D_HEX_CELLS})" in foam
    assert "hex (0 1 2 3 4 5 6 7) (1 1 1)" not in foam
    wall = canonical_xyz_m(params)["housing.wall.pressure"]
    assert wall[0] == pytest.approx(-float(params["housing_id_mm"]) / 2000.0)


def test_d_solid_has_belt_cload_on_key_node(tmp_path: Path) -> None:
    params = load_params()
    path = tmp_path / "d-solid.inp"
    write_d_solid_inp(params, path)
    text = path.read_text(encoding="utf-8")
    assert "9, 2," in text
    assert "10, 1, 3" in text


def test_driven_lid_is_nonzero_after_prepare(tmp_path: Path) -> None:
    params = load_params()
    case = tmp_path / "d-foam"
    write_d_fluid_case(params, case)
    prepare_fluid_participant(case, tmp_path / "precice-config.xml")
    apply_driven_lid_u(case)
    u_text = (case / "0" / "U").read_text(encoding="utf-8")
    assert f"({LID_U_X_M_S:g} 0 0)" in u_text
    assert "lid { type noSlip; }" not in u_text


def test_c_idle_lid_stays_noslip(tmp_path: Path) -> None:
    """--coupling c must not pick up D lid speed."""
    params = load_params()
    case = tmp_path / "c-foam"
    write_c_fluid_case(params, case)
    prepare_fluid_participant(case, tmp_path / "precice-config.xml")
    u_text = (case / "0" / "U").read_text(encoding="utf-8")
    assert "lid { type noSlip; }" in u_text
    assert f"({LID_U_X_M_S:g} 0 0)" not in u_text


def test_run_d_fsi_persists_ok_when_probes_follow_b(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engineering_tools.c_facade import run_d_fsi

    _c_tools(tmp_path, monkeypatch)
    ab = tmp_path / "ab"
    _ab_snapshot_source(ab)
    _patch_samples(monkeypatch, _matching_probes())
    out = tmp_path / "d-fsi"
    session = run_d_fsi(ab_dir=ab, out=out, params=load_params())
    persisted = json.loads((out / "d-session.json").read_text(encoding="utf-8"))
    assert session["status"] == "ok"
    assert persisted["d_ok"] is True
    assert persisted["backend"] == "precice"
    u_text = (out / "d-fluid" / "0" / "U").read_text(encoding="utf-8")
    assert f"({LID_U_X_M_S:g} 0 0)" in u_text


def test_run_d_fsi_broken_when_wall_pressure_is_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engineering_tools.c_facade import run_d_fsi

    probes = _matching_probes()
    probes["housing.wall.pressure"] = dict(probes["housing.wall.pressure"])
    probes["housing.wall.pressure"]["value"] = 0.0
    probes["housing.wall.traction"] = dict(probes["housing.wall.traction"])
    probes["housing.wall.traction"]["value"] = 0.0
    _c_tools(tmp_path, monkeypatch)
    _ab_snapshot_source(tmp_path / "ab")
    _patch_samples(monkeypatch, probes)
    session = run_d_fsi(ab_dir=tmp_path / "ab", out=tmp_path / "d-fsi", params=load_params())
    assert session["status"] == "broken"
    assert session["d_ok"] is False


def test_run_d_fsi_missing_without_pimplefoam(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engineering_tools.c_facade import run_d_fsi

    _c_tools(tmp_path, monkeypatch)
    binary_dir = tmp_path / "bin"
    (binary_dir / "pimpleFoam").unlink()
    out = tmp_path / "d-fsi"
    session = run_d_fsi(ab_dir=tmp_path / "ab", out=out, params=load_params())
    assert session["status"] == "missing"
    assert session["d_ok"] is False
    assert (out / "d-session.json").is_file()
