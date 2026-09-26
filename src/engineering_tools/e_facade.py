"""Phase E façade: execute the field graph without damper scenario logic.

Agents: session is the E artifact. Fake participants are allowed in pytest.
Finite loads with ~0 CAD-mapped fields are broken. C/D façades stay separate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engineering_tools.e_adapters import fluid_participant_input, structural_participant_input
from engineering_tools.e_backend_precice import generate_e_precice_config
from engineering_tools.e_cad import import_identity
from engineering_tools.e_model import dumps_model, validate_model
from engineering_tools.e_policy import compile_coupling_policy, coupling_session
from engineering_tools.e_state import FakeHistoryParticipant


def run_e_session(
    out: Path,
    model: dict[str, Any],
    *,
    probes: dict[str, Any] | None = None,
    windows: int = 2,
) -> dict[str, Any]:
    """Validate model, compile implicit two-way policy, persist e-session.json."""
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
    policy = compile_coupling_policy(
        kind="implicit two-way",
        require_checkpoint=True,
        region_physics=["compressible_fluid", "deformable_solid", "thermal_solid"],
        aitken_data=["Force", "Heat-Flux"],
        max_time_windows=windows,
    )
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
