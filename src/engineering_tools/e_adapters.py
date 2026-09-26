"""Phase E solver adapters: canonical model → native solver intent.

Agents: adapters own CalculiX/OpenFOAM syntax later. This unit publishes
capability-checked participant inputs as dicts. No run_fsi_special path.
"""

from __future__ import annotations

from typing import Any

from engineering_tools.e_capabilities import assign_participant


def structural_participant_input(model: dict[str, Any], region_id: str) -> dict[str, Any]:
    """CalculiX-facing input from a deformable/thermal/rigid region."""
    region = _region(model, region_id)
    if region is None:
        return {"status": "broken", "detail": f"unknown region {region_id}"}
    physics = region["physics_models"][0]
    mat = _material(model, region["material_id"])
    constitutive = None if mat is None else mat.get("constitutive_model")
    check = assign_participant(
        "calculix",
        physical_region=physics if physics != "compressible_fluid" else "deformable_solid",
        constitutive_model=constitutive,
        fields=["displacement", "traction", "temperature"],
        require_checkpoint=True,
    )
    if physics == "compressible_fluid":
        return {"status": "missing", "detail": "structural adapter does not host compressible_fluid"}
    if check["status"] != "ok":
        return check
    entity_ids = {region.get("entity_id")}
    for ent in model.get("entities") or []:
        if ent.get("parent_id") == region.get("entity_id"):
            entity_ids.add(ent.get("entity_id"))
    loads = [ld for ld in (model.get("loads") or []) if ld.get("entity_id") in entity_ids]
    return {
        "status": "ok",
        "solver": "calculix",
        "region_id": region_id,
        "physics": physics,
        "constitutive_model": constitutive,
        "motion_model": region.get("motion_model"),
        "loads": loads,
        "native": {"kind": "inp-intent", "nsets_from_entity": region.get("entity_id")},
    }


def fluid_participant_input(model: dict[str, Any], region_id: str) -> dict[str, Any]:
    """OpenFOAM-facing compressible gas input."""
    region = _region(model, region_id)
    if region is None:
        return {"status": "broken", "detail": f"unknown region {region_id}"}
    physics = region["physics_models"][0]
    check = assign_participant(
        "openfoam",
        physical_region=physics,
        fields=["pressure", "velocity", "temperature", "heat_flux", "traction"],
        require_compressible=physics == "compressible_fluid",
        require_checkpoint=True,
    )
    if check["status"] != "ok":
        return check
    return {
        "status": "ok",
        "solver": "openfoam",
        "region_id": region_id,
        "physics": physics,
        "equation_of_state": region.get("equation_of_state"),
        "motion_model": region.get("motion_model"),
        "native": {"kind": "foam-intent", "energy": True, "compressible": True},
    }


def _region(model: dict[str, Any], region_id: str) -> dict[str, Any] | None:
    for row in model.get("regions") or []:
        if row.get("region_id") == region_id:
            return row
    return None


def _material(model: dict[str, Any], material_id: str) -> dict[str, Any] | None:
    for row in model.get("materials") or []:
        if row.get("material_id") == material_id:
            return row
    return None
