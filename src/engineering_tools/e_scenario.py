"""Phase E heated-vessel reference scenario (canonical graph, fake couple).

Agents: this is not damper-keyway and not D meshes. Geometry IDs come from
e_cad fixture. Live Ubuntu kernels are a later gate; pytest uses the façade fakes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engineering_tools.e_cad import import_identity
from engineering_tools.e_facade import run_e_session
from engineering_tools.e_field import validate_field
from engineering_tools.e_model import empty_model, validate_model


def reference_model() -> dict[str, Any]:
    """Compressible gas + deformable thermal shell + prescribed rigid lid."""
    cad = import_identity()
    model = empty_model(topology_version=int(cad.get("topology_version") or 1))
    model["cad_fingerprint"] = cad.get("cad_fingerprint")
    model["entities"] = list(cad.get("entities") or [])
    model["materials"] = [
        {
            "material_id": "alloy",
            "constitutive_model": "temperature_dependent_elastic",
            "temperature_properties": ["E(T)", "k(T)"],
        },
        {"material_id": "air", "constitutive_model": "linear_elastic", "equation_of_state": "perfect_gas"},
        {"material_id": "lid_steel", "constitutive_model": "rigid"},
    ]
    model["regions"] = [
        {
            "region_id": "shell",
            "entity_id": "body.shell",
            "material_id": "alloy",
            "physics_models": ["deformable_solid"],
            "motion_model": "deformable_motion",
        },
        {
            "region_id": "cavity",
            "entity_id": "body.gas",
            "material_id": "air",
            "physics_models": ["compressible_fluid"],
            "motion_model": "fixed",
            "equation_of_state": "perfect_gas",
        },
        {
            "region_id": "lid",
            "entity_id": "body.lid",
            "material_id": "lid_steel",
            "physics_models": ["rigid_body"],
            "motion_model": "prescribed_rigid_motion",
        },
    ]
    model["loads"] = [
        {
            "load_id": "gas.pressure",
            "entity_id": "face.inner_wall",
            "quantity": "pressure",
            "value": 1.01e5,
            "unit": "Pa",
        }
    ]
    model["relations"] = [
        {
            "relation_id": "wall.fsi",
            "kind": "fluid_solid",
            "region_ids": ["cavity", "shell"],
        }
    ]
    model["interfaces"] = [
        {
            "interface_id": "iface.fluid_solid",
            "entity_id": "face.inner_wall",
            "field_pairs": [
                ["displacement", "traction"],
                ["temperature", "heat_flux"],
            ],
        }
    ]
    model["fields"] = [
        _field("solid.displacement", "displacement", "vector", "m", "Solid", ["Fluid"], "consistent", "intensive", "none"),
        _field("fluid.traction", "traction", "vector", "Pa", "Fluid", ["Solid"], "conservative", "intensive", "force"),
        _field("solid.temperature", "temperature", "scalar", "K", "Solid", ["Fluid"], "consistent", "intensive", "none"),
        _field("fluid.heat_flux", "heat_flux", "vector", "W/m2", "Fluid", ["Solid"], "conservative", "intensive", "energy"),
    ]
    check = validate_model(model)
    if check["status"] != "ok":
        raise ValueError(check["detail"])
    for field in model["fields"]:
        if validate_field(field)["status"] != "ok":
            raise ValueError(validate_field(field)["detail"])
    return model


def _field(
    field_id: str,
    quantity: str,
    kind: str,
    si_unit: str,
    owner: str,
    consumers: list[str],
    mapping: str,
    extent: str,
    conservation: str,
) -> dict[str, Any]:
    return {
        "field_id": field_id,
        "quantity": quantity,
        "kind": kind,
        "si_unit": si_unit,
        "frame_id": "cad",
        "support_entity_id": "face.inner_wall",
        "owner_participant": owner,
        "consumer_participants": consumers,
        "mapping_method": mapping,
        "extent": extent,
        "conservation": conservation,
    }


def run_e_reference(project: str | Path) -> dict[str, Any]:
    """Write artifacts/scenario-e-reference/e-session.json."""
    root = Path(project)
    out = root / "artifacts" / "scenario-e-reference"
    session = run_e_session(out, reference_model())
    ok = bool(session.get("e_ok"))
    return {
        "ok": ok,
        "status": "ok" if ok else session.get("status") or "broken",
        "message": "e-reference passed" if ok else str(session.get("detail") or "e-reference failed"),
        "workdir": str(out),
        "outputs": [str(out / "e-session.json")],
        "session": session,
    }
