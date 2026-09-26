"""Phase E physics-specific mesh metadata bound to canonical entities.

Agents: this is discretization identity, not a mesher. Records are synthetic
JSON metadata (mesh_id, participant, source topology_version, entity→mesh-set
bindings, quality, refinement). Fluid and structural patches on the same
canonical face may have unequal node counts. Never call Gmsh here. Stale
topology_version vs the current model is broken; missing face binding is broken.
"""

from __future__ import annotations

from typing import Any


def _ok(detail: str) -> dict[str, Any]:
    return {"status": "ok", "detail": detail}


def _broken(detail: str) -> dict[str, Any]:
    return {"status": "broken", "detail": detail}


def _face_bindings(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Return bindings that name a non-empty canonical entity."""
    raw = record.get("bindings")
    if not isinstance(raw, list):
        return []
    return [b for b in raw if isinstance(b, dict) and str(b.get("entity_id") or "")]


def validate_mesh(
    record: dict[str, Any],
    *,
    current_topology_version: int | None = None,
) -> dict[str, Any]:
    """Fail-closed mesh record. Does not generate or inspect Gmsh files."""
    if not record.get("mesh_id"):
        return _broken("mesh_id required")
    if not record.get("participant"):
        return _broken("participant required")
    if "topology_version" not in record:
        return _broken("source topology_version required")
    if "quality" not in record:
        return _broken("quality metrics required")
    if "refinement" not in record:
        return _broken("refinement settings required")
    bindings = _face_bindings(record)
    if not bindings:
        return _broken("canonical face binding required")
    source_tv = int(record["topology_version"])
    if current_topology_version is not None and source_tv != int(current_topology_version):
        return _broken(
            f"stale topology_version {source_tv}; current is {current_topology_version}"
        )
    return _ok(str(record["mesh_id"]))


def validate_interface_meshes(
    meshes: list[dict[str, Any]],
    *,
    canonical_face_id: str,
    current_topology_version: int | None = None,
) -> dict[str, Any]:
    """Independent participant meshes may share a face with unequal node counts."""
    if not canonical_face_id:
        return _broken("canonical_face_id required")
    if not isinstance(meshes, list) or len(meshes) < 2:
        return _broken("interface requires at least two participant meshes")
    node_counts: list[int] = []
    for mesh in meshes:
        check = validate_mesh(mesh, current_topology_version=current_topology_version)
        if check["status"] != "ok":
            return check
        bound = False
        for binding in _face_bindings(mesh):
            if str(binding["entity_id"]) == canonical_face_id:
                bound = True
                if "node_count" in binding:
                    node_counts.append(int(binding["node_count"]))
        if not bound:
            return _broken(f"mesh {mesh.get('mesh_id')} missing binding to {canonical_face_id}")
    # Unequal node_counts are valid; conformal coincidence is not required.
    return _ok(f"interface {canonical_face_id} node_counts={node_counts}")
