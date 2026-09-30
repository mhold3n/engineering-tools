"""Phase E coupling policy: field graph → declared coupling, not preCICE XML.

Agents: this module owns policy kinds and fail-closed validation. XML lives in
e_backend_precice. Do not add extra orchestration functions for FSI, thermal,
or gas. Compressible-fluid metadata is a field/region attribute on the same
compile_coupling_policy path. C/D keep default_policy and tight_d_policy in
c_backend_precice; do not call those from here.

Aitken is not a free acceleration knob. On serial-implicit, preCICE only
allows Aitken on data the *second* participant writes to the *first*
(C/D: Force). Displacement Aitken (first→second) is illegal — status
broken, never emit that XML.
"""

from __future__ import annotations

from typing import Any

from engineering_tools.e_field import QUANTITIES

# R35 kinds. Strings are the public IDs tests and sessions store.
POLICY_KINDS = frozenset(
    {
        "one-way",
        "explicit two-way",
        "implicit two-way",
        "multirate implicit",
    }
)

# Only a generated-config backend is in this unit. Homegrown couplers fail closed.
SUPPORTED_BACKENDS = frozenset({"precice"})

# Implicit iteration (partitioned residual loop). one-way / explicit must not
# claim these in policy. The backend maps them to serial-implicit XML.
_IMPLICIT_KINDS = frozenset({"implicit two-way", "multirate implicit"})

# Canonical quantity → (preCICE data name, data element kind).
# traction becomes Force: OpenFOAM-preCICE writes Force, not Traction.
PRECICE_DATA = {
    "displacement": ("Displacement", "vector"),
    "traction": ("Force", "vector"),
    "force": ("Force", "vector"),
    "temperature": ("Temperature", "scalar"),
    "heat_flux": ("Heat-Flux", "vector"),
    "pressure": ("Pressure", "scalar"),
    "velocity": ("Velocity", "vector"),
    "density": ("Density", "scalar"),
    "enthalpy": ("Enthalpy", "scalar"),
}


def _broken(detail: str) -> dict[str, Any]:
    return {"status": "broken", "detail": detail}


def default_participants() -> list[dict[str, str]]:
    """First = serial first (structure), second = serial second (fluid)."""
    return [
        {"name": "Solid", "solver": "calculix"},
        {"name": "Fluid", "solver": "openfoam"},
    ]


def mechanical_exchanges(
    first: str = "Solid",
    second: str = "Fluid",
) -> list[dict[str, str]]:
    """Live OpenFOAM FSI + CalculiX: Displacement and Force only.

    Agents: Heat-Flux/Temperature stay on the canonical graph. The live
    adapters do not write those names; putting them in XML hangs the couple.
    """
    return [
        {"quantity": "displacement", "from": first, "to": second},
        {"quantity": "traction", "from": second, "to": first},
    ]


def mechanical_thermal_exchanges(
    first: str = "Solid",
    second: str = "Fluid",
) -> list[dict[str, str]]:
    """Wall interface: displacement↔force and temperature↔heat-flux.

    Agents: two pairs, same interface. Not two orchestration functions.
    traction is the canonical quantity; compile maps it to Force.
    """
    return [
        {"quantity": "displacement", "from": first, "to": second},
        {"quantity": "traction", "from": second, "to": first},
        {"quantity": "temperature", "from": first, "to": second},
        {"quantity": "heat_flux", "from": second, "to": first},
    ]


def _normalize_exchange(raw: dict[str, Any], participants: list[dict[str, str]]) -> dict[str, Any] | str:
    """Return a compiled exchange dict, or an error string."""
    qty = str(raw.get("quantity") or "")
    if qty not in QUANTITIES:
        return f"unknown exchange quantity: {qty}"
    mapping = PRECICE_DATA.get(qty)
    if mapping is None:
        return f"no preCICE data mapping for quantity: {qty}"
    names = {p["name"] for p in participants}
    src = str(raw.get("from") or "")
    dst = str(raw.get("to") or "")
    if src not in names or dst not in names:
        return f"exchange participants must be named participants, got {src}->{dst}"
    if src == dst:
        return "exchange from and to must differ"
    precice_name, rank = mapping
    return {
        "quantity": qty,
        "from": src,
        "to": dst,
        "precice_name": precice_name,
        "rank": rank,
        "si_unit": QUANTITIES[qty][1],
    }


def _second_to_first_names(
    exchanges: list[dict[str, Any]],
    first_name: str,
    second_name: str,
) -> list[str]:
    """preCICE names written by serial-second, read by serial-first (legal Aitken)."""
    names: list[str] = []
    for ex in exchanges:
        if ex["from"] == second_name and ex["to"] == first_name:
            if ex["precice_name"] not in names:
                names.append(ex["precice_name"])
    return names


def compile_coupling_policy(
    *,
    kind: str,
    backend: str = "precice",
    participants: list[dict[str, str]] | None = None,
    exchanges: list[dict[str, Any]] | None = None,
    require_checkpoint: bool = False,
    aitken_data: list[str] | None = None,
    mesh_name: str = "interface",
    time_window: float = 0.01,
    max_iterations: int = 100,
    max_time_windows: int = 2,
    first_dt: float | None = None,
    second_dt: float | None = None,
    region_physics: list[str] | None = None,
) -> dict[str, Any]:
    """Validate and freeze a Phase E coupling policy dict.

    region_physics (e.g. compressible_fluid) is metadata only. It does not
    select a different function. Invalid kind/backend is broken.
    """
    if kind not in POLICY_KINDS:
        return _broken(f"unknown coupling kind: {kind}")
    if backend not in SUPPORTED_BACKENDS:
        return _broken(f"unsupported coupling backend: {backend}")
    parts = list(participants) if participants is not None else default_participants()
    if len(parts) < 2:
        return _broken("coupling policy needs at least two participants")
    first_name = str(parts[0]["name"])
    second_name = str(parts[1]["name"])
    raw_exchanges = exchanges if exchanges is not None else mechanical_thermal_exchanges(
        first_name, second_name
    )
    compiled: list[dict[str, Any]] = []
    for raw in raw_exchanges:
        got = _normalize_exchange(raw, parts)
        if isinstance(got, str):
            return _broken(got)
        compiled.append(got)

    legal_aitken = _second_to_first_names(compiled, first_name, second_name)
    implicit = kind in _IMPLICIT_KINDS
    if aitken_data is not None:
        if not implicit:
            return _broken("Aitken is only valid on implicit coupling kinds")
        requested = [str(name) for name in aitken_data]
        illegal = [name for name in requested if name not in legal_aitken]
        if illegal:
            return _broken(
                "Aitken on serial-implicit first-to-second data is illegal "
                f"(C/D: Displacement); got {illegal}"
            )
        aitken_names = requested
    elif implicit:
        aitken_names = list(legal_aitken)
    else:
        aitken_names = []

    policy: dict[str, Any] = {
        "status": "ok",
        "kind": kind,
        "backend": backend,
        "participants": parts,
        "mesh_name": mesh_name,
        "exchanges": compiled,
        "time_window": float(time_window),
        "max_iterations": int(max_iterations),
        "max_time_windows": int(max_time_windows),
        "aitken_data": aitken_names,
        "checkpoint_required": bool(require_checkpoint),
        "implicit": implicit,
        "multirate": kind == "multirate implicit",
        "region_physics": list(region_physics or []),
    }
    if kind == "multirate implicit":
        # Coupling window vs participant subcycle. Backend emits substeps=true.
        policy["first_dt"] = float(first_dt if first_dt is not None else time_window)
        policy["second_dt"] = float(second_dt if second_dt is not None else time_window / 10.0)
        if policy["second_dt"] <= 0 or policy["first_dt"] <= 0:
            return _broken("multirate dts must be positive")
    return policy


def coupling_session(policy: dict[str, Any]) -> dict[str, Any]:
    """Session-facing slice of a compiled policy.

    Agents: checkpoint_required is copied when the compile call requested it.
    status follows the policy (broken policies stay broken).
    """
    return {
        "status": policy.get("status", "broken"),
        "kind": policy.get("kind"),
        "backend": policy.get("backend"),
        "checkpoint_required": bool(policy.get("checkpoint_required")),
        "exchanges": list(policy.get("exchanges") or []),
        "region_physics": list(policy.get("region_physics") or []),
        "detail": policy.get("detail"),
    }
