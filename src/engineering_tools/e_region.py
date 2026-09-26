"""Phase E physical regions and motion.

Agents: region type is model data, not an orchestration branch. Gas is
compressible_fluid, never a special product path.
"""

from __future__ import annotations

from typing import Any

REGION_PHYSICS = frozenset(
    {
        "rigid_body",
        "deformable_solid",
        "incompressible_fluid",
        "compressible_fluid",
        "thermal_solid",
        "porous_region",
    }
)

MOTION_MODELS = frozenset(
    {
        "fixed",
        "prescribed_rigid_motion",
        "solved_rigid_body_motion",
        "deformable_motion",
        "rotating_reference_frame",
        "sliding_moving_mesh",
    }
)


def validate_region(record: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed physical-region schema."""
    if not record.get("region_id"):
        return {"status": "broken", "detail": "region_id required"}
    physics = record.get("physics_models")
    if not isinstance(physics, list) or not physics:
        return {"status": "broken", "detail": "physics_models must be a non-empty list"}
    unknown = [p for p in physics if p not in REGION_PHYSICS]
    if unknown:
        return {"status": "broken", "detail": f"unknown physics_models: {unknown}"}
    motion = str(record.get("motion_model") or "")
    if motion not in MOTION_MODELS:
        return {"status": "broken", "detail": f"unknown motion_model: {motion}"}
    if not record.get("entity_id"):
        return {"status": "broken", "detail": "entity_id required"}
    if not record.get("material_id"):
        return {"status": "broken", "detail": "material_id required"}
    if "compressible_fluid" in physics:
        if not record.get("equation_of_state"):
            return {"status": "broken", "detail": "compressible_fluid requires equation_of_state"}
    return {"status": "ok", "detail": str(record["region_id"])}
