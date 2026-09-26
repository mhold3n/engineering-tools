"""D-FSI meshes: A-like chamber Fluid plus B sandwich Solid, tight FSI.

Agents: C is the idle one-cell coupler pair. D is the damper proof.
Fluid matches A hello_cavity numerics (20×20×1, lid U=(1,0,0), nu=0.01,
0.1 s) with the +X face as preCICE `interface` (housing ID, where B maps
wall Pa). Solid is the B four-brick sandwich in SI with NinterfaceN on
the ID plane, belt CLOAD unscaled, no B DLOAD. Do not call A
`write_chamber_case` or B `write_solid_inp` (those stay mm/MPa / icoFoam).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engineering_tools.c_contract import mm_to_m
from engineering_tools.damper_params import probes_from_params

D_NX = 20
D_NY = 20
D_NZ = 1
LID_U_X_M_S = 1.0
D_NU_M2_S = 0.01
D_END_TIME_S = 0.1
D_DELTA_T_S = 0.005


def d_canonical_xyz_m(params: dict[str, Any]) -> dict[str, list[float]]:
    """D wall probe is chamber_wall (−X FSI face). Key is keyway_root."""
    probes = probes_from_params(params)
    wall = mm_to_m(probes["chamber_wall"])
    key = mm_to_m(probes["keyway_root"])
    return {
        "housing.wall.pressure": list(wall),
        "housing.wall.displacement": list(wall),
        "housing.wall.traction": list(wall),
        "key.root.von_mises": list(key),
    }


def _nid(ix: int, iy: int, iz: int) -> int:
    """Same numbering as damper_fea: x-plane, then y, then z."""
    return ix * 4 + iy * 2 + iz + 1


def write_d_solid_inp(
    params: dict[str, Any],
    path: Path,
    *,
    wall_pressure_pa: float | None = None,
) -> None:
    """B sandwich in metres/Pa/kg/m³ with FSI CLOAD slots on the ID plane.

    Agents: wall_pressure_pa is ignored. D wall load is preCICE Force, not
    a B DLOAD. Belt nodal force is traction_MPa × area_mm² / 4 (= N).
    """
    del wall_pressure_pa
    shaft_r = float(params["shaft_od_mm"]) / 2.0
    id_r = float(params["housing_id_mm"]) / 2.0
    od_r = float(params["housing_od_mm"]) / 2.0
    depth = float(params["keyway_depth_mm"])
    hy = float(params["key_width_mm"]) / 2.0
    hz = float(params["key_length_mm"]) / 2.0
    xs = [-od_r, -id_r, 0.0, shaft_r, id_r, id_r + depth, od_r]
    ys = [-hy, hy]
    zs = [-hz, hz]
    youngs_pa = float(params["youngs_mpa"]) * 1.0e6
    poisson = float(params["poisson"])
    traction = float(params["belt_land_traction_mpa"])
    area = float(params["key_width_mm"]) * float(params["key_length_mm"])
    force_n = traction * area / 4.0
    node_lines = []
    for ix, x in enumerate(xs):
        for iy, y in enumerate(ys):
            for iz, z in enumerate(zs):
                nid = _nid(ix, iy, iz)
                node_lines.append(
                    f"{nid}, {x / 1000.0:.8f}, {y / 1000.0:.8f}, {z / 1000.0:.8f}"
                )
    elem_lines = []
    for ix in range(len(xs) - 1):
        n000 = _nid(ix, 0, 0)
        n100 = _nid(ix + 1, 0, 0)
        n110 = _nid(ix + 1, 1, 0)
        n010 = _nid(ix, 1, 0)
        n001 = _nid(ix, 0, 1)
        n101 = _nid(ix + 1, 0, 1)
        n111 = _nid(ix + 1, 1, 1)
        n011 = _nid(ix, 1, 1)
        elem_lines.append(
            f"{ix + 1}, {n000}, {n100}, {n110}, {n010}, {n001}, {n101}, {n111}, {n011}"
        )
    id_ix = 1
    od_ix = len(xs) - 1
    axis_ix = 2
    iface = [_nid(id_ix, iy, iz) for iy in range(2) for iz in range(2)]
    od_nodes = [_nid(od_ix, iy, iz) for iy in range(2) for iz in range(2)]
    axis = [_nid(axis_ix, iy, iz) for iy in range(2) for iz in range(2)]
    iface_set = ", ".join(str(n) for n in iface)
    cload_zero = "\n".join(f"{n}, {dof}, 0." for n in iface for dof in (1, 2, 3))
    belt = "\n".join(f"{n}, 2, {force_n}" for n in od_nodes)
    bounds = "\n".join(f"{n}, 1, 3" for n in axis)
    text = f"""** D-FSI solid: B sandwich in SI. FSI on housing ID (NinterfaceN).
** Belt CLOAD is A/B Newtons. No B wall DLOAD; Force comes from preCICE.
*HEADING
d-fsi sandwich
*NODE
{chr(10).join(node_lines)}
*ELEMENT, TYPE=C3D8, ELSET=EALL
{chr(10).join(elem_lines)}
*NSET, NSET=NinterfaceN
{iface_set}
*MATERIAL, NAME=Steel
*ELASTIC
{youngs_pa}, {poisson}
*DENSITY
7850
*SOLID SECTION, ELSET=EALL, MATERIAL=Steel
*BOUNDARY
{bounds}
*STEP, INC=1000000
*DYNAMIC, ALPHA=0.0, DIRECT
{D_DELTA_T_S}, {D_END_TIME_S}
*CLOAD
{cload_zero}
{belt}
*NODE FILE
U, RF
*EL FILE
S
*END STEP
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_d_fluid_case(params: dict[str, Any], case: Path) -> None:
    """A-sized chamber, +X `interface`, +Y lid, empty frontAndBack."""
    half_id_m = float(params["housing_id_mm"]) / 2000.0
    half_len_m = float(params["chamber_length_mm"]) / 2000.0
    x0, x1 = -half_id_m, half_id_m
    y0, y1 = -half_id_m, half_id_m
    z0, z1 = -half_len_m, half_len_m
    text = f"""/* D-FSI fluid: A chamber size, FSI on +X housing-ID plane. */
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
    ({x0} {y0} {z0})
    ({x1} {y0} {z0})
    ({x1} {y1} {z0})
    ({x0} {y1} {z0})
    ({x0} {y0} {z1})
    ({x1} {y0} {z1})
    ({x1} {y1} {z1})
    ({x0} {y1} {z1})
);

blocks
(
    hex (0 1 2 3 4 5 6 7) ({D_NX} {D_NY} {D_NZ}) simpleGrading (1 1 1)
);

edges
(
);

boundary
(
    interface
    {{
        type wall;
        faces
        (
            (0 4 7 3)
        );
    }}
    lid
    {{
        type wall;
        faces
        (
            (3 7 6 2)
        );
    }}
    walls
    {{
        type wall;
        faces
        (
            (1 5 6 2)
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
    dest = case / "constant" / "polyMesh" / "blockMeshDict"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")


def apply_d_chamber_fields(case: Path) -> None:
    """After OF staging: A lid/nu/time plus empty frontAndBack on every field.

    Agents: prepare_fluid_participant writes C's 3-patch 0/ files. D's mesh
    has frontAndBack. This rewrite must run after mesh_fluid_participant.
    """
    u = f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volVectorField;
    object      U;
}}
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform (0 0 0);
boundaryField
{{
    interface {{ type movingWallVelocity; value uniform (0 0 0); }}
    walls {{ type noSlip; }}
    lid {{ type fixedValue; value uniform ({LID_U_X_M_S:g} 0 0); }}
    frontAndBack {{ type empty; }}
}}
"""
    p = """FoamFile
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
    frontAndBack { type empty; }
}
"""
    pd = """FoamFile
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
    frontAndBack { type empty; }
}
"""
    (case / "0" / "U").write_text(u, encoding="utf-8")
    (case / "0" / "p").write_text(p, encoding="utf-8")
    (case / "0" / "pointDisplacement").write_text(pd, encoding="utf-8")
    cell = case / "0" / "cellDisplacement"
    if cell.is_file():
        text = cell.read_text(encoding="utf-8")
        if "frontAndBack" not in text:
            text = text.replace(
                "lid { type fixedValue; value uniform (0 0 0); }\n}",
                "lid { type fixedValue; value uniform (0 0 0); }\n"
                "    frontAndBack { type empty; }\n}",
            )
            cell.write_text(text, encoding="utf-8")
    nu_path = case / "constant" / "transportProperties"
    nu_text = nu_path.read_text(encoding="utf-8")
    nu_path.write_text(
        nu_text.replace(
            "nu              [0 2 -1 0 0 0 0] 1e-06;",
            f"nu              [0 2 -1 0 0 0 0] {D_NU_M2_S};",
        ),
        encoding="utf-8",
    )
    ctrl = case / "system" / "controlDict"
    ctext = ctrl.read_text(encoding="utf-8")
    ctext = ctext.replace("endTime         0.02;", f"endTime         {D_END_TIME_S};")
    ctext = ctext.replace("deltaT          0.01;", f"deltaT          {D_DELTA_T_S};")
    ctrl.write_text(ctext, encoding="utf-8")
