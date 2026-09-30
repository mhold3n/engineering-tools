"""OpenFOAM participant adapter for C-FSI.

Agents: Fluid is a preCICE participant. `prepare_fluid_participant` writes
`precice-adapter-config.yml` and the OpenFOAM-preCICE function object.
This module may execute `blockMesh` and `pimpleFoam`. It must not execute
`precice`. The façade later starts `pimpleFoam` in the prepared case so
`libpreciceAdapterFunctionObject.so` attaches participant Fluid to
`precice-config.xml`. `sample_c_probes` returns SI pascals. Incompressible
`p` is kinematic (m^2/s^2), same conversion as A (`kinematic_to_pa`).
Wall xyz is the −X `interface` patch centre parsed from blockMeshDict,
not the cell centre.
"""

from __future__ import annotations

import os
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
endTime         0.02;
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
divSchemes { default none; div(phi,U) Gauss linear; div((nuEff*dev2(T(grad(U))))) Gauss linear; }
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
    pcorr { $p; }
    pcorrFinal { $pcorr; relTol 0; }
    Phi { $p; }
    "(U|cellDisplacement)"
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-5;
        relTol          0;
        minIter         1;
    }
    "(U|cellDisplacement)Final"
    {
        $U;
        relTol          0;
    }
}
PIMPLE
{
    nOuterCorrectors 1;
    nCorrectors 2;
    nNonOrthogonalCorrectors 1;
    correctPhi      true;
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


# OpenFOAM-preCICE function object. Name matches the adapter tutorial type.
# pRef, pointDisplacement, and cellDisplacement stay in their own files.
_ADAPTER_FUNCTION = """
functions
{
    preciceAdapter
    {
        type            preciceAdapterFunctionObject;
        libs            ("libpreciceAdapterFunctionObject.so");
    }
}
"""


def _with_adapter_function(control: str) -> str:
    """Append the preCICE function object when controlDict does not have it.

    Agents: a second `functions` dictionary is a Foam error, so this returns
    the text unchanged once both the type and the library name are present.
    """
    if "preciceAdapterFunctionObject" in control and "libpreciceAdapterFunctionObject.so" in control:
        return control
    return control.rstrip() + "\n" + _ADAPTER_FUNCTION


def _config_reference(config_xml: Path, workdir: Path) -> str:
    """Adapter path to precice-config.xml, relative to the case when possible.

    Agents: the OpenFOAM adapter opens `precice-config-file` from the case
    directory. `relpath` fails across filesystems; the absolute path is the
    fallback.
    """
    try:
        return Path(os.path.relpath(config_xml.resolve(), workdir.resolve())).as_posix()
    except (OSError, ValueError):
        return config_xml.as_posix()


def _write_precice_adapter_config(workdir: Path, config_xml: Path) -> None:
    """Write official-style precice-adapter-config.yml for participant Fluid.

    Agents: preCICE mesh `interface-fluid` is what Fluid provides in XML.
    OpenFOAM patch `interface` is the −X wall. Fluid reads Displacement
    and writes Traction (Stress is the adapter's other traction-like write).
    """
    config_ref = _config_reference(config_xml, workdir)
    text = f"""participant: Fluid

precice-config-file: "{config_ref}"

interfaces:
  - mesh: interface-fluid
    locations: faceCenters
    patches:
      - interface
    read-data:
      - Displacement
    write-data:
      - Force
"""
    dest = workdir / "precice-adapter-config.yml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    # Adapter v1.3.1 reads system/preciceDict. The yml is kept for tests.
    rho = require_density(load_params())
    config_posix = Path(config_ref).as_posix()
    dict_path = workdir / "system" / "preciceDict"
    dict_path.parent.mkdir(parents=True, exist_ok=True)
    dict_path.write_text(
        f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      preciceDict;
}}
preciceConfig "{config_posix}";
participant Fluid;
modules (FSI);
interfaces
{{
    Interface1
    {{
        mesh            interface-fluid;
        patches         (interface);
        locations       faceCenters;
        readData        (Displacement);
        writeData       (Force);
    }}
}}
FSI
{{
    rho rho [1 -3 0 0 0 0 0] {rho};
}}
""",
        encoding="utf-8",
    )


def prepare_fluid_participant(workdir: Path, config_xml: Path) -> None:
    """Stage adapter files so OpenFOAM can join as participant Fluid.

    Agents: writes the moving-mesh dicts (including pRef, pointDisplacement,
    and cellDisplacement), `precice-adapter-config.yml`, and the
    preciceAdapter function object. Does not execute precice, blockMesh,
    or pimpleFoam. The façade should start pimpleFoam in `workdir` after
    this returns; the function object loads the adapter and attaches to
    `config_xml`.
    """
    _stage_solver_dicts(workdir, 0)
    _write_precice_adapter_config(workdir, config_xml)


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
            # Two coupling windows at dt=0.01. Do not shrink endTime to one
            # window: Fluid would exit before Solid finishes the second.
            text = _with_adapter_function(body)
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


def mesh_fluid_participant(workdir: Path) -> bool:
    """blockMesh only. The façade starts pimpleFoam as the Fluid participant."""
    _stage_solver_dicts(workdir, 0)
    return _tool_ok("blockMesh", workdir)


def fluid_participant_argv() -> list[str] | None:
    """pimpleFoam argv. None if the solver is missing. No `precice` process."""
    located = _openfoam_tool("pimpleFoam")
    if located is None:
        return None
    command, _locator = located
    return list(command)


def run_step(workdir: Path, step: int) -> bool:
    """Mesh the Fluid case. Do not launch precice.

    Agents: `pimpleFoam` is no longer started here. The façade starts Solid
    and Fluid together after `prepare_fluid_participant` and this mesh step.
    """
    del step
    config_xml = workdir.parent / "precice-config.xml"
    if config_xml.is_file():
        prepare_fluid_participant(workdir, config_xml)
    return mesh_fluid_participant(workdir)


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


def sample_d_probes(out: Path) -> dict[str, Any]:
    """Wall Pa from the A chamber_wall cell, signed, not max-|p|.

    Agents: C's sample_c_probes uses max |cell| on a nonuniform list. D is
    20×20 A-cavity physics; the damper wall is i=0 mid-j, same index as A.
    """
    from engineering_tools.damper_cfd import chamber_wall_index

    pressure_path = _pressure_file(out)
    center = _interface_center_m(out)
    if pressure_path is None or center is None:
        return {}
    kinematic = parse_internal_field_p(
        pressure_path.read_text(encoding="utf-8", errors="replace"),
        cell_index=chamber_wall_index(),
    )
    pascals = kinematic_to_pa(kinematic, require_density(load_params()))
    return {
        "housing.wall.pressure": {"value": pascals, "xyz_m": list(center)},
        "housing.wall.traction": {"value": abs(pascals), "xyz_m": list(center)},
    }


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
