"""Phase E field records: solver-agnostic typed exchange.

Agents: this is the coupling abstraction, not a solver path. Mechanical,
thermal, fluid, and future fields share validate_field / dumps. Status is
ok or broken (schema). Adapter coverage is e_capabilities (missing vs ok).
"""

from __future__ import annotations

from typing import Any

FIELD_KINDS = frozenset({"scalar", "vector", "tensor"})

# Quantity id → (rank, SI unit token). Rank must match field kind.
QUANTITIES: dict[str, tuple[str, str]] = {
    "displacement": ("vector", "m"),
    "traction": ("vector", "Pa"),
    "force": ("vector", "N"),
    "pressure": ("scalar", "Pa"),
    "velocity": ("vector", "m/s"),
    "temperature": ("scalar", "K"),
    "heat_flux": ("vector", "W/m2"),
    "density": ("scalar", "kg/m3"),
    "enthalpy": ("scalar", "J/kg"),
    "species_mass_fraction": ("scalar", "1"),
}

INTENSIVE_EXTENSIVE = frozenset({"intensive", "extensive"})


def validate_field(record: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed field schema. Does not check solver capability."""
    required = (
        "field_id",
        "quantity",
        "kind",
        "si_unit",
        "frame_id",
        "support_entity_id",
        "owner_participant",
        "consumer_participants",
        "mapping_method",
        "extent",
        "conservation",
    )
    missing = [k for k in required if k not in record or record[k] in (None, "")]
    if missing:
        return {"status": "broken", "detail": f"field missing {missing}"}
    kind = str(record["kind"])
    if kind not in FIELD_KINDS:
        return {"status": "broken", "detail": f"unknown field kind: {kind}"}
    qty = str(record["quantity"])
    spec = QUANTITIES.get(qty)
    if spec is None:
        return {"status": "broken", "detail": f"unknown quantity: {qty}"}
    expect_kind, expect_unit = spec
    if kind != expect_kind:
        return {"status": "broken", "detail": f"{qty} requires kind {expect_kind}, got {kind}"}
    if str(record["si_unit"]) != expect_unit:
        return {
            "status": "broken",
            "detail": f"{qty} requires si_unit {expect_unit}, got {record['si_unit']}",
        }
    consumers = record["consumer_participants"]
    if not isinstance(consumers, list) or not consumers:
        return {"status": "broken", "detail": "consumer_participants must be a non-empty list"}
    extent = str(record["extent"])
    if extent not in INTENSIVE_EXTENSIVE:
        return {"status": "broken", "detail": f"unknown extent: {extent}"}
    return {"status": "ok", "detail": str(record["field_id"])}


def dumps_field(record: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe copy after validation."""
    check = validate_field(record)
    if check["status"] != "ok":
        raise ValueError(check["detail"])
    return dict(record)
