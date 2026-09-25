"""OpenFOAM participant adapter for C-FSI.

Agents: the façade calls `run_step` then `sample_c_probes`. This module may
execute `blockMesh` and `pimpleFoam`. It must not execute `precice`.
`sample_c_probes` returns SI pascals. Incompressible `p` is kinematic
(m^2/s^2), same conversion as A (`kinematic_to_pa`). Wall xyz is the
−X `interface` patch centre parsed from blockMeshDict, not the cell centre.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from engineering_tools.damper_cfd import parse_internal_field_p
from engineering_tools.damper_params import kinematic_to_pa, load_params, require_density
from engineering_tools.hello_probes import _openfoam_tool, _run_openfoam

_CASE_FILES: dict[str, str] = {
    # displacementLaplacian keeps the moving wall on the named interface.
    # velocityLaplacian is the other stock choice; this dict stays minimal.
    "constant/dynamicMeshDict": """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      dynamicMeshDict;
}
dynamicFvMesh   dynamicMotionSolverFvMesh;
motionSolverLibs (fvMotionSolvers);
motionSolver    displacementLaplacian;
displacementLaplacianCoeffs
{
    diffusivity     uniform;
}
""",
    "system/controlDict": """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}
application     pimpleFoam;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         0.01;
deltaT          0.01;
writeControl    timeStep;
writeInterval   1;
purgeWrite      0;
writeFormat     ascii;
writePrecision  6;
runTimeModifiable true;
""",
    "system/fvSchemes": """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSchemes;
}
ddtSchemes { default Euler; }
gradSchemes { default Gauss linear; }
divSchemes { default none; div(phi,U) Gauss linear; }
laplacianSchemes { default Gauss linear orthogonal; }
interpolationSchemes { default linear; }
snGradSchemes { default orthogonal; }
""",
    "system/fvSolution": """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSolution;
}
solvers
{
    p { solver PCG; preconditioner DIC; tolerance 1e-6; relTol 0.05; }
    pFinal { $p; relTol 0; }
    U { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-5; relTol 0; }
    cellDisplacement
    {
        solver smoothSolver;
        smoother symGaussSeidel;
        tolerance 1e-5;
        relTol 0;
    }
}
PIMPLE
{
    nOuterCorrectors 1;
    nCorrectors 2;
    nNonOrthogonalCorrectors 0;
    pRefCell 0;
    pRefValue 0;
}
""",
    "constant/transportProperties": """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      transportProperties;
}
transportModel  Newtonian;
nu              [0 2 -1 0 0 0 0] 1e-06;
""",
    "constant/turbulenceProperties": """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      turbulenceProperties;
}
simulationType  laminar;
""",
    "0/p": """FoamFile
{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      p;
}
dimensions      [0 2 -2 0 0 0 0];
internalField   uniform 0;
boundaryField
{
    interface { type zeroGradient; }
    walls { type zeroGradient; }
    lid { type zeroGradient; }
}
""",
    "0/U": """FoamFile
{
    version     2.0;
    format      ascii;
    class       volVectorField;
    object      U;
}
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform (0 0 0);
boundaryField
{
    interface { type movingWallVelocity; value uniform (0 0 0); }
    walls { type noSlip; }
    lid { type noSlip; }
}
""",
    # pointDisplacement is the motion-solver field. cellDisplacement is solved
    # from fvSolution; this file gives every patch a value so pimpleFoam can
    # start. A preCICE adapter may replace the interface BC later.
    "0/pointDisplacement": """FoamFile
{
    version     2.0;
    format      ascii;
    class       pointVectorField;
    object      pointDisplacement;
}
dimensions      [0 1 0 0 0 0 0];
internalField   uniform (0 0 0);
boundaryField
{
    interface { type fixedValue; value uniform (0 0 0); }
    walls { type fixedValue; value uniform (0 0 0); }
    lid { type fixedValue; value uniform (0 0 0); }
}
""",
}


def _stage_solver_dicts(workdir: Path, step: int) -> None:
    """Write the minimal moving-mesh case around the C blockMeshDict.

    The mesh writer leaves blockMeshDict under constant/polyMesh. blockMesh
    reads system/blockMeshDict and then replaces constant/polyMesh, so the
    first step copies the dict into system/ before meshing.
    """
    staged = workdir / "constant" / "polyMesh" / "blockMeshDict"
    system_dict = workdir / "system" / "blockMeshDict"
    if staged.is_file():
        system_dict.parent.mkdir(parents=True, exist_ok=True)
        system_dict.write_text(staged.read_text(encoding="utf-8"), encoding="utf-8")
    for relative, body in _CASE_FILES.items():
        dest = workdir / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = body
        if relative == "system/controlDict":
            # One window per façade index. Fake pimpleFoam ignores the file.
            text = body.replace("endTime         0.01;", f"endTime         {0.01 * (step + 1)};")
        dest.write_text(text, encoding="utf-8")


def _tool_ok(name: str, workdir: Path) -> bool:
    located = _openfoam_tool(name)
    if located is None:
        return False
    command, _locator = located
    try:
        proc = _run_openfoam(command, workdir)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def run_step(workdir: Path, step: int) -> bool:
    """Mesh the C case and run pimpleFoam. True only when both exit 0."""
    _stage_solver_dicts(workdir, step)
    if not _tool_ok("blockMesh", workdir):
        return False
    return _tool_ok("pimpleFoam", workdir)


def _pressure_file(workdir: Path) -> Path | None:
    found: list[Path] = []
    for path in workdir.glob("*/p"):
        if path.parent.name != "0" and path.is_file() and path.stat().st_size > 0:
            found.append(path)
    if not found:
        return None
    return sorted(found)[-1]


def _paren_block_after(text: str, marker: str) -> str | None:
    """Interior of the first parenthesis group that follows marker.

    Agents: blockMesh lists vertices as `(x y z)` inside a vertices `(...)`
    group. Splitting that group on the first `)` keeps only vertex 0, so
    face `(0 4 7 3)` is out of range and the wall centre is None. Depth
    walking keeps every vertex line in the block.
    """
    parts = text.split(marker, 1)
    if len(parts) < 2:
        return None
    rest = parts[1]
    start = rest.find("(")
    if start < 0:
        return None
    depth = 0
    for index, char in enumerate(rest[start:], start=start):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return rest[start + 1 : index]
    return None


def _interface_center_m(workdir: Path) -> list[float] | None:
    """Average the vertices of the first `interface` face. Metres.

    Face `(0 4 7 3)` is the −X patch. Its centre is chamber_wall, not the
    hex cell centre at the origin.
    """
    candidates = (
        workdir / "system" / "blockMeshDict",
        workdir / "constant" / "polyMesh" / "blockMeshDict",
    )
    text = next((path.read_text(encoding="utf-8") for path in candidates if path.is_file()), None)
    if text is None or "vertices" not in text or "interface" not in text:
        return None
    vert_body = _paren_block_after(text, "vertices")
    if vert_body is None:
        return None
    verts: list[list[float]] = []
    for line in vert_body.splitlines():
        nums = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", line)
        if len(nums) >= 3:
            verts.append([float(nums[0]), float(nums[1]), float(nums[2])])
    iface = text.split("interface", 1)[1]
    face = re.search(r"\(\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*\)", iface)
    if face is None:
        return None
    ids = [int(face.group(i)) for i in range(1, 5)]
    if any(nid >= len(verts) for nid in ids):
        return None
    picked = [verts[nid] for nid in ids]
    return [sum(point[axis] for point in picked) / len(picked) for axis in range(3)]


def sample_c_probes(out: Path) -> dict[str, Any]:
    """Read wall pressure from the C fluid case and return SI probe rows.

    Traction magnitude is abs(wall Pa), the same B counterpart the façade
    compares. Both rows share the interface patch centre.
    """
    pressure_path = _pressure_file(out)
    center = _interface_center_m(out)
    if pressure_path is None or center is None:
        return {}
    kinematic = parse_internal_field_p(pressure_path.read_text(encoding="utf-8", errors="replace"))
    pascals = kinematic_to_pa(kinematic, require_density(load_params()))
    return {
        "housing.wall.pressure": {"value": pascals, "xyz_m": list(center)},
        "housing.wall.traction": {"value": abs(pascals), "xyz_m": list(center)},
    }
