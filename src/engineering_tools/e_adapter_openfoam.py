"""Phase E OpenFOAM deck: gas cylinder, patch face.inner_wall.

Agents: mesh is Gmsh + gmshToFoam. Patch name matches Physical Surface
face.inner_wall (same CAD face as the solid). Adapter writes Force and
Heat-Flux, reads Displacement and Temperature. rhoPimpleFoam: no CHT rho/Cp
block. Does not launch solvers.
"""

from __future__ import annotations

import math
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from engineering_tools.e_mesh_fluid import INNER_WALL as MESH_FACE
from engineering_tools.e_policy import OPENFOAM_ADAPTER_DATA
from engineering_tools.hello_probes import _openfoam_tool

_ESI_FOAM = Path("/usr/lib/openfoam/openfoam2512/platforms/linux64GccDPInt32Opt/bin")


def _e_openfoam_tool(name: str) -> list[str] | None:
    """ESI v2512 first unless ETOOLS_E_MOCK_SOLVERS=1 (pytest PATH fakes)."""
    if os.environ.get("ETOOLS_E_MOCK_SOLVERS") == "1":
        located = _openfoam_tool(name)
        if located is not None:
            return list(located[0])
        return None
    esi = _ESI_FOAM / name
    if esi.is_file():
        return [str(esi)]
    located = _openfoam_tool(name)
    if located is None:
        return None
    return list(located[0])

# CAD entity for the FSI wall (same string as mesh bindings).
CAD_FACE = "face.inner_wall"
OF_PATCH = "face.inner_wall"
_AIR_RHO = 1.225
# Name OpenFOAM prints when the function object cannot open this file.
# The couple install builds this into the ESI site lib. A case that names it
# and a machine that lacks it is the early-exit seen on the guest.
ADAPTER_LIBRARY = "libpreciceAdapterFunctionObject.so"
# OpenFOAM 2512 functionObjectList reads this word in the functions dictionary.
# The default handler warns and continues, so rhoPimpleFoam reaches End without
# joining preCICE. `strict` calls exitNow on that load failure.
_E_ADAPTER_FUNCTION = """
functions
{
    errors          strict;
    preciceAdapter
    {
        type            preciceAdapterFunctionObject;
        libs            ("libpreciceAdapterFunctionObject.so");
    }
}
"""


def _config_reference(config_xml: Path, workdir: Path) -> str:
    try:
        return Path(os.path.relpath(config_xml.resolve(), workdir.resolve())).as_posix()
    except (OSError, ValueError):
        return config_xml.as_posix()


def write_e_fluid_fields(case: Path, *, t_end_s: float = 0.02, dt_s: float = 0.01, p_pa: float = 1.01e5) -> None:
    """0/ and system dicts whose patches match Physical Surface names."""
    case = Path(case)
    pressure = float(p_pa)
    p_patches = f"""
    {OF_PATCH} {{ type zeroGradient; }}
    lid {{ type zeroGradient; }}
    base {{ type zeroGradient; }}
"""
    t_patches = f"""
    {OF_PATCH} {{ type fixedValue; value uniform 300; }}
    lid {{ type zeroGradient; }}
    base {{ type zeroGradient; }}
"""
    u_patches = f"""
    {OF_PATCH} {{ type movingWallVelocity; value uniform (0 0 0); }}
    lid {{ type noSlip; }}
    base {{ type noSlip; }}
"""
    disp_patches = f"""
    {OF_PATCH} {{ type fixedValue; value uniform (0 0 0); }}
    lid {{ type fixedValue; value uniform (0 0 0); }}
    base {{ type fixedValue; value uniform (0 0 0); }}
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
internalField   uniform {pressure};
boundaryField
{{{p_patches}}}
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
{{{t_patches}}}
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
        "system/controlDict": f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}}
application     rhoPimpleFoam;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         {float(t_end_s)};
deltaT          {float(dt_s)};
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
            text = _with_e_adapter_function(body)
        dest.write_text(text, encoding="utf-8")


def _with_e_adapter_function(control: str) -> str:
    """Append the adapter function object with the strict OpenFOAM handler.

    Agents: the C damper controlDict keeps the default handler. This E deck
    must not. A missing libpreciceAdapterFunctionObject.so has to stop
    rhoPimpleFoam before the time loop, not after a short uncoupled End.
    """
    if "errors          strict;" in control and ADAPTER_LIBRARY in control:
        return control
    return control.rstrip() + "\n" + _E_ADAPTER_FUNCTION


def fluid_adapter_load_detail(log_text: str) -> str | None:
    """Return the session detail when the fluid log shows the adapter did not load.

    Agents: that line is the cause. A later End and a zero window count are
    the consequence. Callers must prefer this detail over the mechanical
    verify string, which only restates the missing windows.
    """
    if f'Could not load "{ADAPTER_LIBRARY}"' in log_text:
        return (
            "OpenFOAM could not load libpreciceAdapterFunctionObject.so; "
            "the fluid solver left the couple"
        )
    return None


def _participant_data_names(xml: str, participant: str, tag: str) -> list[str]:
    """Names of one read-data or write-data tag inside one participant block.

    Agents: the adapter must ask only for data this XML puts on that
    participant. A hardcoded Displacement read makes one-way configure abort,
    because Solid does not provide Displacement.
    """
    start = xml.find(f'<participant name="{participant}">')
    if start < 0:
        return []
    end = xml.find("</participant>", start)
    block = xml[start:end]
    names: list[str] = []
    for name in re.findall(rf'{tag} name="([^"]+)"', block):
        if name in names or name not in OPENFOAM_ADAPTER_DATA:
            continue
        names.append(name)
    return names


def write_e_precice_adapter_config(workdir: Path, config_xml: Path) -> None:
    """Fluid adapter files whose read and write lists match the XML.

    Agents: one-way writes Force, Heat-Flux, and Temperature and reads
    nothing. Two-way still reads Displacement and Temperature when the XML
    says Fluid reads them. An empty read list is omitted. Adapter v1.4.0
    treats a skipped readData entry as uni-directional coupling.
    """
    workdir = Path(workdir)
    config_ref = _config_reference(config_xml, workdir)
    xml_text = Path(config_xml).read_text(encoding="utf-8") if Path(config_xml).is_file() else ""
    reads = _participant_data_names(xml_text, "Fluid", "read-data")
    writes = _participant_data_names(xml_text, "Fluid", "write-data")
    read_yml = "".join(f"      - {name}\n" for name in reads)
    write_yml = "".join(f"      - {name}\n" for name in writes)
    read_block = f"    read-data:\n{read_yml}" if reads else ""
    write_block = f"    write-data:\n{write_yml}" if writes else ""
    yml = (
        "participant: Fluid\n\n"
        f'precice-config-file: "{config_ref}"\n\n'
        "interfaces:\n"
        "  - mesh: interface-fluid\n"
        "    locations: faceCenters\n"
        "    patches:\n"
        f"      - {OF_PATCH}\n"
        f"{read_block}"
        f"{write_block}"
    )
    (workdir / "precice-adapter-config.yml").write_text(yml, encoding="utf-8")
    read_line = f"        readData        ({' '.join(reads)});\n" if reads else ""
    write_line = f"        writeData       ({' '.join(writes)});\n" if writes else ""
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
modules (FSI CHT);
interfaces
{{
    Interface1
    {{
        mesh            interface-fluid;
        patches         ({OF_PATCH});
        locations       faceCenters;
{read_line}{write_line}    }}
}}
FSI
{{
    rho rho [1 -3 0 0 0 0 0] {_AIR_RHO};
}}
""",
        encoding="utf-8",
    )


def prepare_e_fluid_participant(
    workdir: Path,
    config_xml: Path,
    identity: dict[str, Any],
    *,
    msh: Path | None = None,
    t_end_s: float = 0.02,
    dt_s: float = 0.01,
    p_pa: float = 1.01e5,
) -> dict[str, Any]:
    """Stage fluid.msh, fields, and adapter files. Does not run gmshToFoam."""
    ids = set(identity.get("entity_ids") or [])
    if CAD_FACE not in ids:
        return {"status": "broken", "detail": f"identity missing {CAD_FACE}"}
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    if msh is not None:
        src = Path(msh)
        if not src.is_file():
            return {"status": "broken", "detail": f"missing fluid msh {src}"}
        dest = workdir / "fluid.msh"
        dest.write_text(src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    write_e_fluid_fields(workdir, t_end_s=t_end_s, dt_s=dt_s, p_pa=p_pa)
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
    face.inner_wall { type fixedValue; value uniform (0 0 0); }
    lid { type fixedValue; value uniform (0 0 0); }
    base { type fixedValue; value uniform (0 0 0); }
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
    """gmshToFoam on fluid.msh. Facade starts rhoPimpleFoam."""
    from engineering_tools.hello_probes import _run_openfoam

    workdir = Path(workdir)
    msh = workdir / "fluid.msh"
    if not msh.is_file():
        return False
    write_e_solver_support(workdir)
    command = _e_openfoam_tool("gmshToFoam")
    if command is None:
        return False
    try:
        proc = _run_openfoam(list(command) + [str(msh)], workdir)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def fluid_e_participant_argv() -> list[str] | None:
    """rhoPimpleFoam under ESI bashrc so libthermoTools.so resolves.

    Agents: raw Popen of the ESI binary fails with missing .so. C pimpleFoam
    did not need thermo libs. Fake PATH binaries still exec without bashrc.
    """
    command = _e_openfoam_tool("rhoPimpleFoam")
    if command is None:
        return None
    if os.environ.get("ETOOLS_E_MOCK_SOLVERS") == "1":
        return command
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


def _foam_list_body(text: str) -> str:
    """Inner text of the first count+(...) polyMesh list."""
    match = re.search(r"(?m)^(\d+)\s*\n\(", text)
    if match is None:
        return ""
    start = match.end() - 1
    depth = 0
    for index, char in enumerate(text[start:], start=start):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index]
    return ""


def _parse_points(text: str) -> list[list[float]]:
    body = _foam_list_body(text)
    points: list[list[float]] = []
    for match in re.finditer(r"\(([^)]+)\)", body):
        nums = [float(tok) for tok in match.group(1).split()]
        if len(nums) >= 3:
            points.append(nums[:3])
    return points


def _parse_faces(text: str) -> list[list[int]]:
    body = _foam_list_body(text)
    faces: list[list[int]] = []
    for match in re.finditer(r"(\d+)\s*\(([^)]*)\)", body):
        faces.append([int(tok) for tok in match.group(2).split()])
    return faces


def _parse_owner(text: str) -> list[int]:
    body = _foam_list_body(text)
    return [int(tok) for tok in body.split() if tok.lstrip("-").isdigit()]


def _patch_face_range(boundary_text: str, name: str) -> tuple[int, int] | None:
    match = re.search(rf"\b{re.escape(name)}\s*\{{", boundary_text)
    if match is None:
        return None
    body = boundary_text[match.end() :]
    end = body.find("}")
    if end < 0:
        return None
    block = body[:end]
    n_faces = re.search(r"nFaces\s+(\d+)", block)
    start_face = re.search(r"startFace\s+(\d+)", block)
    if n_faces is None or start_face is None:
        return None
    return int(start_face.group(1)), int(n_faces.group(1))


def _cell_pressures(p_text: str, n_cells: int) -> list[float] | None:
    """Owner-cell p from latest volScalarField. Does not read T."""
    if n_cells <= 0:
        return None
    if re.search(r"internalField\s+nonuniform\s+List<scalar>", p_text):
        body = _foam_list_body(p_text[p_text.find("internalField") :])
        values = [float(tok) for tok in body.split() if tok not in {"(", ")"}]
        if len(values) < n_cells:
            return None
        return values[:n_cells]
    uniform = re.search(r"internalField\s+uniform\s+([-+0-9.eE]+)", p_text)
    if uniform is None:
        return None
    return [float(uniform.group(1))] * n_cells


def _face_area(points: list[list[float]], ids: list[int]) -> list[float]:
    if len(ids) < 3 or any(nid >= len(points) for nid in ids):
        return [0.0, 0.0, 0.0]
    origin = points[ids[0]]
    acc = [0.0, 0.0, 0.0]
    for index in range(1, len(ids) - 1):
        a = [points[ids[index]][axis] - origin[axis] for axis in range(3)]
        b = [points[ids[index + 1]][axis] - origin[axis] for axis in range(3)]
        acc[0] += a[1] * b[2] - a[2] * b[1]
        acc[1] += a[2] * b[0] - a[0] * b[2]
        acc[2] += a[0] * b[1] - a[1] * b[0]
    return [0.5 * component for component in acc]


def integrate_inner_wall_pressure_force(workdir: Path) -> dict[str, Any] | None:
    """Absolute p*Sf on complete face.inner_wall. Net and L1; SI newtons.

    Agents: OpenFOAM Sf is outward from the fluid. p*Sf is the pressure load
    on that patch (same applied-load family as CalculiX interface FORC/CLOAD).
    Net vector nearly cancels on the cylinder; L1 of ||p*Sf|| is the mapping
    size compared to sum ||FORC||. Gauge p-p_ref is not used: live p is ~p_ref
    so gauge L1 is identically 0 and is not the coupled Force.
    """
    mesh = Path(workdir) / "constant" / "polyMesh"
    p_path = _latest_scalar(Path(workdir), "p")
    needed = [mesh / "points", mesh / "faces", mesh / "owner", mesh / "boundary"]
    if p_path is None or any(not path.is_file() for path in needed):
        return None
    points = _parse_points(needed[0].read_text(encoding="utf-8", errors="replace"))
    faces = _parse_faces(needed[1].read_text(encoding="utf-8", errors="replace"))
    owner = _parse_owner(needed[2].read_text(encoding="utf-8", errors="replace"))
    span = _patch_face_range(needed[3].read_text(encoding="utf-8", errors="replace"), OF_PATCH)
    if span is None or not points or not faces or not owner:
        return None
    start, n_faces = span
    end = start + n_faces
    if n_faces <= 0 or end > len(faces) or end > len(owner):
        return None
    n_cells = max(owner) + 1 if owner else 0
    pressures = _cell_pressures(p_path.read_text(encoding="utf-8", errors="replace"), n_cells)
    if pressures is None:
        return None
    fx = fy = fz = 0.0
    l1 = 0.0
    for face_id in range(start, end):
        cell = owner[face_id]
        if cell < 0 or cell >= len(pressures):
            return None
        area = _face_area(points, faces[face_id])
        px, py, pz = pressures[cell] * area[0], pressures[cell] * area[1], pressures[cell] * area[2]
        fx += px
        fy += py
        fz += pz
        l1 += math.sqrt(px * px + py * py + pz * pz)
    return {
        "value": l1,
        "unit": "N",
        "entity_id": CAD_FACE,
        "kind": "integrated_traction_magnitude",
        "l1_N": l1,
        "net_components_N": [fx, fy, fz],
        "net_magnitude_N": math.sqrt(fx * fx + fy * fy + fz * fz),
        "components_N": [fx, fy, fz],
        "n_faces": n_faces,
        "endpoint": "reconstructed_p_Sf_pressure_only",
        "limitation": "pressure-only p*Sf reconstruction; not proven adapter Force write",
    }

def sample_e_fluid_probes(out: Path) -> dict[str, Any]:
    """Interface location count from tagged msh plus wall pressure force. Not T."""
    from engineering_tools.e_msh2 import interface_triangle_count

    workdir = Path(out)
    msh = workdir / "fluid.msh"
    probes: dict[str, Any] = {}
    if msh.is_file():
        text = msh.read_text(encoding="utf-8", errors="replace")
        n_loc = interface_triangle_count(text, CAD_FACE)
        if n_loc > 0:
            probes["face.inner_wall.interface_locations"] = {
                "value": float(n_loc),
                "unit": "1",
                "entity_id": CAD_FACE,
                "patch": OF_PATCH,
                "locations": "faceCenters",
            }
    force = integrate_inner_wall_pressure_force(workdir)
    if force is not None:
        probes["face.inner_wall.fluid_integrated_force"] = force
    return probes

