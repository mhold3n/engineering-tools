"""Phase E canonical engineering model (JSON-serializable).

Agents: this graph is identity + intent. Meshes, adapters, and preCICE are
downstream. CAD edits bump topology_version; they do not silently reuse IDs.
"""

from __future__ import annotations

import json
from typing import Any

from engineering_tools.e_field import validate_field
from engineering_tools.e_material import validate_material
from engineering_tools.e_region import validate_region

ENTITY_KINDS = frozenset({"assembly", "body", "face", "edge", "interface", "region"})
RELATION_KINDS = frozenset(
    {"contact", "joint", "connector", "fluid_solid", "thermal", "coupling"}
)


def _ok(detail: str) -> dict[str, Any]:
    return {"status": "ok", "detail": detail}


def _broken(detail: str) -> dict[str, Any]:
    return {"status": "broken", "detail": detail}


def empty_model(*, topology_version: int = 1) -> dict[str, Any]:
    """Empty versioned model shell."""
    return {
        "schema_version": 1,
        "topology_version": int(topology_version),
        "cad_fingerprint": None,
        "entities": [],
        "lineage": [],
        "materials": [],
        "regions": [],
        "loads": [],
        "bcs": [],
        "relations": [],
        "fields": [],
        "interfaces": [],
        "time_state": {"global_time_s": 0.0, "window_index": 0},
    }


def validate_entity(record: dict[str, Any]) -> dict[str, Any]:
    if not record.get("entity_id"):
        return _broken("entity_id required")
    kind = str(record.get("kind") or "")
    if kind not in ENTITY_KINDS:
        return _broken(f"unknown entity kind: {kind}")
    if "topology_version" not in record:
        return _broken("entity topology_version required")
    return _ok(str(record["entity_id"]))


def validate_load(record: dict[str, Any]) -> dict[str, Any]:
    if not record.get("load_id"):
        return _broken("load_id required")
    if not record.get("entity_id"):
        return _broken("load must attach to entity_id")
    if not record.get("quantity"):
        return _broken("load quantity required")
    return _ok(str(record["load_id"]))


def validate_relation(record: dict[str, Any]) -> dict[str, Any]:
    if not record.get("relation_id"):
        return _broken("relation_id required")
    kind = str(record.get("kind") or "")
    if kind not in RELATION_KINDS:
        return _broken(f"unknown relation kind: {kind}")
    regions = record.get("region_ids")
    if not isinstance(regions, list) or len(regions) < 2:
        return _broken("relation region_ids must list at least two regions")
    return _ok(str(record["relation_id"]))


def validate_interface(record: dict[str, Any]) -> dict[str, Any]:
    if not record.get("interface_id"):
        return _broken("interface_id required")
    if not record.get("entity_id"):
        return _broken("interface entity_id required")
    pairs = record.get("field_pairs")
    if not isinstance(pairs, list) or not pairs:
        return _broken("interface field_pairs required")
    return _ok(str(record["interface_id"]))


def validate_model(model: dict[str, Any]) -> dict[str, Any]:
    """Validate a full canonical model. Schema-valid even if adapters are missing."""
    if int(model.get("schema_version") or 0) != 1:
        return _broken("schema_version must be 1")
    if "topology_version" not in model:
        return _broken("topology_version required")
    for ent in model.get("entities") or []:
        r = validate_entity(ent)
        if r["status"] != "ok":
            return r
    for mat in model.get("materials") or []:
        r = validate_material(mat)
        if r["status"] != "ok":
            return r
    for reg in model.get("regions") or []:
        r = validate_region(reg)
        if r["status"] != "ok":
            return r
    for load in model.get("loads") or []:
        r = validate_load(load)
        if r["status"] != "ok":
            return r
    for rel in model.get("relations") or []:
        r = validate_relation(rel)
        if r["status"] != "ok":
            return r
    for field in model.get("fields") or []:
        r = validate_field(field)
        if r["status"] != "ok":
            return r
    for iface in model.get("interfaces") or []:
        r = validate_interface(iface)
        if r["status"] != "ok":
            return r
    entity_ids = {e["entity_id"] for e in (model.get("entities") or [])}
    for field in model.get("fields") or []:
        support = field.get("support_entity_id")
        if support not in entity_ids:
            return _broken(f"field support_entity_id unknown: {support}")
        if not field.get("owner_participant"):
            return _broken("field owner_participant required")
    return _ok("model")


def dumps_model(model: dict[str, Any]) -> str:
    check = validate_model(model)
    if check["status"] != "ok":
        raise ValueError(check["detail"])
    return json.dumps(model, sort_keys=True, indent=2)


def loads_model(text: str) -> dict[str, Any]:
    model = json.loads(text)
    check = validate_model(model)
    if check["status"] != "ok":
        raise ValueError(check["detail"])
    return model
