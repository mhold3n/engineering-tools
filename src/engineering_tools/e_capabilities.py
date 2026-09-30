"""Phase E solver capability registry.

Agents: architectural representability is e_model. This module is implemented
solver support. Unknown IDs are broken; advertised-unavailable is missing.
Never silently downgrade elastoplastic, brittle, compressible, or thermal.
"""

from __future__ import annotations

from typing import Any

# Initial kernels: CalculiX structural, ESI OpenFOAM compressible/energy, preCICE backend.
ADAPTERS: dict[str, dict[str, Any]] = {
    "calculix": {
        "physical_regions": frozenset({"deformable_solid", "thermal_solid", "rigid_body"}),
        "constitutive_models": frozenset(
            {"linear_elastic", "temperature_dependent_elastic", "elastoplastic", "rigid"}
        ),
        "fields": frozenset({"displacement", "traction", "force", "temperature", "heat_flux"}),
        "steady": True,
        "transient": True,
        "compressible": False,
        "incompressible": False,
        "thermal": True,
        "moving_mesh": False,
        "rigid_contact": True,
        "checkpoint_restore": True,
        "topology_change": False,
        "discretizations": frozenset({"tet", "hex"}),
    },
    "openfoam": {
        "physical_regions": frozenset({"compressible_fluid", "incompressible_fluid"}),
        "constitutive_models": frozenset(),
        "fields": frozenset(
            {
                "pressure",
                "velocity",
                "density",
                "temperature",
                "heat_flux",
                "traction",
                "displacement",
                "enthalpy",
            }
        ),
        "steady": True,
        "transient": True,
        "compressible": True,
        "incompressible": True,
        "thermal": True,
        "moving_mesh": True,
        "rigid_contact": False,
        "checkpoint_restore": True,
        "topology_change": False,
        "discretizations": frozenset({"polyhedral", "hex"}),
    },
}


def request_capability(adapter_id: str, requirement: str, value: Any = True) -> dict[str, Any]:
    """Validate one requirement against a published adapter.

    requirement is a registry key (e.g. compressible, checkpoint_restore)
    or 'physical_region' / 'constitutive_model' / 'field' with value as the name.
    """
    adapter = ADAPTERS.get(adapter_id)
    if adapter is None:
        return {"status": "broken", "detail": f"unknown adapter: {adapter_id}"}
    if requirement == "physical_region":
        if value in adapter["physical_regions"]:
            return {"status": "ok", "detail": f"{adapter_id}:{value}"}
        return {"status": "missing", "detail": f"{adapter_id} has no physical_region {value}"}
    if requirement == "constitutive_model":
        if value in adapter["constitutive_models"]:
            return {"status": "ok", "detail": f"{adapter_id}:{value}"}
        return {"status": "missing", "detail": f"{adapter_id} has no constitutive_model {value}"}
    if requirement == "field":
        if value in adapter["fields"]:
            return {"status": "ok", "detail": f"{adapter_id}:{value}"}
        return {"status": "missing", "detail": f"{adapter_id} has no field {value}"}
    if requirement not in adapter:
        return {"status": "broken", "detail": f"unknown capability key: {requirement}"}
    have = adapter[requirement]
    if isinstance(have, bool):
        if have == bool(value):
            return {"status": "ok", "detail": f"{adapter_id}.{requirement}"}
        if have is False:
            return {"status": "missing", "detail": f"{adapter_id} lacks {requirement}"}
        return {"status": "broken", "detail": f"{adapter_id}.{requirement} mismatch"}
    return {"status": "ok", "detail": f"{adapter_id}.{requirement}"}


def assign_participant(
    adapter_id: str,
    *,
    physical_region: str,
    constitutive_model: str | None = None,
    fields: list[str] | None = None,
    require_checkpoint: bool = False,
    require_compressible: bool = False,
) -> dict[str, Any]:
    """Fail closed before launch if the adapter cannot host the assignment."""
    checks = [request_capability(adapter_id, "physical_region", physical_region)]
    if constitutive_model:
        checks.append(request_capability(adapter_id, "constitutive_model", constitutive_model))
    for field in fields or []:
        checks.append(request_capability(adapter_id, "field", field))
    if require_compressible:
        checks.append(request_capability(adapter_id, "compressible", True))
    if require_checkpoint:
        checks.append(request_capability(adapter_id, "checkpoint_restore", True))
    for check in checks:
        if check["status"] != "ok":
            return check
    return {"status": "ok", "detail": adapter_id}
