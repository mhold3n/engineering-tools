"""U11 mechanical discretization stability. Comparator only; no live solvers."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from engineering_tools.e_verify import (
    FORCE_SIGN,
    MAPPING_CONSERVATION_TOLERANCE,
    MAPPING_RESIDUAL_CONVENTION,
    MAPPING_RESIDUAL_FORMULA,
    MAPPING_RESIDUAL_KIND,
    RELATIVE_TOLERANCE,
    compare_refinement,
    dumps_report,
    parse_backend_version,
    run_live_refinement_pair,
    vector_conservation_residual,
)

ENTITY = "face.inner_wall"

_VERSIONS = {
    "gmsh": "4.13.1",
    "calculix": "2.21",
    "openfoam": "v2512",
    "precice": "3.4.1",
}

_ADAPTER = {
    "bc_id": "adapter.outer_fixed",
    "entity_id": "face.outer_wall",
    "kind": "fixed_displacement",
    "value": [0.0, 0.0, 0.0],
    "unit": "m",
    "dofs": [1, 2, 3],
    "source": "e_adapter_calculix.write_e_solid_inp",
    "rule": "r >= 0.0235 m and node not on NinterfaceN",
}


def _mid(tag: str) -> str:
    return "sha256:" + hashlib.sha256(tag.encode("utf-8")).hexdigest()


def _xyz(n: int, scale: float) -> list[list[float]]:
    return [[scale, float(i) * 0.001, 0.0] for i in range(n)]


def _bcs() -> dict:
    return {
        "canonical_bcs": [
            {
                "bc_id": "shell.outer_fixed",
                "entity_id": "face.outer_wall",
                "kind": "fixed_displacement",
                "value": [0.0, 0.0, 0.0],
                "unit": "m",
            }
        ],
        "region_motion": [
            {"region_id": "shell", "entity_id": "body.shell", "motion_model": "deformable_motion"}
        ],
        "adapter_constraints": [dict(_ADAPTER)],
    }


def _meas(*, force: float = 9.0, disp: float = 1.0e-8, residual: float = 0.02) -> dict:
    solid_net = [residual, 0.0, 0.0]
    fluid_net = [0.0, 0.0, 0.0]
    source_l1 = 1.0
    return {
        "integrated_interface_force": {
            "value": force,
            "unit": "N",
            "entity_id": ENTITY,
            "kind": "integrated_traction_magnitude",
            "l1_N": force,
            "net_components_N": [0.0, 0.0, 0.0],
            "net_magnitude_N": 0.0,
            "components_N": [0.0, 0.0, 0.0],
        },
        "max_interface_displacement": {
            "value": disp,
            "unit": "m",
            "entity_id": ENTITY,
            "kind": "max_magnitude",
        },
        "mapping_residual": {
            "value": residual,
            "unit": "1",
            "entity_id": ENTITY,
            "kind": MAPPING_RESIDUAL_KIND,
            "formula": MAPPING_RESIDUAL_FORMULA,
            "convention": MAPPING_RESIDUAL_CONVENTION,
            "dimensionless": True,
            "solid_components_N": solid_net,
            "fluid_components_N": fluid_net,
            "solid_l1_N": source_l1,
            "fluid_l1_N": source_l1,
        },
    }


def _session(
    *,
    fingerprint: str = "fp-a",
    topology_version: int = 1,
    materials: list | None = None,
    bcs: dict | None = None,
    loads: list | None = None,
    coupling_kind: str = "implicit two-way",
    convergence_measures: dict | None = None,
    aitken_data: list | None = None,
    aitken_initial_relaxation: float = 0.5,
    max_iterations: int = 100,
    t_end: float = 0.02,
    h_max: float = 0.012,
    solid_mesh_id: str | None = None,
    fluid_mesh_id: str | None = None,
    n_solid: int = 3,
    n_fluid: int = 2,
    solid_xyz: list | None = None,
    fluid_xyz: list | None = None,
    dt: float = 0.01,
    solver_dt: float | None = None,
    expected_windows: int = 2,
    completed_windows: int = 2,
    terminal_coupling_status: str = "completed",
    force: float = 9.0,
    disp: float = 1.0e-8,
    residual: float = 0.02,
    versions: dict | None = None,
    entity_id: str = ENTITY,
    status: str = "ok",
    e_ok: bool = True,
    live: bool = True,
) -> dict:
    ns = n_solid
    nf = n_fluid
    return {
        "status": status,
        "e_ok": e_ok,
        "live": live,
        "problem": {
            "cad_fingerprint": fingerprint,
            "topology_version": topology_version,
            "materials": list(materials if materials is not None else ["steel", "air"]),
            "boundary_conditions": dict(bcs if bcs is not None else _bcs()),
            "loads": list(loads if loads is not None else [{"quantity": "pressure", "value": 1.01e5, "entity_id": ENTITY}]),
            "coupling_kind": coupling_kind,
            "convergence_measures": dict(
                convergence_measures
                if convergence_measures is not None
                else {"relative": 1.0e-4, "data": ["Force"]}
            ),
            "aitken_data": list(aitken_data if aitken_data is not None else ["Force"]),
            "aitken_initial_relaxation": aitken_initial_relaxation,
            "max_iterations": max_iterations,
            "t_end": t_end,
            "entity_id": entity_id,
            "effective_solver_pressure_Pa": 1.01e5,
        },
        "discretization": {
            "h_max": h_max,
            "solid_mesh_id": solid_mesh_id or _mid("solid-default"),
            "fluid_mesh_id": fluid_mesh_id or _mid("fluid-default"),
            "solid_interface_vertex_count": ns,
            "fluid_interface_facecenter_count": nf,
            "solid_interface_vertices": solid_xyz if solid_xyz is not None else _xyz(ns, -0.02),
            "fluid_interface_facecenters": fluid_xyz if fluid_xyz is not None else _xyz(nf, -0.02),
            "dt": dt,
            "solver_dt": float(solver_dt if solver_dt is not None else dt),
            "expected_windows": expected_windows,
            "completed_windows": completed_windows,
            "terminal_coupling_status": terminal_coupling_status,
        },
        "measurements": _meas(force=force, disp=disp, residual=residual),
        "provenance": {"backend_versions": dict(versions if versions is not None else _VERSIONS)},
    }


def _spatial_pair(**fine_kw) -> tuple[dict, dict]:
    coarse = _session(h_max=0.012, n_solid=3, n_fluid=2, solid_mesh_id=_mid("s-c"), fluid_mesh_id=_mid("f-c"))
    fine = _session(
        h_max=0.006,
        n_solid=8,
        n_fluid=5,
        solid_mesh_id=_mid("s-f"),
        fluid_mesh_id=_mid("f-f"),
        force=9.4,
        **fine_kw,
    )
    return coarse, fine


def _temporal_pair(**fine_kw) -> tuple[dict, dict]:
    mesh = dict(
        h_max=0.012,
        n_solid=4,
        n_fluid=3,
        solid_mesh_id=_mid("s-same"),
        fluid_mesh_id=_mid("f-same"),
        solid_xyz=_xyz(4, -0.02),
        fluid_xyz=_xyz(3, -0.02),
    )
    coarse = _session(dt=0.01, expected_windows=2, completed_windows=2, t_end=0.02, **mesh)
    fine = _session(
        dt=0.005,
        expected_windows=4,
        completed_windows=4,
        t_end=0.02,
        force=9.1,
        **mesh,
        **fine_kw,
    )
    return coarse, fine


def test_spatial_same_problem_definition_passes() -> None:
    coarse, fine = _spatial_pair()
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["same_problem_definition"] is True
    assert got["ok"] is True
    assert got["record_valid"] is True
    assert got["within_tolerance"] is True


def test_spatial_h_max_is_012_and_006() -> None:
    coarse, fine = _spatial_pair()
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["coarse"]["h_max"] == 0.012
    assert got["fine"]["h_max"] == 0.006


def test_unchanged_solid_interface_count_fails() -> None:
    coarse, fine = _spatial_pair()
    fine["discretization"]["solid_interface_vertex_count"] = 3
    fine["discretization"]["solid_interface_vertices"] = _xyz(3, -0.02)
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["ok"] is False
    assert "solid_interface_vertex_count" in got["differences"]


def test_unchanged_fluid_interface_count_fails() -> None:
    coarse, fine = _spatial_pair()
    fine["discretization"]["fluid_interface_facecenter_count"] = 2
    fine["discretization"]["fluid_interface_facecenters"] = _xyz(2, -0.02)
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["ok"] is False
    assert "fluid_interface_facecenter_count" in got["differences"]


def test_fine_counts_lower_than_coarse_fail() -> None:
    coarse, fine = _spatial_pair()
    fine["discretization"]["solid_interface_vertex_count"] = 2
    fine["discretization"]["solid_interface_vertices"] = _xyz(2, -0.02)
    fine["discretization"]["fluid_interface_facecenter_count"] = 1
    fine["discretization"]["fluid_interface_facecenters"] = _xyz(1, -0.02)
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["ok"] is False


def test_different_cad_fingerprint_fails() -> None:
    coarse, fine = _spatial_pair()
    fine["problem"]["cad_fingerprint"] = "fp-other"
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["same_problem_definition"] is False
    assert "cad_fingerprint" in got["differences"]
    assert got["ok"] is False


def test_different_topology_version_fails() -> None:
    coarse, fine = _spatial_pair()
    fine["problem"]["topology_version"] = 2
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["same_problem_definition"] is False
    assert "topology_version" in got["differences"]


def test_different_material_bc_load_fails() -> None:
    coarse, fine = _spatial_pair()
    fine["problem"]["materials"] = ["aluminium", "air"]
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["same_problem_definition"] is False
    assert "materials" in got["differences"]
    fine = _spatial_pair()[1]
    fine["problem"]["boundary_conditions"]["canonical_bcs"][0]["entity_id"] = "face.lid"
    got = compare_refinement(coarse, fine, kind="spatial")
    assert "boundary_conditions" in got["differences"]
    fine = _spatial_pair()[1]
    fine["problem"]["loads"] = [{"quantity": "pressure", "value": 2.0e5, "entity_id": ENTITY}]
    got = compare_refinement(coarse, fine, kind="spatial")
    assert "loads" in got["differences"]


def test_bc_entity_or_value_change_fails_same_problem() -> None:
    coarse, fine = _spatial_pair()
    fine["problem"]["boundary_conditions"]["canonical_bcs"][0]["value"] = [1.0, 0.0, 0.0]
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["same_problem_definition"] is False
    assert "boundary_conditions" in got["differences"]
    assert got["ok"] is False


def test_different_coupling_physics_fails() -> None:
    coarse, fine = _spatial_pair()
    fine["problem"]["coupling_kind"] = "explicit two-way"
    assert "coupling_kind" in compare_refinement(coarse, fine, kind="spatial")["differences"]
    fine = _spatial_pair()[1]
    fine["problem"]["convergence_measures"] = {"relative": 1.0e-3, "data": ["Force"]}
    assert "convergence_measures" in compare_refinement(coarse, fine, kind="spatial")["differences"]
    fine = _spatial_pair()[1]
    fine["problem"]["aitken_data"] = ["Displacement"]
    assert "aitken_data" in compare_refinement(coarse, fine, kind="spatial")["differences"]
    fine = _spatial_pair()[1]
    fine["problem"]["max_iterations"] = 50
    assert "max_iterations" in compare_refinement(coarse, fine, kind="spatial")["differences"]
    fine = _spatial_pair()[1]
    fine["problem"]["t_end"] = 0.04
    assert "t_end" in compare_refinement(coarse, fine, kind="spatial")["differences"]


def test_temporal_one_mesh_and_window_arithmetic() -> None:
    coarse, fine = _temporal_pair()
    got = compare_refinement(coarse, fine, kind="temporal")
    assert got["ok"] is True
    assert got["same_problem_definition"] is True
    assert got["coarse"]["dt"] == 0.01
    assert got["fine"]["dt"] == 0.005
    assert got["coarse"]["solver_dt"] == 0.01
    assert got["fine"]["solver_dt"] == 0.005
    assert got["coarse"]["expected_windows"] == 2
    assert got["fine"]["expected_windows"] == 4
    assert got["coarse"]["t_end"] == pytest.approx(0.02)
    assert coarse["problem"]["t_end"] == pytest.approx(coarse["discretization"]["dt"] * 2)
    assert fine["problem"]["t_end"] == pytest.approx(fine["discretization"]["dt"] * 4)


def test_temporal_mesh_id_or_h_max_change_fails() -> None:
    coarse, fine = _temporal_pair()
    fine["discretization"]["h_max"] = 0.006
    got = compare_refinement(coarse, fine, kind="temporal")
    assert got["same_problem_definition"] is False
    assert "h_max" in got["differences"]
    coarse, fine = _temporal_pair()
    fine["discretization"]["solid_mesh_id"] = _mid("other")
    got = compare_refinement(coarse, fine, kind="temporal")
    assert "solid_mesh_id" in got["differences"]


def test_temporal_max_iterations_change_fails() -> None:
    coarse, fine = _temporal_pair()
    fine["problem"]["max_iterations"] = 80
    got = compare_refinement(coarse, fine, kind="temporal")
    assert got["same_problem_definition"] is False
    assert "max_iterations" in got["differences"]


def test_temporal_physical_time_change_fails() -> None:
    coarse, fine = _temporal_pair()
    fine["problem"]["t_end"] = 0.04
    fine["discretization"]["expected_windows"] = 8
    fine["discretization"]["completed_windows"] = 8
    got = compare_refinement(coarse, fine, kind="temporal")
    assert got["same_problem_definition"] is False
    assert "t_end" in got["differences"]


def test_incomplete_windows_fail() -> None:
    coarse, fine = _spatial_pair()
    coarse["discretization"]["completed_windows"] = 1
    coarse["discretization"]["terminal_coupling_status"] = "incomplete"
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["ok"] is False
    assert "completed_windows" in got["differences"]
    coarse, fine = _temporal_pair()
    fine["discretization"]["completed_windows"] = 3
    got = compare_refinement(coarse, fine, kind="temporal")
    assert got["ok"] is False


def test_coordinate_array_count_mismatch_fails() -> None:
    coarse, fine = _spatial_pair()
    fine["discretization"]["solid_interface_vertices"] = _xyz(3, -0.02)
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["ok"] is False
    assert "solid_interface_vertices" in got["differences"]


def test_wrong_entity_id_fails() -> None:
    coarse, fine = _spatial_pair()
    fine["problem"]["entity_id"] = "face.outer_wall"
    fine["measurements"]["integrated_interface_force"]["entity_id"] = "face.outer_wall"
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["ok"] is False
    assert "entity_id" in got["differences"]


def test_three_quantities_have_coarse_fine_relative_change() -> None:
    coarse, fine = _spatial_pair()
    got = compare_refinement(coarse, fine, kind="spatial")
    names = {row["name"] for row in got["quantities"]}
    assert names == {
        "integrated_interface_force",
        "max_interface_displacement",
        "mapping_residual",
    }
    force = next(r for r in got["quantities"] if r["name"] == "integrated_interface_force")
    assert force["coarse"] == 9.0
    assert force["fine"] == 9.4
    assert force["relative_change"] == pytest.approx(abs(9.4 - 9.0) / abs(9.4))
    assert force["unit"] == "N"
    assert force["relative_tolerance"] == RELATIVE_TOLERANCE
    assert force["within_tolerance"] is True


def test_force_conservation_residual_zero_and_undefined() -> None:
    from engineering_tools.e_verify import mapping_l1_residual

    zero = {"l1_N": 0.0, "components_N": [0.0, 0.0, 0.0]}
    assert mapping_l1_residual(zero, zero) == 0.0
    assert mapping_l1_residual({"l1_N": 1.0, "components_N": [1.0, 0.0, 0.0]}, {"l1_N": 1.0, "components_N": [0.0, 0.0, 0.0]}) == 1.0
    assert mapping_l1_residual(None, zero) is None


def test_zero_zero_relative_change_is_zero() -> None:
    coarse, fine = _spatial_pair()
    for session in (coarse, fine):
        session["measurements"]["mapping_residual"]["value"] = 0.0
        session["measurements"]["mapping_residual"]["solid_components_N"] = [0.0, 0.0, 0.0]
        session["measurements"]["mapping_residual"]["fluid_components_N"] = [0.0, 0.0, 0.0]
    got = compare_refinement(coarse, fine, kind="spatial")
    row = next(r for r in got["quantities"] if r["name"] == "mapping_residual")
    assert row["relative_change"] == 0.0
    assert row["within_tolerance"] is True


def test_nonzero_over_zero_serializes_without_nan_or_infinity() -> None:
    coarse, fine = _spatial_pair()
    coarse["measurements"]["mapping_residual"]["value"] = 0.02
    coarse["measurements"]["mapping_residual"]["solid_components_N"] = [0.02, 0.0, 0.0]
    fine["measurements"]["mapping_residual"]["value"] = 0.0
    fine["measurements"]["mapping_residual"]["solid_components_N"] = [0.0, 0.0, 0.0]
    got = compare_refinement(coarse, fine, kind="spatial")
    text = dumps_report(got)
    assert "NaN" not in text
    assert "Infinity" not in text
    assert "inf" not in text.lower()
    row = next(r for r in got["quantities"] if r["name"] == "mapping_residual")
    assert row["relative_change"] is None
    assert got["ok"] is False


def test_run_live_refinement_pair_two_independent_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def _fake_session(out, model, **kwargs):
        del model
        calls.append({"out": Path(out).name, **kwargs})
        if kwargs.get("h_max") == 0.006:
            return _spatial_pair()[1]
        return _spatial_pair()[0]

    monkeypatch.setattr("engineering_tools.e_facade.run_e_session", _fake_session)
    got = run_live_refinement_pair(tmp_path / "pair", {"unused": True}, kind="spatial")
    assert [c["out"] for c in calls] == ["coarse", "fine"]
    assert calls[0]["h_max"] == 0.012
    assert calls[1]["h_max"] == 0.006
    assert (tmp_path / "pair" / "e-refine.json").is_file()
    assert got["ok"] is True


def test_run_live_refinement_pair_temporal_orchestration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def _fake_session(out, model, **kwargs):
        del model
        calls.append({"out": Path(out).name, **kwargs})
        if kwargs.get("time_window_s") == 0.005:
            return _temporal_pair()[1]
        return _temporal_pair()[0]

    monkeypatch.setattr("engineering_tools.e_facade.run_e_session", _fake_session)
    got = run_live_refinement_pair(tmp_path / "tpair", {}, kind="temporal")
    assert [c["out"] for c in calls] == ["coarse", "fine"]
    assert calls[0]["time_window_s"] == 0.01
    assert calls[1]["time_window_s"] == 0.005
    assert calls[0]["h_max"] == 0.012
    assert calls[1]["h_max"] == 0.012
    assert got["ok"] is True


def test_pair_records_provenance_and_backend_versions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "engineering_tools.e_facade.run_e_session",
        lambda out, model, **kwargs: _spatial_pair()[0] if kwargs.get("h_max") == 0.012 else _spatial_pair()[1],
    )
    got = run_live_refinement_pair(tmp_path / "prov", {}, kind="spatial")
    assert "gmsh" in got["coarse_provenance"]["backend_versions"]
    assert "calculix" in got["fine_provenance"]["backend_versions"]
    assert got["coarse_provenance"]["backend_versions"]["precice"] == "3.4.1"


def test_comparator_does_not_read_thermal_ics_or_band_files() -> None:
    src = Path("src/engineering_tools/e_verify.py").read_text(encoding="utf-8")
    assert "e-fsi-bands" not in src
    assert "101325" not in src
    assert "heat_flux" not in src.lower()
    assert "wall_temperature" not in src
    coarse, fine = _spatial_pair()
    coarse["probes"] = {
        "face.inner_wall.pressure": {"value": 101325.0},
        "face.inner_wall.temperature": {"value": 350.0},
    }
    fine["probes"] = dict(coarse["probes"])
    got = compare_refinement(coarse, fine, kind="spatial")
    names = {row["name"] for row in got["quantities"]}
    assert "pressure" not in names
    assert "temperature" not in names


def test_unknown_kind_rejected() -> None:
    coarse, fine = _spatial_pair()
    got = compare_refinement(coarse, fine, kind="hp-adaptivity")
    assert got["ok"] is False
    assert got["same_problem_definition"] is False


def test_equal_broken_mapping_residual_fails_despite_zero_relative_change() -> None:
    coarse, fine = _spatial_pair()
    for session in (coarse, fine):
        session["measurements"]["mapping_residual"]["value"] = 1.0
        session["measurements"]["mapping_residual"]["solid_components_N"] = [1.0, 0.0, 0.0]
        session["measurements"]["mapping_residual"]["fluid_components_N"] = [0.0, 0.0, 0.0]
        session["measurements"]["mapping_residual"]["fluid_l1_N"] = 1.0
    got = compare_refinement(coarse, fine, kind="spatial")
    row = next(r for r in got["quantities"] if r["name"] == "mapping_residual")
    assert row["relative_change"] == 0.0
    assert row["within_tolerance"] is False
    assert row["conservation_tolerance"] == MAPPING_CONSERVATION_TOLERANCE
    assert got["ok"] is False
    assert "mapping_residual" in got["differences"]


def test_broken_mock_and_non_live_sessions_fail() -> None:
    coarse, fine = _spatial_pair()
    coarse["status"] = "broken"
    coarse["e_ok"] = False
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["ok"] is False
    assert "coarse_session_status" in got["differences"]
    coarse, fine = _spatial_pair()
    fine["status"] = "mock"
    fine["e_ok"] = False
    fine["live"] = False
    got = compare_refinement(coarse, fine, kind="spatial")
    assert "fine_session_status" in got["differences"]
    assert "fine_not_live" in got["differences"]
    coarse, fine = _spatial_pair()
    coarse["live"] = False
    got = compare_refinement(coarse, fine, kind="spatial")
    assert "coarse_not_live" in got["differences"]
    assert got["ok"] is False


@pytest.mark.parametrize("payload", [math.nan, math.inf, -math.inf])
def test_nonfinite_quantity_fails_and_serializes(payload: float) -> None:
    coarse, fine = _spatial_pair()
    fine["measurements"]["integrated_interface_force"]["value"] = payload
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["ok"] is False
    assert "integrated_interface_force" in got["differences"]
    row = next(r for r in got["quantities"] if r["name"] == "integrated_interface_force")
    assert row["relative_change"] is None
    dumps_report(got)


def test_spatial_and_temporal_solver_dt_mismatch_fail() -> None:
    coarse, fine = _spatial_pair()
    fine["discretization"]["solver_dt"] = 0.005
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["ok"] is False
    assert "solver_dt" in got["differences"]
    coarse, fine = _temporal_pair()
    fine["discretization"]["solver_dt"] = 0.01
    got = compare_refinement(coarse, fine, kind="temporal")
    assert got["ok"] is False
    assert "solver_dt" in got["differences"]


def test_spatial_wrong_horizon_arithmetic_fails() -> None:
    coarse, fine = _spatial_pair()
    fine["problem"]["t_end"] = 0.03
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["ok"] is False
    assert "t_end" in got["differences"]


def test_identical_or_missing_spatial_mesh_ids_fail() -> None:
    coarse, fine = _spatial_pair()
    fine["discretization"]["solid_mesh_id"] = coarse["discretization"]["solid_mesh_id"]
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["ok"] is False
    assert "solid_mesh_id" in got["differences"]
    coarse, fine = _spatial_pair()
    for session in (coarse, fine):
        session["discretization"]["fluid_mesh_id"] = None
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["ok"] is False
    assert "fluid_mesh_id" in got["differences"]


@pytest.mark.parametrize(
    "field",
    [
        "cad_fingerprint",
        "topology_version",
        "materials",
        "boundary_conditions",
        "loads",
        "coupling_kind",
        "convergence_measures",
        "aitken_data",
        "max_iterations",
        "solid_mesh_id",
        "fluid_mesh_id",
    ],
)
def test_missing_field_on_both_sessions_fails(field: str) -> None:
    coarse, fine = _spatial_pair()
    for session in (coarse, fine):
        if field in session["problem"]:
            session["problem"][field] = None if field != "topology_version" else 0
        if field in session["discretization"]:
            session["discretization"][field] = None
        if field == "aitken_data":
            session["problem"]["aitken_initial_relaxation"] = None
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["ok"] is False
    assert field in got["differences"] or "aitken_data" in got["differences"]


def test_wrong_force_unit_kind_and_formula_fail() -> None:
    coarse, fine = _spatial_pair()
    fine["measurements"]["integrated_interface_force"]["unit"] = "Pa"
    fine["measurements"]["integrated_interface_force"]["kind"] = "point_sample"
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["ok"] is False
    assert "integrated_interface_force" in got["differences"]
    coarse, fine = _spatial_pair()
    fine["measurements"]["mapping_residual"]["formula"] = "iteration-count"
    got = compare_refinement(coarse, fine, kind="spatial")
    assert "mapping_residual" in got["differences"]
    assert got["ok"] is False


def test_parse_backend_version_cases() -> None:
    assert parse_backend_version("precice", "WARNING: deprecated\n3.2.0\n") == "3.2.0"
    assert parse_backend_version("openfoam", "Usage: rhoPimpleFoam [OPTIONS]") is None
    assert parse_backend_version("gmsh", None) is None
    assert parse_backend_version("gmsh", "") is None
    assert parse_backend_version("gmsh", "4.12.1") == "4.12.1"
    assert parse_backend_version("calculix", "This is Version 2.20") == "2.20"
    assert parse_backend_version("openfoam", "Version: 2512") == "2512"


def test_parse_backend_version_ignores_host_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WM_PROJECT_VERSION", "v9999")
    assert parse_backend_version("openfoam", "Usage: rhoPimpleFoam [OPTIONS]") is None


def test_different_backend_versions_invalidate_same_analysis() -> None:
    coarse, fine = _spatial_pair()
    fine["provenance"]["backend_versions"] = dict(_VERSIONS, openfoam="v9999")
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["record_valid"] is False
    assert "backend_versions" in got["problem_definition_differences"]
    assert got["ok"] is False


def test_equal_l1_different_vector_sums_fail_conservation() -> None:
    coarse, fine = _spatial_pair()
    for session in (coarse, fine):
        row = session["measurements"]["mapping_residual"]
        row["solid_components_N"] = [0.0, 0.0, 0.0]
        row["fluid_components_N"] = [1.0, 1.0, 0.0]
        row["solid_l1_N"] = 2.0
        row["fluid_l1_N"] = 2.0
        row["value"] = vector_conservation_residual(
            solid_net=(0.0, 0.0, 0.0), fluid_net=(1.0, 1.0, 0.0), source_l1=2.0
        )
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["ok"] is False
    assert "mapping_residual" in got["acceptance_failures"]


def test_matching_vector_sums_pass_despite_l1_mismatch() -> None:
    coarse, fine = _spatial_pair()
    for session in (coarse, fine):
        row = session["measurements"]["mapping_residual"]
        row["solid_components_N"] = [1.0, 0.0, 0.0]
        row["fluid_components_N"] = [1.0, 0.0, 0.0]
        row["solid_l1_N"] = 100.0
        row["fluid_l1_N"] = 10.0
        row["value"] = 0.0
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["record_valid"] is True
    row = next(r for r in got["quantities"] if r["name"] == "mapping_residual")
    assert row["within_tolerance"] is True
    assert row["load_magnitude_consistency_coarse"] == pytest.approx(0.9)


def test_force_sign_same_direction_not_action_reaction() -> None:
    same = vector_conservation_residual(solid_net=(1.0, 0.0, 0.0), fluid_net=(1.0, 0.0, 0.0), source_l1=1.0, sign=1)
    opposite = vector_conservation_residual(solid_net=(1.0, 0.0, 0.0), fluid_net=(1.0, 0.0, 0.0), source_l1=1.0, sign=-1)
    assert FORCE_SIGN == 1
    assert same == pytest.approx(0.0)
    assert opposite == pytest.approx(2.0)


def test_closed_cylinder_near_zero_net_uses_l1_denominator() -> None:
    residual = vector_conservation_residual(
        solid_net=(3e-5, 0.0, 0.0), fluid_net=(0.0, 0.0, 0.0), source_l1=500.0
    )
    assert residual == pytest.approx(3e-5 / 500.0)
    assert residual < MAPPING_CONSERVATION_TOLERANCE


def test_forged_and_negative_residual_fail() -> None:
    coarse, fine = _spatial_pair()
    for session in (coarse, fine):
        row = session["measurements"]["mapping_residual"]
        row["value"] = 0.001
        row["solid_l1_N"] = 100.0
        row["fluid_l1_N"] = 1.0
        row["solid_components_N"] = [100.0, 0.0, 0.0]
        row["fluid_components_N"] = [0.0, 0.0, 0.0]
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["record_valid"] is False
    assert "mapping_residual" in got["validation_errors"]
    coarse, fine = _spatial_pair()
    for session in (coarse, fine):
        session["measurements"]["mapping_residual"]["value"] = -1.0
        session["measurements"]["mapping_residual"]["solid_components_N"] = [0.0, 0.0, 0.0]
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["ok"] is False
    assert got["record_valid"] is False


def test_wrong_formula_plus_excessive_residual_is_invalid_record() -> None:
    coarse, fine = _spatial_pair()
    for session in (coarse, fine):
        session["measurements"]["mapping_residual"]["formula"] = "wrong"
        session["measurements"]["mapping_residual"]["value"] = 1.0
        session["measurements"]["mapping_residual"]["solid_components_N"] = [1.0, 0.0, 0.0]
        session["measurements"]["mapping_residual"]["fluid_l1_N"] = 1.0
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["record_valid"] is False
    assert got["within_tolerance"] is False


def test_wrong_force_unit_plus_excessive_relative_change_is_invalid_record() -> None:
    coarse, fine = _spatial_pair()
    fine["measurements"]["integrated_interface_force"]["unit"] = "Pa"
    fine["measurements"]["integrated_interface_force"]["kind"] = "point_sample"
    fine["measurements"]["integrated_interface_force"]["value"] = 50.0
    fine["measurements"]["integrated_interface_force"]["l1_N"] = 50.0
    got = compare_refinement(coarse, fine, kind="spatial")
    assert got["record_valid"] is False
    assert "integrated_interface_force" in got["validation_errors"]


def test_relative_change_overflow_is_undefined() -> None:
    coarse, fine = _spatial_pair()
    coarse["measurements"]["integrated_interface_force"]["value"] = 1e308
    coarse["measurements"]["integrated_interface_force"]["l1_N"] = 1e308
    fine["measurements"]["integrated_interface_force"]["value"] = 1e-308
    fine["measurements"]["integrated_interface_force"]["l1_N"] = 1e-308
    got = compare_refinement(coarse, fine, kind="spatial")
    row = next(r for r in got["quantities"] if r["name"] == "integrated_interface_force")
    assert row["relative_change"] is None
    dumps_report(got)


def test_run_live_writes_json_when_runner_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args, **kwargs):
        raise RuntimeError("solver exploded")

    monkeypatch.setattr("engineering_tools.e_facade.run_e_session", _boom)
    got = run_live_refinement_pair(tmp_path / "crash", {}, kind="spatial")
    assert got["ok"] is False
    assert got["stage"] == "coarse_session"
    assert (tmp_path / "crash" / "e-refine.json").is_file()
    dumps_report(got)
