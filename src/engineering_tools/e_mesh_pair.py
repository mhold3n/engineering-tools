"""Pair solid+fluid E meshes on the same CAD face identity.

Agents: both writers tag Physical Surface face.inner_wall. pair.json records
solid interface vertices and fluid preCICE faceCenter locations. Equal counts
on one mesh pair are allowed (same h_max, independent Gmsh jobs). Cross-level
U11 refinement still fails if either interface count is unchanged between
coarse and fine.
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
    run_gmsh_fluid: Callable[..., dict[str, Any]] | None = None,
    h_max: float = 0.012,
) -> dict[str, Any]:
    """Write artifacts/.../meshes/solid and .../fluid plus pair.json."""
    ident = identity if identity is not None else import_identity()
    if ident.get("status") in {"missing", "broken"}:
        return {"status": ident["status"], "detail": ident.get("detail"), "e_mesh_ok": False}
    topo = int(ident.get("topology_version") or 1)
    root = Path(out)
    solid_dir = root / "solid"
    fluid_dir = root / "fluid"
    gmsh_kw: dict[str, Any] = {"h_max": float(h_max)}
    if run_gmsh is not None:
        gmsh_kw["run_gmsh"] = run_gmsh
    fluid_kw: dict[str, Any] = {"h_max": float(h_max)}
    if run_gmsh_fluid is not None:
        fluid_kw["run_gmsh"] = run_gmsh_fluid
    elif run_gmsh is not None:
        fluid_kw["run_gmsh"] = run_gmsh
    solid = write_solid_mesh(solid_dir, ident, **gmsh_kw)
    fluid = write_fluid_mesh(fluid_dir, ident, **fluid_kw)
    if solid.get("status") != "ok":
        return {**solid, "e_mesh_ok": False}
    if fluid.get("status") != "ok":
        return {**fluid, "e_mesh_ok": False}
    pair = validate_interface_meshes(
        [solid, fluid],
        canonical_face_id=INNER_WALL,
        current_topology_version=topo,
    )
    n_solid = int(solid.get("interface_vertices") or solid["bindings"][0]["node_count"])
    n_fluid = int(fluid.get("interface_locations") or fluid["bindings"][0]["node_count"])
    if pair["status"] != "ok":
        return {**pair, "e_mesh_ok": False, "solid": solid, "fluid": fluid}
    payload = {
        "status": "ok",
        "e_mesh_ok": True,
        "detail": pair["detail"],
        "canonical_face_id": INNER_WALL,
        "topology_version": topo,
        "solid_interface_vertices": n_solid,
        "fluid_interface_locations": n_fluid,
        "solid_interface_vertex_xyz": list(solid.get("interface_vertex_xyz") or []),
        "fluid_interface_facecenter_xyz": list(fluid.get("interface_facecenter_xyz") or []),
        "solid_mesh_id": str(solid.get("mesh_id") or ""),
        "fluid_mesh_id": str(fluid.get("mesh_id") or ""),
        "solid_volume_nodes": int(solid.get("volume_nodes") or 0),
        "fluid_volume_nodes": int(fluid.get("volume_nodes") or 0),
        "independent": True,
        "generators": ["gmsh-solid-geo", "gmsh-fluid-geo"],
        "h_max_m": float(h_max),
        "solid": solid,
        "fluid": fluid,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "pair.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload
