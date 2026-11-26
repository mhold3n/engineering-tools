"""Phase E structural mesh from heated-vessel CAD identity.

Agents: Gmsh keeps body.shell and body.lid as separate volumes after
deleting gas. IDs from import_identity. Missing gmsh is missing. No
BooleanUnion of the lid into the shell. No Cylinder() fallback.
"""

from __future__ import annotations

import shutil
import subprocess
import json
from pathlib import Path
from typing import Any, Callable

from engineering_tools.e_cad import DEMO_STEP_PATH
from engineering_tools.e_mesh import finite_positive_mesh_size, make_mesh_record, validate_mesh
from engineering_tools.e_mesh_geo import classified_vessel_step_geo
from engineering_tools.e_msh2 import interface_nodes_from_physical, interface_vertex_xyz, msh_content_id

INNER_WALL = "face.inner_wall"
REQUIRED_IDS = frozenset({"body.shell", "body.lid", INNER_WALL})


def gmsh_available() -> bool:
    return shutil.which("gmsh") is not None


def write_solid_geo(path: Path, *, h_max: float = 0.012) -> bool:
    """Keep shell and lid volumes after deleting gas.

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
Delete { Volume{gasVols[]}; }
s() = Unique(Abs(Boundary{ Volume{shellVols[0]}; }));
innerSurfs[] = {};
For i In {0:#s()-1}
  bb() = BoundingBox Surface {s(i)};
  dx = bb(3)-bb(0); dy = bb(4)-bb(1); dz = bb(5)-bb(2);
  If (dx < 0.041 && dx > 0.039 && dz > 0.039 && dz < 0.041)
    innerSurfs[] += {s(i)};
  EndIf
EndFor
Physical Volume("body.shell") = {shellVols[0]};
Physical Volume("body.lid") = {lidVols[0]};
Physical Surface("face.inner_wall") = innerSurfs[];
"""
        + f"Mesh.CharacteristicLengthMax = {float(h_max)};\n",
        encoding="utf-8",
    )
    return True


def _count_msh_nodes(msh: Path) -> int:
    text = msh.read_text(encoding="utf-8", errors="replace")
    if "$Nodes" not in text:
        return 0
    after = text.split("$Nodes", 1)[1]
    lines = [ln.strip() for ln in after.splitlines() if ln.strip() and not ln.startswith("$")]
    # MSH 2: first line is node count. MSH 4: numEntityBlocks numNodes ...
    parts = lines[0].split()
    if len(parts) >= 2:
        return int(parts[1])
    return int(parts[0])


def write_solid_mesh(
    out: Path,
    identity: dict[str, Any],
    *,
    run_gmsh: Callable[[Path, Path], dict[str, Any]] | None = None,
    h_max: float = 0.012,
) -> dict[str, Any]:
    """Write solid.msh + mesh record bound to face.inner_wall."""
    ids = set(identity.get("entity_ids") or [])
    missing = REQUIRED_IDS - ids
    if missing:
        return {"status": "broken", "detail": f"identity missing {sorted(missing)}"}
    topo = int(identity.get("topology_version") or 1)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    geo = out / "solid.geo"
    msh = out / "solid.msh"
    if not finite_positive_mesh_size(h_max):
        return {"status": "broken", "detail": "h_max must be finite and positive"}
    if not DEMO_STEP_PATH.is_file() or not write_solid_geo(geo, h_max=h_max):
        return {"status": "broken", "detail": f"vessel STEP missing: {DEMO_STEP_PATH}"}
    if run_gmsh is None:
        if not gmsh_available():
            return {"status": "missing", "detail": "gmsh not on PATH"}
        run_gmsh = _run_gmsh
    ran = run_gmsh(geo, msh)
    if ran.get("status") in {"missing", "broken"}:
        return ran
    n_nodes = int(ran.get("n_nodes") or (_count_msh_nodes(msh) if msh.is_file() else 0))
    n_iface = int(ran.get("n_interface") or 0)
    if msh.is_file() and n_iface <= 0:
        n_iface = len(interface_nodes_from_physical(msh.read_text(encoding="utf-8", errors="replace")))
    iface_xyz: list[list[float]] = []
    mesh_id = "solid.shell_lid"
    if msh.is_file():
        text = msh.read_text(encoding="utf-8", errors="replace")
        iface_xyz = interface_vertex_xyz(text)
        mesh_id = msh_content_id(msh)
        if n_iface <= 0:
            n_iface = len(iface_xyz)
    if n_nodes <= 0:
        return {"status": "broken", "detail": "solid mesh has no nodes"}
    if n_iface <= 0:
        return {"status": "broken", "detail": "Physical Surface face.inner_wall has no vertices"}
    record = make_mesh_record(
        mesh_id=mesh_id,
        participant="Solid",
        topology_version=topo,
        entity_id=INNER_WALL,
        mesh_set="PhysicalSurface:face.inner_wall",
        node_count=n_iface,
        refinement={"boundary_layer": False, "levels": 1, "tool": "gmsh", "kind": "tet", "h_max": float(h_max)},
    )
    check = validate_mesh(record, current_topology_version=topo)
    if check["status"] != "ok":
        return check
    (out / "solid-mesh.json").write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    record = dict(record)
    record["status"] = "ok"
    record["detail"] = "solid mesh"
    record["artifact"] = str(msh)
    record["interface_vertices"] = n_iface
    record["volume_nodes"] = n_nodes
    record["interface_vertex_xyz"] = iface_xyz
    record["h_max_m"] = float(h_max)
    return record


def _run_gmsh(geo: Path, msh: Path) -> dict[str, Any]:
    gmsh = shutil.which("gmsh")
    if gmsh is None:
        return {"status": "missing", "detail": "gmsh not on PATH"}
    try:
        proc = subprocess.run(
            [gmsh, "-3", str(geo), "-o", str(msh), "-format", "msh2"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "broken", "detail": f"gmsh failed: {exc}"}
    if proc.returncode != 0 or not msh.is_file():
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        hint = tail[-1] if tail else f"exit {proc.returncode}"
        return {"status": "broken", "detail": f"gmsh: {hint}"}
    return {"status": "ok", "n_nodes": _count_msh_nodes(msh)}
