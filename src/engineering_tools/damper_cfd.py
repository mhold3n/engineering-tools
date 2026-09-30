"""Stage a short OpenFOAM chamber case for the damper scenario.

Copies hello_cavity numerics, then rewrites blockMeshDict so the cavity box
matches housing_id_mm × housing_id_mm × chamber_length_mm (meters).
"""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path
from typing import Any

from .hello_probes import _copy_resource_tree

# Agents: keep (nx, ny) even so chamber_center_index is the geometric middle cell.
CHAMBER_NX = 20
CHAMBER_NY = 20
CHAMBER_NZ = 1


def chamber_center_index(nx: int = CHAMBER_NX, ny: int = CHAMBER_NY, nz: int = CHAMBER_NZ) -> int:
    """OpenFOAM hex cell order i + j*nx + k*nx*ny."""
    return (nz // 2) * nx * ny + (ny // 2) * nx + (nx // 2)


def chamber_wall_index(nx: int = CHAMBER_NX, ny: int = CHAMBER_NY, nz: int = CHAMBER_NZ) -> int:
    """Cell on i=0 at mid-j: stand-in for chamber_wall (fixed wall of the cavity)."""
    return (nz // 2) * nx * ny + (ny // 2) * nx


def write_chamber_case(params: dict[str, Any], work: Path) -> dict[str, Any]:
    """Copy hello_cavity and size the block to the chamber params (meters)."""
    root = resources.files("engineering_tools")
    _copy_resource_tree(root / "data" / "openfoam" / "hello_cavity", work)
    lx = float(params["housing_id_mm"]) * 1e-3
    ly = lx
    lz = float(params["chamber_length_mm"]) * 1e-3
    nx, ny, nz = CHAMBER_NX, CHAMBER_NY, CHAMBER_NZ
    text = f"""/*--------------------------------*- C++ -*----------------------------------*\\
| engineering-tools damper chamber (hello_cavity numerics, chamber size)     |
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      blockMeshDict;
}}
convertToMeters 1;

vertices
(
    (0 0 0)
    ({lx} 0 0)
    ({lx} {ly} 0)
    (0 {ly} 0)
    (0 0 {lz})
    ({lx} 0 {lz})
    ({lx} {ly} {lz})
    (0 {ly} {lz})
);

blocks
(
    hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading (1 1 1)
);

edges
(
);

boundary
(
    movingWall
    {{
        type wall;
        faces
        (
            (3 7 6 2)
        );
    }}
    fixedWalls
    {{
        type wall;
        faces
        (
            (0 4 7 3)
            (2 6 5 1)
            (1 5 4 0)
        );
    }}
    frontAndBack
    {{
        type empty;
        faces
        (
            (0 3 2 1)
            (4 5 6 7)
        );
    }}
);

mergePatchPairs
(
);
"""
    (work / "system" / "blockMeshDict").write_text(text, encoding="utf-8")
    meta = {"nx": nx, "ny": ny, "nz": nz, "lx": lx, "ly": ly, "lz": lz}
    (work / "mesh.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def parse_internal_field_p(text: str, cell_index: int | None = None) -> float:
    """Parse OpenFOAM p. Uniform scalar, or one cell / max |cell| of a nonuniform list."""
    match = re.search(r"internalField\s+uniform\s+([-+0-9.eE]+)\s*;", text)
    if match:
        return float(match.group(1))
    match = re.search(
        r"internalField\s+nonuniform\s+List<scalar>\s*\d*\s*\((.*?)\)\s*;",
        text,
        re.S,
    )
    if not match:
        raise ValueError("internalField uniform scalar not found")
    numbers = [float(n) for n in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", match.group(1))]
    if not numbers:
        raise ValueError("nonuniform p list was empty")
    if cell_index is None:
        return max(abs(n) for n in numbers)
    if cell_index < 0 or cell_index >= len(numbers):
        raise ValueError(f"p cell_index {cell_index} out of range {len(numbers)}")
    return numbers[cell_index]
