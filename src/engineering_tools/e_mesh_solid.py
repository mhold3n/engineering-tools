"""Phase E structural mesh from heated-vessel CAD identity.

Agents: Gmsh tet of shell+lid envelope. IDs from import_identity, not node
numbers. Missing gmsh is missing. Never call damper sandwich INP writers.
"""

from __future__ import annotations

import shutil
import subprocess
import json
from pathlib import Path
from typing import Any, Callable

from engineering_tools.e_mesh import make_mesh_record, validate_mesh

INNER_WALL = "face.inner_wall"
REQUIRED_IDS = frozenset({"body.shell", "body.lid", INNER_WALL})


def gmsh_available() -> bool:
    return shutil.which("gmsh") is not None


def write_solid_geo(path: Path) -> None:
    """Tube + lid in metres, matching data/e-demo/build_vessel.py mm sizes / 1000."""
    path.write_text(
        """SetFactory("OpenCASCADE");
Cylinder(1) = {0, 0, 0, 0, 0, 0.04, 0.025};
Cylinder(2) = {0, 0, 0, 0, 0, 0.04, 0.02};
BooleanDifference(3) = { Volume{1}; Delete; }{ Volume{2}; Delete; };
Cylinder(4) = {0, 0, 0.04, 0, 0, 0.004, 0.025};
BooleanUnion(5) = { Volume{3}; Delete; }{ Volume{4}; Delete; };
Physical Volume("body.shell_lid") = {5};
Mesh.CharacteristicLengthMax = 0.012;
""",
        encoding="utf-8",
    )


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
    write_solid_geo(geo)
    if run_gmsh is None:
        if not gmsh_available():
            return {"status": "missing", "detail": "gmsh not on PATH"}
        run_gmsh = _run_gmsh
    ran = run_gmsh(geo, msh)
    if ran.get("status") in {"missing", "broken"}:
        return ran
    n_nodes = int(ran.get("n_nodes") or (_count_msh_nodes(msh) if msh.is_file() else 0))
    if n_nodes <= 0:
        return {"status": "broken", "detail": "solid mesh has no nodes"}
    record = make_mesh_record(
        mesh_id="solid.shell_lid",
        participant="Solid",
        topology_version=topo,
        entity_id=INNER_WALL,
        mesh_set="PhysicalSurface:face.inner_wall",
        node_count=n_nodes,
        refinement={"boundary_layer": False, "levels": 1, "tool": "gmsh", "kind": "tet"},
    )
    check = validate_mesh(record, current_topology_version=topo)
    if check["status"] != "ok":
        return check
    (out / "solid-mesh.json").write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    record = dict(record)
    record["status"] = "ok"
    record["detail"] = "solid mesh"
    record["artifact"] = str(msh)
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
