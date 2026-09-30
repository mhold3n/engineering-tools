"""Pair solid+fluid E meshes on the same CAD face identity.

Agents: fail-closed if either binding missing or node counts equal-and-required
conformal. Unequal node counts are the success path. Does not start preCICE.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from engineering_tools.e_cad import import_identity
from engineering_tools.e_mesh import validate_interface_meshes
from engineering_tools.e_mesh_fluid import write_fluid_mesh
from engineering_tools.e_mesh_solid import write_solid_mesh

INNER_WALL = "face.inner_wall"


def mesh_e_reference(
    out: Path,
    *,
    identity: dict[str, Any] | None = None,
    run_gmsh: Callable[..., dict[str, Any]] | None = None,
    run_blockmesh: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Write artifacts/.../meshes/solid and .../fluid plus pair.json."""
    ident = identity if identity is not None else import_identity()
    if ident.get("status") in {"missing", "broken"}:
        return {"status": ident["status"], "detail": ident.get("detail"), "e_mesh_ok": False}
    topo = int(ident.get("topology_version") or 1)
    root = Path(out)
    solid_dir = root / "solid"
    fluid_dir = root / "fluid"
    gmsh_kw = {} if run_gmsh is None else {"run_gmsh": run_gmsh}
    foam_kw = {} if run_blockmesh is None else {"run_blockmesh": run_blockmesh}
    solid = write_solid_mesh(solid_dir, ident, **gmsh_kw)
    fluid = write_fluid_mesh(fluid_dir, ident, **foam_kw)
    if solid.get("status") != "ok":
        return {**solid, "e_mesh_ok": False}
    if fluid.get("status") != "ok":
        return {**fluid, "e_mesh_ok": False}
    pair = validate_interface_meshes(
        [solid, fluid],
        canonical_face_id=INNER_WALL,
        current_topology_version=topo,
    )
    n_solid = int(solid["bindings"][0]["node_count"])
    n_fluid = int(fluid["bindings"][0]["node_count"])
    if pair["status"] != "ok":
        return {**pair, "e_mesh_ok": False, "solid": solid, "fluid": fluid}
    payload = {
        "status": "ok",
        "e_mesh_ok": True,
        "detail": pair["detail"],
        "canonical_face_id": INNER_WALL,
        "topology_version": topo,
        "solid_nodes": n_solid,
        "fluid_nodes": n_fluid,
        "solid": solid,
        "fluid": fluid,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "pair.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload
