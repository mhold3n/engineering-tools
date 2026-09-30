"""Phase E OpenFOAM deck: gas envelope, patch inner_wall = face.inner_wall.

Agents: blockMesh already names inner_wall. Adapter YAML/preciceDict must
use that patch, mesh interface-fluid, write Force (not Traction), read
Displacement. Does not launch pimpleFoam or precice.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from engineering_tools.c_adapter_openfoam import _with_adapter_function
from engineering_tools.e_mesh_fluid import INNER_WALL as MESH_FACE, write_fluid_block_mesh_dict
from engineering_tools.hello_probes import _openfoam_tool

_ESI_FOAM = Path("/usr/lib/openfoam/openfoam2512/platforms/linux64GccDPInt32Opt/bin")


def _e_openfoam_tool(name: str) -> list[str] | None:
    """ESI v2512 first. Distro /usr/bin rhoPimpleFoam is not the C-proven adapter ABI."""
    esi = _ESI_FOAM / name
    if esi.is_file():
        return [str(esi)]
    located = _openfoam_tool(name)
    if located is None:
        return None
    return list(located[0])

# CAD entity for the FSI wall (same string as mesh bindings).
CAD_FACE = "face.inner_wall"
OF_PATCH = "inner_wall"
_AIR_RHO = 1.225


def _config_reference(config_xml: Path, workdir: Path) -> str:
    try:
        return Path(os.path.relpath(config_xml.resolve(), workdir.resolve())).as_posix()
    except (OSError, ValueError):
        return config_xml.as_posix()


def write_e_fluid_fields(case: Path) -> None:
    """0/ and system dicts whose patches match e_mesh_fluid blockMeshDict."""
    case = Path(case)
    patches = f"""
    {OF_PATCH} {{ type zeroGradient; }}
    lid {{ type zeroGradient; }}
    base {{ type zeroGradient; }}
    outer {{ type zeroGradient; }}
"""
    u_patches = f"""
    {OF_PATCH} {{ type movingWallVelocity; value uniform (0 0 0); }}
    lid {{ type noSlip; }}
    base {{ type noSlip; }}
    outer {{ type noSlip; }}
"""
    disp_patches = f"""
    {OF_PATCH} {{ type fixedValue; value uniform (0 0 0); }}
    lid {{ type fixedValue; value uniform (0 0 0); }}
    base {{ type fixedValue; value uniform (0 0 0); }}
    outer {{ type fixedValue; value uniform (0 0 0); }}
"""
    files = {
        "0/p": f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      p;
}}
dimensions      [1 -1 -2 0 0 0 0];
internalField   uniform 101325;
boundaryField
{{{patches}}}
""",
        "0/T": f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      T;
}}
dimensions      [0 0 0 1 0 0 0];
internalField   uniform 350;
boundaryField
{{{patches}}}
""",
        "0/U": f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volVectorField;
    object      U;
}}
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform (0 0 0);
boundaryField
{{{u_patches}}}
""",
        "0/pointDisplacement": f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       pointVectorField;
    object      pointDisplacement;
}}
dimensions      [0 1 0 0 0 0 0];
internalField   uniform (0 0 0);
boundaryField
{{{disp_patches}}}
""",
        "constant/transportProperties": """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      transportProperties;
}
transportModel  Newtonian;
nu              [0 2 -1 0 0 0 0] 1.5e-05;
""",
        "constant/thermophysicalProperties": """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      thermophysicalProperties;
}
thermoType
{
    type            hePsiThermo;
    mixture         pureMixture;
    transport       const;
    thermo          hConst;
    equationOfState perfectGas;
    specie          specie;
    energy          sensibleEnthalpy;
}
mixture
{
    specie { molWeight 28.9; }
    thermodynamics { Cp 1005; Hf 0; }
    transport { mu 1.8e-05; Pr 0.7; }
}
""",
        "system/controlDict": """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}
application     rhoPimpleFoam;
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
    }
    for rel, body in files.items():
        dest = case / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = body
        if rel == "system/controlDict":
            text = _with_adapter_function(body)
        dest.write_text(text, encoding="utf-8")


def write_e_precice_adapter_config(workdir: Path, config_xml: Path) -> None:
    """Force write, Displacement read, patch inner_wall, mesh interface-fluid."""
    workdir = Path(workdir)
    config_ref = _config_reference(config_xml, workdir)
    yml = f"""participant: Fluid

precice-config-file: "{config_ref}"

interfaces:
  - mesh: interface-fluid
    locations: faceCenters
    patches:
      - {OF_PATCH}
    read-data:
      - Displacement
    write-data:
      - Force
"""
    (workdir / "precice-adapter-config.yml").write_text(yml, encoding="utf-8")
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
preciceConfig "{Path(config_ref).as_posix()}";
participant Fluid;
modules (FSI);
interfaces
{{
    Interface1
    {{
        mesh            interface-fluid;
        patches         ({OF_PATCH});
        locations       faceCenters;
        readData        (Displacement);
        writeData       (Force);
    }}
}}
FSI
{{
    rho rho [1 -3 0 0 0 0 0] {_AIR_RHO};
}}
""",
        encoding="utf-8",
    )


def prepare_e_fluid_participant(
    workdir: Path, config_xml: Path, identity: dict[str, Any]
) -> dict[str, Any]:
    """Stage blockMeshDict, fields, and adapter files. Does not run blockMesh."""
    ids = set(identity.get("entity_ids") or [])
    if CAD_FACE not in ids:
        return {"status": "broken", "detail": f"identity missing {CAD_FACE}"}
    workdir = Path(workdir)
    write_fluid_block_mesh_dict(workdir / "system" / "blockMeshDict")
    write_e_fluid_fields(workdir)
    write_e_solver_support(workdir)
    write_e_precice_adapter_config(workdir, config_xml)
    return {
        "status": "ok",
        "detail": str(workdir),
        "patch": OF_PATCH,
        "entity_id": CAD_FACE,
        "mesh_face_id": MESH_FACE,
        "topology_version": int(identity.get("topology_version") or 1),
        "path": str(workdir),
    }


_E_SOLVER_FILES: dict[str, str] = {
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
    "constant/g": """FoamFile
{
    version     2.0;
    format      ascii;
    class       uniformDimensionedVectorField;
    object      g;
}
dimensions      [0 1 -2 0 0 0 0];
value           (0 0 0);
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
    "system/fvSchemes": """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSchemes;
}
ddtSchemes { default Euler; }
gradSchemes { default Gauss linear; }
divSchemes
{
    default         none;
    div(phi,U)      Gauss upwind;
    div(phi,h)      Gauss upwind;
    div(phi,e)      Gauss upwind;
    div(phi,K)      Gauss upwind;
    div(phiv,p)     Gauss upwind;
    div(meshPhi,p)  Gauss linear;
    div(((rho*nuEff)*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes { default corrected; }
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
    p
    {
        solver          PCG;
        preconditioner  DIC;
        tolerance       1e-6;
        relTol          0.1;
    }
    pFinal { $p; relTol 0; }
    pcorr { $p; }
    pcorrFinal { $pcorr; relTol 0; }
    rho { solver diagonal; }
    rhoFinal { $rho; }
    "(U|h|e|k|epsilon|omega|R|cellDisplacement)"
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-5;
        relTol          0.1;
    }
    "(U|h|e|k|epsilon|omega|R|cellDisplacement)Final"
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
    transonic       no;
}
""",
    "0/cellDisplacement": """FoamFile
{
    version     2.0;
    format      ascii;
    class       volVectorField;
    object      cellDisplacement;
}
dimensions      [0 1 0 0 0 0 0];
internalField   uniform (0 0 0);
boundaryField
{
    inner_wall { type fixedValue; value uniform (0 0 0); }
    lid { type fixedValue; value uniform (0 0 0); }
    base { type fixedValue; value uniform (0 0 0); }
    outer { type fixedValue; value uniform (0 0 0); }
}
""",
}


def write_e_solver_support(case: Path) -> None:
    """fvSchemes, motion, g. Does not overwrite 0/p or 0/T."""
    case = Path(case)
    for rel, body in _E_SOLVER_FILES.items():
        dest = case / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding="utf-8")


def _tool_ok(name: str, workdir: Path) -> bool:
    from engineering_tools.hello_probes import _run_openfoam

    command = _e_openfoam_tool(name)
    if command is None:
        return False
    try:
        proc = _run_openfoam(command, workdir)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def mesh_e_fluid_participant(workdir: Path) -> bool:
    """blockMesh only. Facade starts rhoPimpleFoam."""
    write_e_solver_support(workdir)
    return _tool_ok("blockMesh", workdir)


def fluid_e_participant_argv() -> list[str] | None:
    """rhoPimpleFoam under ESI bashrc so libthermoTools.so resolves.

    Agents: raw Popen of the ESI binary fails with missing .so. C pimpleFoam
    did not need thermo libs. Fake PATH binaries still exec without bashrc.
    """
    command = _e_openfoam_tool("rhoPimpleFoam")
    if command is None:
        return None
    bashrc = "/usr/lib/openfoam/openfoam2512/etc/bashrc"
    quoted = " ".join(shlex.quote(p) for p in command)
    if Path(bashrc).is_file():
        script = f"set +u; . {shlex.quote(bashrc)}; exec {quoted}"
        return ["bash", "--noprofile", "--norc", "-c", script]
    return command


def _paren_block_after(text: str, marker: str) -> str | None:
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


def _inner_wall_center_m(workdir: Path) -> list[float] | None:
    candidates = (
        workdir / "system" / "blockMeshDict",
        workdir / "constant" / "polyMesh" / "blockMeshDict",
    )
    text = next((path.read_text(encoding="utf-8") for path in candidates if path.is_file()), None)
    if text is None or "vertices" not in text or "inner_wall" not in text:
        return None
    vert_body = _paren_block_after(text, "vertices")
    if vert_body is None:
        return None
    verts: list[list[float]] = []
    for line in vert_body.splitlines():
        nums = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", line)
        if len(nums) >= 3:
            verts.append([float(nums[0]), float(nums[1]), float(nums[2])])
    iface = text.split("inner_wall", 1)[1]
    face = re.search(r"\(\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*\)", iface)
    if face is None:
        return None
    ids = [int(face.group(i)) for i in range(1, 5)]
    if any(nid >= len(verts) for nid in ids):
        return None
    picked = [verts[nid] for nid in ids]
    return [sum(point[axis] for point in picked) / len(picked) for axis in range(3)]


def _latest_scalar(workdir: Path, name: str) -> Path | None:
    found: list[Path] = []
    for path in workdir.glob(f"*/{name}"):
        if path.parent.name != "0" and path.is_file() and path.stat().st_size > 0:
            found.append(path)
    if not found:
        return None
    return sorted(found)[-1]


def sample_e_fluid_probes(out: Path) -> dict[str, Any]:
    """SI p and T from later-than-0 time dirs. Patch is inner_wall."""
    from engineering_tools.damper_cfd import parse_internal_field_p

    p_path = _latest_scalar(out, "p")
    t_path = _latest_scalar(out, "T")
    center = _inner_wall_center_m(out)
    if p_path is None or t_path is None or center is None:
        return {}
    pressure = parse_internal_field_p(p_path.read_text(encoding="utf-8", errors="replace"))
    temperature = parse_internal_field_p(t_path.read_text(encoding="utf-8", errors="replace"))
    return {
        "face.inner_wall.pressure": {
            "value": pressure,
            "unit": "Pa",
            "entity_id": CAD_FACE,
            "patch": OF_PATCH,
            "xyz_m": list(center),
        },
        "face.inner_wall.temperature": {
            "value": temperature,
            "unit": "K",
            "entity_id": CAD_FACE,
            "patch": OF_PATCH,
            "xyz_m": list(center),
        },
        "face.inner_wall.heat_flux": {
            "value": 0.0,
            "unit": "W/m2",
            "entity_id": CAD_FACE,
            "note": "sampled placeholder; live XML is FSI Force/Displacement",
        },
    }

