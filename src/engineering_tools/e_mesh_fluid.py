"""Phase E fluid volume mesh for body.gas, wall patch = face.inner_wall.

Agents: first mesh is blockMesh envelope of the gas cylinder (r=20 mm, h=40 mm)
in metres. snappy deferred. Missing blockMesh is missing. Not D cavity writer.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable

from engineering_tools.e_mesh import make_mesh_record, validate_mesh
from engineering_tools.hello_probes import _openfoam_tool, _run_openfoam

INNER_WALL = "face.inner_wall"
REQUIRED_IDS = frozenset({"body.gas", INNER_WALL})


def blockmesh_available() -> bool:
    return _openfoam_tool("blockMesh") is not None


def write_fluid_block_mesh_dict(path: Path) -> None:
    """Hex envelope of gas cylinder; patch inner_wall is the cylindrical-ish -X face."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      blockMeshDict;
}
convertToMeters 1;
vertices
(
    (-0.02 -0.02 0)
    ( 0.02 -0.02 0)
    ( 0.02  0.02 0)
    (-0.02  0.02 0)
    (-0.02 -0.02 0.04)
    ( 0.02 -0.02 0.04)
    ( 0.02  0.02 0.04)
    (-0.02  0.02 0.04)
);
blocks
(
    hex (0 1 2 3 4 5 6 7) (8 8 8) simpleGrading (1 1 1)
);
edges
(
);
boundary
(
    inner_wall
    {
        type wall;
        faces
        (
            (0 4 7 3)
        );
    }
    lid
    {
        type patch;
        faces
        (
            (4 5 6 7)
        );
    }
    base
    {
        type wall;
        faces
        (
            (0 3 2 1)
        );
    }
    outer
    {
        type patch;
        faces
        (
            (1 5 4 0)
            (2 6 5 1)
            (3 7 6 2)
        );
    }
);
mergePatchPairs
(
);
""",
        encoding="utf-8",
    )


def _count_poly_points(case: Path) -> int:
    points = case / "constant" / "polyMesh" / "points"
    if not points.is_file():
        return 0
    text = points.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.isdigit():
            return int(stripped)
    return 0


def write_fluid_mesh(
    out: Path,
    identity: dict[str, Any],
    *,
    run_blockmesh: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Write OpenFOAM case + record bound to face.inner_wall."""
    ids = set(identity.get("entity_ids") or [])
    missing = REQUIRED_IDS - ids
    if missing:
        return {"status": "broken", "detail": f"identity missing {sorted(missing)}"}
    topo = int(identity.get("topology_version") or 1)
    case = Path(out)
    (case / "system").mkdir(parents=True, exist_ok=True)
    (case / "constant" / "polyMesh").mkdir(parents=True, exist_ok=True)
    write_fluid_block_mesh_dict(case / "system" / "blockMeshDict")
    control = case / "system" / "controlDict"
    if not control.is_file():
        control.write_text(
            "FoamFile { version 2.0; format ascii; class dictionary; object controlDict; }\n"
            "application blockMesh; startFrom startTime; startTime 0; stopAt endTime; "
            "endTime 1; deltaT 1; writeControl timeStep; writeInterval 1;\n",
            encoding="utf-8",
        )
    fv = case / "system" / "fvSchemes"
    if not fv.is_file():
        fv.write_text(
            "FoamFile { version 2.0; format ascii; class dictionary; object fvSchemes; }\n"
            "ddtSchemes { default Euler; } gradSchemes { default Gauss linear; } "
            "divSchemes { default none; } laplacianSchemes { default Gauss linear orthogonal; } "
            "interpolationSchemes { default linear; } snGradSchemes { default orthogonal; }\n",
            encoding="utf-8",
        )
    sol = case / "system" / "fvSolution"
    if not sol.is_file():
        sol.write_text(
            "FoamFile { version 2.0; format ascii; class dictionary; object fvSolution; }\n"
            "solvers {}\n",
            encoding="utf-8",
        )
    if run_blockmesh is None:
        if not blockmesh_available():
            return {"status": "missing", "detail": "blockMesh or foamExec not on PATH"}
        run_blockmesh = _run_blockmesh
    ran = run_blockmesh(case)
    if ran.get("status") in {"missing", "broken"}:
        return ran
    n_nodes = int(ran.get("n_nodes") or _count_poly_points(case))
    if n_nodes <= 0:
        return {"status": "broken", "detail": "fluid mesh has no points"}
    record = make_mesh_record(
        mesh_id="fluid.gas",
        participant="Fluid",
        topology_version=topo,
        entity_id=INNER_WALL,
        mesh_set="patch:inner_wall",
        node_count=n_nodes,
        refinement={
            "boundary_layer": False,
            "levels": 1,
            "tool": "blockMesh",
            "kind": "hex-envelope",
            "note": "first mesh; snappy deferred",
        },
    )
    check = validate_mesh(record, current_topology_version=topo)
    if check["status"] != "ok":
        return check
    (case / "fluid-mesh.json").write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    record = dict(record)
    record["status"] = "ok"
    record["detail"] = "fluid mesh"
    record["artifact"] = str(case / "constant" / "polyMesh")
    return record


def _run_blockmesh(case: Path) -> dict[str, Any]:
    located = _openfoam_tool("blockMesh")
    if located is None:
        return {"status": "missing", "detail": "blockMesh or foamExec not on PATH"}
    argv, _locator = located
    try:
        proc = _run_openfoam(argv, case)
    except (OSError, shutil.Error) as exc:
        return {"status": "broken", "detail": f"blockMesh failed: {exc}"}
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        hint = tail[-1] if tail else f"exit {proc.returncode}"
        return {"status": "broken", "detail": f"blockMesh: {hint}"}
    n_nodes = _count_poly_points(case)
    if n_nodes <= 0:
        return {"status": "broken", "detail": "blockMesh did not write constant/polyMesh/points"}
    return {"status": "ok", "n_nodes": n_nodes}
