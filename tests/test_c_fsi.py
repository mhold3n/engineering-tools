"""C-FSI mesh and façade session tests.

Agents: mesh tests pin metres from damper-params probes and the shared
interface name. Façade tests monkeypatch adapter sample_c_probes so CI
does not need OpenFOAM to write JSON. precice is launched only by the
backend adapter, never by damper_scenario.py.
"""

import json
import os
from pathlib import Path

import pytest

from engineering_tools.c_fsi_meshes import canonical_xyz_m, write_c_fluid_case, write_c_solid_inp
from engineering_tools.c_parity import load_c_fsi_bands
from engineering_tools.damper_params import load_params


def test_canonical_xyz_matches_params_in_metres() -> None:
    params = load_params()
    xyz = canonical_xyz_m(params)
    wall = xyz["housing.wall.pressure"]
    assert wall[0] == pytest.approx(-float(params["housing_id_mm"]) / 2000.0)


def test_c_solid_and_fluid_share_interface_name(tmp_path: Path) -> None:
    params = load_params()
    write_c_solid_inp(params, tmp_path / "c-solid.inp")
    write_c_fluid_case(params, tmp_path / "c-foam")
    inp = (tmp_path / "c-solid.inp").read_text(encoding="utf-8")
    foam = (tmp_path / "c-foam" / "constant" / "polyMesh" / "blockMeshDict").read_text(encoding="utf-8")
    assert "interface" in inp.lower() or "INTERFACE" in inp
    assert "interface" in foam
    # Named interface is the chamber_wall −X plane (mm in the deck, m in blockMesh).
    assert "-25.000000" in inp
    start = foam.index("\n    interface\n")
    iface = foam[start:foam.index("\n    walls\n", start)]
    assert "(0 4 7 3)" in iface


def _executable(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _c_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, precice: bool = True) -> None:
    """PATH extras: ccx, pimpleFoam, blockMesh, and optional precice all exit 0."""
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    _executable(binary_dir / "ccx", "exit 0\n")
    _executable(binary_dir / "pimpleFoam", "exit 0\n")
    _executable(binary_dir / "blockMesh", "mkdir -p constant/polyMesh\ntouch constant/polyMesh/points\nexit 0\n")
    if precice:
        _executable(binary_dir / "precice", "exit 0\n")
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")


def _ab_snapshot_source(path: Path) -> None:
    """Minimal A/B pair whose B wall Pa and key-root MPa match the C fake probes."""
    path.mkdir(parents=True, exist_ok=True)
    product = {
        "probes": {
            "chamber_wall": {"cfd": {"p": 56.62}},
            "keyway_root": {"fea_mapped": {"von_mises": 10.07}},
        }
    }
    (path / "product-state.json").write_text(json.dumps(product) + "\n", encoding="utf-8")
    (path / "scenario-report.json").write_text('{"a_ok": true, "b_ok": true}\n', encoding="utf-8")


def _matching_probes() -> dict:
    canonical = canonical_xyz_m(load_params())
    return {
        "housing.wall.pressure": {"value": 56.62, "xyz_m": canonical["housing.wall.pressure"]},
        "key.root.von_mises": {"value": 10.07e6, "xyz_m": canonical["key.root.von_mises"]},
        "housing.wall.displacement": {"value": 1e-6, "xyz_m": canonical["housing.wall.displacement"]},
        "housing.wall.traction": {"value": 56.62, "xyz_m": canonical["housing.wall.traction"]},
    }


def _patch_samples(monkeypatch: pytest.MonkeyPatch, probes: dict) -> None:
    """Both adapters return the same SI probe dict; the façade merges them."""

    def _sample(_out: Path) -> dict:
        return probes

    monkeypatch.setattr("engineering_tools.c_adapter_calculix.sample_c_probes", _sample)
    monkeypatch.setattr("engineering_tools.c_adapter_openfoam.sample_c_probes", _sample)


def test_run_c_fsi_persists_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engineering_tools.c_facade import run_c_fsi

    _c_tools(tmp_path, monkeypatch)
    ab = tmp_path / "ab"
    _ab_snapshot_source(ab)
    _patch_samples(monkeypatch, _matching_probes())
    out = tmp_path / "c-fsi"
    session = run_c_fsi(ab_dir=ab, out=out, params=load_params())
    persisted = json.loads((out / "c-session.json").read_text(encoding="utf-8"))
    assert session["status"] == "ok"
    assert persisted["status"] == "ok"
    assert persisted["c_ok"] is True
    assert persisted["backend"] == "precice"
    n_steps = int(load_c_fsi_bands()["n_steps"])
    assert len(persisted["steps"]) == n_steps
    assert all(step["converged"] is True for step in persisted["steps"])
    for name, row in _matching_probes().items():
        assert persisted["probes"][name]["value"] == pytest.approx(row["value"])
    assert persisted["parity"]
    assert all(row["ok"] is True for row in persisted["parity"])
    assert len(persisted["snapshot_digest"]) == 64


def test_run_c_fsi_missing_without_precice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engineering_tools.c_facade import run_c_fsi

    _c_tools(tmp_path, monkeypatch, precice=False)
    out = tmp_path / "c-fsi"
    session = run_c_fsi(ab_dir=tmp_path / "ab", out=out, params=load_params())
    assert session["status"] == "missing"
    assert session["evaluated"] is True
    assert session["c_ok"] is False
    persisted = json.loads((out / "c-session.json").read_text(encoding="utf-8"))
    assert persisted["status"] == "missing"


def test_run_c_fsi_broken_when_backend_step_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engineering_tools.c_facade import run_c_fsi

    _c_tools(tmp_path, monkeypatch)
    _ab_snapshot_source(tmp_path / "ab")
    _patch_samples(monkeypatch, _matching_probes())
    monkeypatch.setattr("engineering_tools.c_backend_precice.run_step", lambda *_args, **_kwargs: False)
    session = run_c_fsi(ab_dir=tmp_path / "ab", out=tmp_path / "c-fsi", params=load_params())
    assert session["status"] == "broken"
    assert session["c_ok"] is False


def test_run_c_fsi_broken_when_displacement_is_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engineering_tools.c_facade import run_c_fsi

    probes = _matching_probes()
    probes["housing.wall.displacement"] = dict(probes["housing.wall.displacement"])
    probes["housing.wall.displacement"]["value"] = 0.0
    _c_tools(tmp_path, monkeypatch)
    _ab_snapshot_source(tmp_path / "ab")
    _patch_samples(monkeypatch, probes)
    session = run_c_fsi(ab_dir=tmp_path / "ab", out=tmp_path / "c-fsi", params=load_params())
    assert session["status"] == "broken"
    assert session["c_ok"] is False


def test_run_c_fsi_broken_when_pressure_out_of_band(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engineering_tools.c_facade import run_c_fsi

    probes = _matching_probes()
    probes["housing.wall.pressure"] = dict(probes["housing.wall.pressure"])
    probes["housing.wall.pressure"]["value"] = 1e20
    _c_tools(tmp_path, monkeypatch)
    _ab_snapshot_source(tmp_path / "ab")
    _patch_samples(monkeypatch, probes)
    session = run_c_fsi(ab_dir=tmp_path / "ab", out=tmp_path / "c-fsi", params=load_params())
    assert session["status"] == "broken"
    assert session["c_ok"] is False
    assert any(row["ok"] is False for row in session["parity"])


def test_scenario_module_does_not_spawn_precice() -> None:
    text = Path("src/engineering_tools/damper_scenario.py").read_text(encoding="utf-8")
    assert "precice" not in text.lower()
