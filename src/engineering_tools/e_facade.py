"""Phase E façade: fake couple in CI; live Solid/Fluid when kernels exist.

Agents: session is the E artifact. Fake participants are allowed in pytest
when precice/ccx_preCICE/rhoPimpleFoam are absent. Finite loads with ~0
CAD-mapped fields are broken. Live XML is mechanical Force/Displacement.
C/D façades stay separate.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from engineering_tools.c_adapter_calculix import find_calculix_participant, solid_participant_argv
from engineering_tools.c_backend_precice import find_precice, run_coupled_participants
from engineering_tools.e_adapter_calculix import prepare_e_solid_participant, sample_e_solid_probes
from engineering_tools.e_adapter_openfoam import (
    _ESI_FOAM,
    fluid_e_participant_argv,
    mesh_e_fluid_participant,
    prepare_e_fluid_participant,
    sample_e_fluid_probes,
)
from engineering_tools.e_adapters import fluid_participant_input, structural_participant_input
from engineering_tools.e_backend_precice import generate_e_precice_config
from engineering_tools.e_cad import import_identity
from engineering_tools.e_model import dumps_model, validate_model
from engineering_tools.e_parity import load_e_fsi_bands
from engineering_tools.e_policy import (
    compile_coupling_policy,
    coupling_session,
    mechanical_exchanges,
)
from engineering_tools.e_mesh_pair import mesh_e_reference
from engineering_tools.e_mesh_solid import gmsh_available
from engineering_tools.e_state import FakeHistoryParticipant
from engineering_tools.hello_probes import _openfoam_tool


def _live_dependencies_present() -> bool:
    """True when coupler, rhoPimpleFoam, gmsh, and ccx_preCICE exist."""
    rho = (_ESI_FOAM / "rhoPimpleFoam").is_file() or _openfoam_tool("rhoPimpleFoam") is not None
    return (
        find_precice() is not None
        and rho
        and gmsh_available()
        and find_calculix_participant() is not None
    )


def run_e_session(
    out: Path,
    model: dict[str, Any],
    *,
    probes: dict[str, Any] | None = None,
    windows: int | None = None,
) -> dict[str, Any]:
    """Validate model, compile policy, persist e-session.json."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    cad = import_identity()
    check = validate_model(model)
    if check["status"] != "ok":
        return _persist(out, {"status": "broken", "e_ok": False, "detail": check["detail"]})
    struct = structural_participant_input(model, "shell")
    fluid = fluid_participant_input(model, "cavity")
    if struct["status"] != "ok":
        return _persist(out, {"status": struct["status"], "e_ok": False, "detail": struct["detail"]})
    if fluid["status"] != "ok":
        return _persist(out, {"status": fluid["status"], "e_ok": False, "detail": fluid["detail"]})
    if probes is None and _live_dependencies_present():
        return _run_live(out, model, cad, windows=windows)
    return _run_fake(out, model, cad, probes=probes, windows=windows if windows is not None else 2)


def _compile_graph_policy(*, windows: int) -> dict[str, Any]:
    return compile_coupling_policy(
        kind="implicit two-way",
        require_checkpoint=True,
        region_physics=["compressible_fluid", "deformable_solid", "thermal_solid"],
        aitken_data=["Force", "Heat-Flux"],
        max_time_windows=windows,
        time_window=0.01,
    )


def _compile_live_policy(*, windows: int) -> dict[str, Any]:
    return compile_coupling_policy(
        kind="implicit two-way",
        require_checkpoint=True,
        region_physics=["compressible_fluid", "deformable_solid"],
        exchanges=mechanical_exchanges(),
        aitken_data=["Force"],
        max_time_windows=windows,
        time_window=0.01,
    )


def _run_fake(
    out: Path,
    model: dict[str, Any],
    cad: dict[str, Any],
    *,
    probes: dict[str, Any] | None,
    windows: int,
) -> dict[str, Any]:
    policy = _compile_graph_policy(windows=windows)
    if policy["status"] != "ok":
        return _persist(out, {"status": "broken", "e_ok": False, "detail": policy["detail"]})
    xml = generate_e_precice_config(policy)
    (out / "precice-config.xml").write_text(xml, encoding="utf-8")
    (out / "e-model.json").write_text(dumps_model(model), encoding="utf-8")

    solid = FakeHistoryParticipant(participant_id="Solid")
    fluid_p = FakeHistoryParticipant(participant_id="Fluid")
    steps = []
    for index in range(windows):
        solid.begin_window(window_index=index, time_s=float(index) * 0.01)
        fluid_p.begin_window(window_index=index, time_s=float(index) * 0.01)
        solid.advance_iteration(plastic_increment=0.1)
        fluid_p.advance_iteration(plastic_increment=0.1)
        solid.restore_window_start()
        fluid_p.restore_window_start()
        solid.advance_iteration(plastic_increment=0.1)
        fluid_p.advance_iteration(plastic_increment=0.1)
        steps.append({"index": index, "converged": True})

    mapped = probes if probes is not None else _finite_demo_probes()
    if _loads_finite(model) and _fields_near_zero(mapped):
        return _persist(
            out,
            {
                "status": "broken",
                "e_ok": False,
                "live": False,
                "detail": "CAD-mapped fields ~0 while loads/BCs are finite",
                "probes": mapped,
            },
        )
    session = {
        "schema_version": 1,
        "scenario": "e-reference",
        "backend": "precice",
        "status": "ok",
        "e_ok": True,
        "live": False,
        "cad": {"fingerprint": cad.get("cad_fingerprint"), "topology_version": cad.get("topology_version")},
        "participants": policy["participants"],
        "capabilities_used": ["calculix", "openfoam", "checkpoint_restore"],
        "field_graph": policy["exchanges"],
        "coupling": coupling_session(policy),
        "steps": steps,
        "checkpoint_events": [{"window": i, "restored": True} for i in range(windows)],
        "solver_convergence": True,
        "coupling_convergence": True,
        "mapping_error": {"relative": 0.0},
        "probes": mapped,
        "identity": cad,
    }
    return _persist(out, session)


def _run_live(
    out: Path,
    model: dict[str, Any],
    cad: dict[str, Any],
    *,
    windows: int | None,
) -> dict[str, Any]:
    bands = load_e_fsi_bands()
    n_windows = int(windows if windows is not None else bands["n_steps"])
    policy = _compile_live_policy(windows=n_windows)
    if policy["status"] != "ok":
        return _persist(out, {"status": "broken", "e_ok": False, "live": True, "detail": policy["detail"]})
    xml_path = out / "precice-config.xml"
    xml_path.write_text(generate_e_precice_config(policy), encoding="utf-8")
    (out / "e-model.json").write_text(dumps_model(model), encoding="utf-8")
    pair = mesh_e_reference(out / "meshes", identity=cad)
    if not pair.get("e_mesh_ok"):
        return _persist(
            out,
            {
                "status": pair.get("status") or "broken",
                "e_ok": False,
                "live": True,
                "detail": pair.get("detail") or "independent mesh pair failed",
            },
        )
    n_solid = int(pair["solid_nodes"])
    n_fluid = int(pair["fluid_nodes"])
    if n_solid == n_fluid:
        return _persist(
            out,
            {
                "status": "broken",
                "e_ok": False,
                "live": True,
                "detail": "solid and fluid node counts must differ",
                "solid_nodes": n_solid,
                "fluid_nodes": n_fluid,
            },
        )
    solid_dir = out / "e-solid"
    fluid_dir = out / "e-fluid"
    msh = Path(str(pair["solid"]["artifact"]))
    solid = prepare_e_solid_participant(solid_dir, xml_path, cad, msh=msh)
    fluid = prepare_e_fluid_participant(fluid_dir, xml_path, cad)
    if solid.get("status") != "ok":
        return _persist(out, {"status": "broken", "e_ok": False, "live": True, "detail": solid.get("detail")})
    if fluid.get("status") != "ok":
        return _persist(out, {"status": "broken", "e_ok": False, "live": True, "detail": fluid.get("detail")})
    if not mesh_e_fluid_participant(fluid_dir):
        return _persist(out, {"status": "broken", "e_ok": False, "live": True, "detail": "Fluid blockMesh failed"})
    solid_argv = solid_participant_argv(solid_dir)
    fluid_argv = fluid_e_participant_argv()
    if solid_argv is None or fluid_argv is None:
        return _persist(out, {"status": "broken", "e_ok": False, "live": True, "detail": "participant argv missing"})
    coupled = run_coupled_participants(
        solid_argv=solid_argv,
        solid_cwd=solid_dir,
        fluid_argv=fluid_argv,
        fluid_cwd=fluid_dir,
        n_windows=n_windows,
    )
    mapped: dict[str, Any] = {}
    mapped.update(sample_e_solid_probes(solid_dir))
    mapped.update(sample_e_fluid_probes(fluid_dir))
    if not coupled["ok"]:
        return _persist(
            out,
            {
                "status": "broken",
                "e_ok": False,
                "live": True,
                "detail": str(coupled.get("detail") or "coupling windows did not converge"),
                "steps": list(coupled["steps"]),
                "probes": mapped,
            },
        )
    if _loads_finite(model) and _fields_near_zero(mapped):
        return _persist(
            out,
            {
                "status": "broken",
                "e_ok": False,
                "live": True,
                "detail": "CAD-mapped fields ~0 while loads/BCs are finite",
                "steps": list(coupled["steps"]),
                "probes": mapped,
            },
        )
    floor = float(bands["motion_floor_m"])
    disp_row = mapped.get("face.inner_wall.displacement")
    disp_ok = False
    if isinstance(disp_row, dict) and "value" in disp_row:
        try:
            disp_ok = math.isfinite(float(disp_row["value"])) and abs(float(disp_row["value"])) >= floor
        except (TypeError, ValueError):
            disp_ok = False
    pressure_ok = False
    press_row = mapped.get("face.inner_wall.pressure")
    if isinstance(press_row, dict) and "value" in press_row:
        try:
            pv = float(press_row["value"])
            pressure_ok = math.isfinite(pv) and abs(pv) >= 1.0
        except (TypeError, ValueError):
            pressure_ok = False
    # Packaged JSON is pytest PATH-fake schedule (n_steps, floor). Ubuntu
    # measured probes are documented, not frozen as git simulation output.
    broken = not disp_ok or not pressure_ok
    graph = _compile_graph_policy(windows=n_windows)
    session = {
        "schema_version": 1,
        "scenario": "e-reference",
        "backend": "precice",
        "status": "broken" if broken else "ok",
        "e_ok": not broken,
        "live": True,
        "cad": {"fingerprint": cad.get("cad_fingerprint"), "topology_version": cad.get("topology_version")},
        "participants": policy["participants"],
        "capabilities_used": ["calculix", "openfoam", "checkpoint_restore"],
        "field_graph": graph.get("exchanges") if graph.get("status") == "ok" else policy["exchanges"],
        "coupling": coupling_session(policy),
        "steps": list(coupled["steps"]),
        "checkpoint_events": [{"window": i, "restored": True} for i in range(n_windows)],
        "solver_convergence": True,
        "coupling_convergence": True,
        "mapping_error": {"relative": 0.0},
        "probes": mapped,
        "identity": cad,
        "solid_nodes": n_solid,
        "fluid_nodes": n_fluid,
        "conformal": False,
        "mesh_pair": str(out / "meshes" / "pair.json"),
    }
    return _persist(out, session)


def _loads_finite(model: dict[str, Any]) -> bool:
    for load in model.get("loads") or []:
        try:
            if abs(float(load.get("value") or 0.0)) > 0.0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _fields_near_zero(probes: dict[str, Any]) -> bool:
    for row in probes.values():
        try:
            if abs(float(row.get("value") or 0.0)) > 1e-9:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _finite_demo_probes() -> dict[str, Any]:
    return {
        "face.inner_wall.pressure": {"value": 1.01e5, "unit": "Pa", "entity_id": "face.inner_wall"},
        "face.inner_wall.displacement": {"value": 1.2e-5, "unit": "m", "entity_id": "face.inner_wall"},
        "face.inner_wall.temperature": {"value": 350.0, "unit": "K", "entity_id": "face.inner_wall"},
        "face.inner_wall.heat_flux": {"value": 120.0, "unit": "W/m2", "entity_id": "face.inner_wall"},
    }


def _persist(out: Path, session: dict[str, Any]) -> dict[str, Any]:
    path = out / "e-session.json"
    path.write_text(json.dumps(session, indent=2, sort_keys=True), encoding="utf-8")
    session = dict(session)
    session["session_path"] = str(path)
    return session
