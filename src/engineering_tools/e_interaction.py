"""Fluid-first wall interaction between OpenFOAM and CalculiX.

Agents: this module is the CFD-FEA outline. Intended behavior is one step.
OpenFOAM owns gas, liquid, and their interface. CalculiX owns the solid.
The only bridge is the solid wall. The fluid writes a wall record of name,
value, and unit. The solid reads it. Solid displacement does not move the
fluid mesh before the next fluid step. Observed behavior is the dict
returned by interaction_step. Status is ok or broken.

Bridge emission is a separate fact from the wall record. A name in
BRIDGE_QUANTITIES is emitted. Any other named quantity with a unit stays
on the record as not_emitted. It is not dropped and it is not invented
as a preCICE field.
"""

from __future__ import annotations

import math
from typing import Any

from engineering_tools.e_field import QUANTITIES
from engineering_tools.e_time import compile_multirate_schedule

# Names the preCICE bridge can carry today. Keep this equal to e_policy.PRECICE_DATA.
# displacement is in the set because the bridge knows the name. This step still
# rejects a Solid to Fluid displacement exchange below.
BRIDGE_QUANTITIES = frozenset(
    {
        "displacement",
        "traction",
        "force",
        "temperature",
        "heat_flux",
        "pressure",
        "velocity",
        "density",
        "enthalpy",
    }
)

# Fluid products written onto the wall. displacement is a solid result, so it
# is not a default fluid write. traction is the same bridge Force as force.
FLUID_WALL_QUANTITIES = frozenset(
    {
        "force",
        "pressure",
        "heat_flux",
        "velocity",
        "density",
        "enthalpy",
        "temperature",
    }
)

STOP_RULES = frozenset({"static", "steady", "dynamic"})


def _broken(detail: str) -> dict[str, Any]:
    """Fail-closed step. Callers branch on status, not on exceptions."""
    return {"status": "broken", "detail": detail}


def fluid_first_participants() -> list[dict[str, str]]:
    """OpenFOAM first, CalculiX second. Ownership stays on the participant."""
    return [
        {"name": "Fluid", "solver": "openfoam", "owns": "gas,liquid,gas_liquid_interface"},
        {"name": "Solid", "solver": "calculix", "owns": "solid"},
    ]


def _vector3(value: Any, label: str) -> str | None:
    """Return an error string when value is not three numbers."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return f"{label} must be three numbers"
    for component in value:
        if isinstance(component, bool) or not isinstance(component, (int, float)):
            return f"{label} must be three numbers"
    return None


def prescribed_spin_record(spin: dict[str, Any] | None) -> dict[str, Any] | None | str:
    """Fluid input. None means the wall is not spinning.

    A provided spin needs origin, axis, and a non-empty schedule. The schedule
    is the caller's angular-velocity table. This module does not interpret rpm.
    """
    if spin is None:
        return None
    if not isinstance(spin, dict):
        return "prescribed spin must be a record"
    origin = _vector3(spin.get("origin"), "origin")
    if origin:
        return origin
    axis = _vector3(spin.get("axis"), "axis")
    if axis:
        return axis
    schedule = spin.get("schedule")
    if schedule in (None, "", []):
        return "prescribed spin schedule is required"
    return {
        "origin": [float(component) for component in spin["origin"]],
        "axis": [float(component) for component in spin["axis"]],
        "schedule": schedule,
    }


def _finite_number(value: Any) -> bool:
    """True for a real number. Bool is rejected because it is not a magnitude."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _known_quantity_problem(name: str, value: Any, unit: str) -> str | None:
    """Known quantities must match QUANTITIES. Unknown names are not checked."""
    spec = QUANTITIES.get(name)
    if spec is None:
        return None
    rank, expect_unit = spec
    if unit != expect_unit:
        return f"{name} requires unit {expect_unit}"
    if rank == "scalar" and _finite_number(value):
        return None
    if (
        rank == "vector"
        and isinstance(value, (list, tuple))
        and len(value) == 3
        and all(_finite_number(part) for part in value)
    ):
        return None
    return f"{name} value must be a {rank}"


def _wall_item(raw: dict[str, Any]) -> dict[str, Any] | str:
    """One wall quantity. Missing unit fails. Unknown names stay.

    A name in QUANTITIES must use that rank and unit. A scalar force is
    broken. An unknown name with a unit stays on the record.
    """
    name = str(raw.get("name") or "")
    if not name:
        return "wall item missing name"
    unit = raw.get("unit")
    if unit in (None, ""):
        return "wall item missing unit"
    if "value" not in raw:
        return "wall item missing value"
    problem = _known_quantity_problem(name, raw["value"], str(unit))
    if problem:
        return problem
    emission = "emitted" if name in BRIDGE_QUANTITIES else "not_emitted"
    return {
        "name": name,
        "value": raw["value"],
        "unit": str(unit),
        "emission": emission,
    }


def _rejects_solid_displacement(exchanges: list[dict[str, Any]]) -> str | None:
    """Solid displacement must not be handed back to the fluid mesh."""
    for exchange in exchanges:
        quantity = str(exchange.get("quantity") or "")
        source = str(exchange.get("from") or "")
        destination = str(exchange.get("to") or "")
        if quantity == "displacement" and source == "Solid" and destination == "Fluid":
            return "solid displacement does not update the fluid mesh"
    return None


def _resolve_stop(
    stop_rule: str,
    wall: list[dict[str, Any]],
    *,
    previous_wall: list[dict[str, Any]] | None,
    window_dt_s: float | None,
    fluid_dt_s: float | None,
    global_time_s: float,
) -> dict[str, Any] | str:
    """Same step, three stop rules. The steady compare is exact equality."""
    if stop_rule == "static":
        return {"rule": "static", "steps": 1, "continue": False}
    if stop_rule == "steady":
        # First record has no previous. Later records stop only on exact equality.
        continued = previous_wall is None or previous_wall != wall
        return {"rule": "steady", "continue": continued}
    if window_dt_s is None or fluid_dt_s is None:
        return "dynamic stop needs window_dt_s and fluid_dt_s"
    clock = compile_multirate_schedule(
        window_dt_s=window_dt_s,
        global_time_s=global_time_s,
        participants={"Fluid": {"dt_s": fluid_dt_s}},
    )
    if clock["status"] != "ok":
        return str(clock["detail"])
    return {"rule": "dynamic", "continue": True, "clock": clock}


def interaction_step(
    *,
    wall_items: list[dict[str, Any]] | None = None,
    exchanges: list[dict[str, Any]] | None = None,
    stop_rule: str = "static",
    prescribed_spin: dict[str, Any] | None = None,
    previous_wall: list[dict[str, Any]] | None = None,
    window_dt_s: float | None = None,
    fluid_dt_s: float | None = None,
    global_time_s: float = 0.0,
) -> dict[str, Any]:
    """Return one fluid-first step.

    wall_items are what the fluid produced. exchanges are proposed bridge
    writes. A Solid to Fluid displacement fails the whole step. Emitted wall
    items become Fluid to Solid exchanges. not_emitted items stay on the wall
    record only. static runs once. steady repeats until the wall record
    repeats exactly. dynamic repeats on the fluid clock.
    """
    if stop_rule not in STOP_RULES:
        return _broken(f"unknown stop rule: {stop_rule}")
    spin = prescribed_spin_record(prescribed_spin)
    if isinstance(spin, str):
        return _broken(spin)
    proposed = list(exchanges or [])
    rejected = _rejects_solid_displacement(proposed)
    if rejected:
        return _broken(rejected)
    compiled_wall: list[dict[str, Any]] = []
    for raw in list(wall_items or []):
        item = _wall_item(raw)
        if isinstance(item, str):
            return _broken(item)
        compiled_wall.append(item)
    stop = _resolve_stop(
        stop_rule,
        compiled_wall,
        previous_wall=previous_wall,
        window_dt_s=window_dt_s,
        fluid_dt_s=fluid_dt_s,
        global_time_s=global_time_s,
    )
    if isinstance(stop, str):
        return _broken(stop)
    emitted = [
        {"quantity": item["name"], "from": "Fluid", "to": "Solid"}
        for item in compiled_wall
        if item["emission"] == "emitted"
    ]
    return {
        "status": "ok",
        "participants": fluid_first_participants(),
        "bridge": "solid_wall",
        "stop_rule": stop_rule,
        "stop": stop,
        "fluid_region": {
            "region_id": "fluid",
            "participant": "Fluid",
            "motion_model": "prescribed_rigid_motion" if spin else "fixed",
            "prescribed_spin": spin,
        },
        "prescribed_spin": spin,
        "solid_updates_fluid_mesh": False,
        "wall": compiled_wall,
        "exchanges": emitted,
    }


def default_fluid_exchanges() -> list[dict[str, str]]:
    """One-way compiler default. Every default fluid quantity, Fluid to Solid."""
    return [
        {"quantity": name, "from": "Fluid", "to": "Solid"}
        for name in sorted(FLUID_WALL_QUANTITIES)
    ]
