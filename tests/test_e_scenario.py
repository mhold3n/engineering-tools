"""Phase E adapters, façade, scenario, and refinement tests."""

from pathlib import Path

from engineering_tools.e_adapters import fluid_participant_input, structural_participant_input
from engineering_tools.e_facade import run_e_session
from engineering_tools.e_scenario import reference_model, run_e_reference
from engineering_tools.e_verify import compare_refinement


def test_structural_and_fluid_adapters_from_reference_model() -> None:
    model = reference_model()
    solid = structural_participant_input(model, "shell")
    fluid = fluid_participant_input(model, "cavity")
    assert solid["status"] == "ok"
    assert solid["loads"]
    assert fluid["status"] == "ok"
    assert fluid["equation_of_state"] == "perfect_gas"


def test_run_e_session_ok_with_finite_probes(tmp_path: Path) -> None:
    session = run_e_session(tmp_path / "e-out", reference_model())
    assert session["e_ok"] is True
    assert (tmp_path / "e-out" / "e-session.json").is_file()
    assert "Displacement" in (tmp_path / "e-out" / "precice-config.xml").read_text()
    assert "Heat-Flux" in (tmp_path / "e-out" / "precice-config.xml").read_text()
    probes = session["probes"]
    assert probes["face.inner_wall.pressure"]["value"] > 0
    assert probes["face.inner_wall.temperature"]["value"] > 0


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
    from engineering_tools.project import init_project

    project = init_project(tmp_path / "proj", name="e")
    result = run_e_reference(project)
    assert result["ok"] is True
    assert (Path(result["workdir"]) / "e-session.json").is_file()


def test_missing_thermal_pair_is_not_the_reference_model() -> None:
    model = reference_model()
    quantities = {f["quantity"] for f in model["fields"]}
    assert {"displacement", "traction", "temperature", "heat_flux"} <= quantities
    motions = {r["motion_model"] for r in model["regions"]}
    assert "prescribed_rigid_motion" in motions
    physics = {p for r in model["regions"] for p in r["physics_models"]}
    assert "compressible_fluid" in physics


def test_refinement_within_band() -> None:
    baseline = {
        "peak_wall_pressure": 1.01e5,
        "integrated_wall_force": 12.0,
        "peak_structural_displacement": 1.2e-5,
        "critical_von_mises": 8.0e7,
        "wall_temperature": 350.0,
        "integrated_heat_transfer": 40.0,
    }
    refined = dict(baseline)
    refined["peak_wall_pressure"] = 1.05e5
    got = compare_refinement(baseline, refined, relative_tolerance=0.2)
    assert got["ok"] is True


def test_refinement_outside_band_fails() -> None:
    baseline = {
        "peak_wall_pressure": 1.0e5,
        "integrated_wall_force": 10.0,
        "peak_structural_displacement": 1.0e-5,
        "critical_von_mises": 1.0e8,
        "wall_temperature": 300.0,
        "integrated_heat_transfer": 10.0,
    }
    refined = dict(baseline)
    refined["peak_wall_pressure"] = 2.0e5
    got = compare_refinement(baseline, refined, relative_tolerance=0.2)
    assert got["ok"] is False
    assert got["status"] == "broken"
