"""Phase E fluid volume mesh from vessel.step gas volume.

Agents: Gmsh tet of body.gas after a millimeter to meter Dilate. Physical Surface name is
face.inner_wall, the same CAD entity as the solid inner wall. Missing gmsh
is missing. preCICE Fluid locations are faceCenters on that tagged surface.
No Cylinder() fallback.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from engineering_tools.e_cad import DEMO_STEP_PATH
from engineering_tools.e_mesh import finite_positive_mesh_size, make_mesh_record, validate_mesh
from engineering_tools.e_mesh_geo import classified_vessel_step_geo
from engineering_tools.e_mesh_solid import _count_msh_nodes, _run_gmsh, gmsh_available
from engineering_tools.e_msh2 import (
    interface_facecenter_xyz,
    interface_nodes_from_physical,
    interface_triangle_count,
    msh_content_id,
)

INNER_WALL = "face.inner_wall"
REQUIRED_IDS = frozenset({"body.gas", INNER_WALL})


def write_fluid_geo(path: Path, *, h_max: float = 0.012) -> bool:
    """Keep gas volume from scaled vessel.step.

    False when h_max is not finite and positive, and when the STEP is missing.
    A refused size does not create the geo file.
    """
    if not finite_positive_mesh_size(h_max):
        return False
    header = classified_vessel_step_geo()
    if header is None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        header
        + """
Delete { Volume{shellVols[]}; }
Delete { Volume{lidVols[]}; }
s() = Unique(Abs(Boundary{ Volume{gasVols[]}; }));
innerSurfs[] = {};
lidSurfs[] = {};
baseSurfs[] = {};
For i In {0:#s()-1}
  bb() = BoundingBox Surface {s(i)};
  dx = bb(3)-bb(0); dy = bb(4)-bb(1); dz = bb(5)-bb(2);
  cz = (bb(2)+bb(5))/2;
  If (dx < 0.041 && dx > 0.039 && dz > 0.039 && dz < 0.041)
    innerSurfs[] += {s(i)};
  EndIf
  If (dz < 0.001 && cz > 0.03)
    lidSurfs[] += {s(i)};
  EndIf
  If (dz < 0.001 && cz < 0.01)
    baseSurfs[] += {s(i)};
  EndIf
EndFor
Physical Volume("body.gas") = gasVols[];
Physical Surface("face.inner_wall") = innerSurfs[];
Physical Surface("lid") = lidSurfs[];
Physical Surface("base") = baseSurfs[];
"""
        + f"Mesh.CharacteristicLengthMax = {float(h_max)};\n",
        encoding="utf-8",
    )
    return True


def write_fluid_mesh(
    out: Path,
    identity: dict[str, Any],
    *,
    run_gmsh: Callable[[Path, Path], dict[str, Any]] | None = None,
    h_max: float = 0.012,
) -> dict[str, Any]:
    """Write fluid.msh + record bound to Physical Surface face.inner_wall."""
    ids = set(identity.get("entity_ids") or [])
    missing = REQUIRED_IDS - ids
    if missing:
        return {"status": "broken", "detail": f"identity missing {sorted(missing)}"}
    topo = int(identity.get("topology_version") or 1)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    geo = out / "fluid.geo"
    msh = out / "fluid.msh"
    if not finite_positive_mesh_size(h_max):
        return {"status": "broken", "detail": "h_max must be finite and positive"}
    if not DEMO_STEP_PATH.is_file() or not write_fluid_geo(geo, h_max=h_max):
        return {"status": "broken", "detail": f"vessel STEP missing: {DEMO_STEP_PATH}"}
    if run_gmsh is None:
        if not gmsh_available():
            return {"status": "missing", "detail": "gmsh not on PATH"}
        run_gmsh = _run_gmsh
    ran = run_gmsh(geo, msh)
    if ran.get("status") in {"missing", "broken"}:
        return ran
    n_vol = int(ran.get("n_nodes") or (_count_msh_nodes(msh) if msh.is_file() else 0))
    n_loc = int(ran.get("n_interface") or 0)
    iface_xyz: list[list[float]] = []
    mesh_id = "fluid.gas"
    if msh.is_file():
        text = msh.read_text(encoding="utf-8", errors="replace")
        iface_xyz = interface_facecenter_xyz(text, INNER_WALL)
        mesh_id = msh_content_id(msh)
        if n_loc <= 0:
            n_loc = len(iface_xyz) or interface_triangle_count(text, INNER_WALL)
        if n_loc <= 0:
            n_loc = len(interface_nodes_from_physical(text, INNER_WALL))
        if iface_xyz:
            n_loc = len(iface_xyz)
    if n_vol <= 0 and n_loc <= 0:
        return {"status": "broken", "detail": "fluid mesh has no nodes"}
    if n_loc <= 0:
        return {"status": "broken", "detail": "Physical Surface face.inner_wall has no locations"}
    record = make_mesh_record(
        mesh_id=mesh_id,
        participant="Fluid",
        topology_version=topo,
        entity_id=INNER_WALL,
        mesh_set="PhysicalSurface:face.inner_wall",
        node_count=n_loc,
        refinement={
            "boundary_layer": False,
            "levels": 1,
            "tool": "gmsh",
            "kind": "tet-cylinder",
            "h_max": float(h_max),
        },
    )
    check = validate_mesh(record, current_topology_version=topo)
    if check["status"] != "ok":
        return check
    (out / "fluid-mesh.json").write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    record = dict(record)
    record["status"] = "ok"
    record["detail"] = "fluid mesh"
    record["artifact"] = str(msh)
    record["interface_locations"] = n_loc
    record["volume_nodes"] = n_vol
    record["interface_facecenter_xyz"] = iface_xyz
    record["h_max_m"] = float(h_max)
    return record
