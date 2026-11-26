"""Phase E adapters, façade, scenario, and refinement tests."""

from pathlib import Path

import pytest

from engineering_tools.e_adapters import fluid_participant_input, structural_participant_input
from engineering_tools.e_facade import run_e_session
from engineering_tools.e_scenario import reference_model, run_e_reference


def test_structural_and_fluid_adapters_from_reference_model() -> None:
    model = reference_model()
    solid = structural_participant_input(model, "shell")
    fluid = fluid_participant_input(model, "cavity")
    assert solid["status"] == "ok"
    assert solid["loads"]
    assert fluid["status"] == "ok"
    assert fluid["equation_of_state"] == "perfect_gas"


def test_run_e_session_without_live_kernels_is_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("engineering_tools.e_facade._authoritative_live", lambda: False)
    monkeypatch.delenv("ETOOLS_E_MOCK_SOLVERS", raising=False)
    session = run_e_session(tmp_path / "e-out", reference_model())
    assert session["e_ok"] is False
    assert session["status"] == "missing"
    assert (tmp_path / "e-out" / "e-session.json").is_file()


def test_run_e_session_probes_are_not_engineering_ok(tmp_path: Path) -> None:
    session = run_e_session(tmp_path / "e-probes", reference_model(), probes={
        "face.inner_wall.displacement": {"value": 1.2e-5, "unit": "m", "entity_id": "face.inner_wall"},
        "face.inner_wall.integrated_force": {"value": 12.0, "unit": "N", "entity_id": "face.inner_wall"},
    })
    assert session["e_ok"] is False
    assert session["status"] == "mock"
    assert session["mapping_error"]["relative"] is None
    assert "Displacement" in (tmp_path / "e-probes" / "precice-config.xml").read_text()
    assert "Heat-Flux" in (tmp_path / "e-probes" / "precice-config.xml").read_text()
    assert session["capabilities_used"] == ["fake_history", "checkpoint_restore"]
    assert session["coupling_convergence"] is False
    assert session["solver_convergence"] is None


def test_run_e_session_broken_when_mapped_fields_are_zero(tmp_path: Path) -> None:
    zeros = {
        "face.inner_wall.pressure": {"value": 0.0, "unit": "Pa", "entity_id": "face.inner_wall"},
        "face.inner_wall.displacement": {"value": 0.0, "unit": "m", "entity_id": "face.inner_wall"},
        "face.inner_wall.temperature": {"value": 0.0, "unit": "K", "entity_id": "face.inner_wall"},
        "face.inner_wall.heat_flux": {"value": 0.0, "unit": "W/m2", "entity_id": "face.inner_wall"},
    }
    session = run_e_session(tmp_path / "e-zero", reference_model(), probes=zeros)
    assert session["e_ok"] is False
    assert session["status"] == "broken"


def test_run_e_reference_writes_session(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("engineering_tools.e_facade._authoritative_live", lambda: False)
    monkeypatch.delenv("ETOOLS_E_MOCK_SOLVERS", raising=False)
    from engineering_tools.project import init_project

    project = init_project(tmp_path / "proj", name="e")
    result = run_e_reference(project)
    assert result["ok"] is False
    assert result["session"]["e_ok"] is False
    assert (Path(result["workdir"]) / "e-session.json").is_file()


def test_missing_thermal_pair_is_not_the_reference_model() -> None:
    model = reference_model()
    quantities = {f["quantity"] for f in model["fields"]}
    assert {"displacement", "traction", "temperature", "heat_flux"} <= quantities
    motions = {r["motion_model"] for r in model["regions"]}
    assert "prescribed_rigid_motion" in motions
    physics = {p for r in model["regions"] for p in r["physics_models"]}
    assert "compressible_fluid" in physics


def test_mechanical_verify_rejects_hardcoded_zero_mapping() -> None:
    from engineering_tools.e_verify import verify_mechanical_couple

    got = verify_mechanical_couple(
        windows_ok=True,
        probes={
            "face.inner_wall.displacement": {"value": 1e-8, "unit": "m"},
            "face.inner_wall.integrated_force": {"value": 9.0, "unit": "N", "l1_N": 9.0},
        },
        mapping_residual=None,
        log_text="Time window completed\n",
    )
    assert got["ok"] is False
    assert got["mapping_error"]["relative"] is None


def test_mechanical_verify_accepts_force_disp_and_residual() -> None:
    from engineering_tools.e_verify import verify_mechanical_couple

    got = verify_mechanical_couple(
        windows_ok=True,
        probes={
            "face.inner_wall.displacement": {"value": 1e-8, "unit": "m"},
            "face.inner_wall.integrated_force": {"value": 9.0, "unit": "N", "l1_N": 9.0},
        },
        mapping_residual=1.2e-5,
        log_text="relative convergence measure is not the mapping residual\n",
    )
    assert got["ok"] is True
    assert got["mapping_error"]["relative"] == pytest.approx(1.2e-5)
