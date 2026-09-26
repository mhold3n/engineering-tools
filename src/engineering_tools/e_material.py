"""Phase E materials and constitutive declarations.

Agents: constitutive evaluation stays in the solver. This module only records
intent. Unsupported live models remain schema-valid; adapters reject at
capability check (e_capabilities).
"""

from __future__ import annotations

from typing import Any

CONSTITUTIVE_MODELS = frozenset(
    {
        "linear_elastic",
        "temperature_dependent_elastic",
        "elastoplastic",
        "temperature_dependent_plastic",
        "hyperelastic",
        "viscoelastic",
        "creep",
        "damage_brittle",
        "composite_anisotropic",
        "rigid",
    }
)

# Optional temperature-dependent property keys (R19).
TEMPERATURE_PROPERTIES = frozenset(
    {"E(T)", "nu(T)", "yield(T)", "alpha(T)", "k(T)", "Cp(T)", "rho(T)", "creep(T)", "damage(T)"}
)


def validate_material(record: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed material/constitutive schema."""
    if not record.get("material_id"):
        return {"status": "broken", "detail": "material_id required"}
    model = str(record.get("constitutive_model") or "")
    if model not in CONSTITUTIVE_MODELS:
        return {"status": "broken", "detail": f"unknown constitutive_model: {model}"}
    props = record.get("temperature_properties") or []
    if props:
        if not isinstance(props, list):
            return {"status": "broken", "detail": "temperature_properties must be a list"}
        unknown = [p for p in props if p not in TEMPERATURE_PROPERTIES]
        if unknown:
            return {"status": "broken", "detail": f"unknown temperature_properties: {unknown}"}
    eos = record.get("equation_of_state")
    if eos is not None and not isinstance(eos, str):
        return {"status": "broken", "detail": "equation_of_state must be a string"}
    return {"status": "ok", "detail": str(record["material_id"])}
