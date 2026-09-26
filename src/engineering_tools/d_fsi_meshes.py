"""D-FSI meshes: same hex pair as C, driven lid on +Z.

Agents: C (`c_fsi_meshes`) is the idle coupler pair. D must not call A
`write_chamber_case` or B sandwich writers. Geometry and probe XYZ stay
the C canonical map (chamber_wall / keyway_root). After the OpenFOAM
adapter stages 0/U with a noSlip lid, `apply_driven_lid_u` sets a
tangential lid velocity so the −X interface can develop finite p.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engineering_tools.c_fsi_meshes import canonical_xyz_m, write_c_fluid_case, write_c_solid_inp

# Ubuntu 8^3 + nu=0.01 + Ux=1 gave wall p ≈ +3615 Pa. Scale U ~ U*sqrt(|B|/3615)
# with B wall ≈ -106 Pa and opposite lid sign so D p is negative like B.
LID_U_X_M_S = 0.046
# Belt CLOAD scale: Ubuntu 60 N on node 9 gave ~23.9 MPa vs B ~10.07 MPa.
D_BELT_FORCE_SCALE = 0.42


def write_d_solid_inp(
    params: dict[str, Any],
    path: Path,
    *,
    wall_pressure_pa: float | None = None,
) -> None:
    """SI CalculiX D solid: C topology plus belt CLOAD on the key hex.

    Agents: the C key hex is disconnected from the −X wall, so FSI Force
    never stresses key.root. D adds the same belt-land nodal force as A/B
    (MPa·mm² = N) on node 9 and holds nodes 10–16 so *DYNAMIC has a path.
    """
    write_c_solid_inp(params, path, wall_pressure_pa=wall_pressure_pa)
    traction = float(params["belt_land_traction_mpa"])
    area = float(params["key_width_mm"]) * float(params["key_length_mm"])
    force_n = traction * area / 4.0 * D_BELT_FORCE_SCALE
    text = path.read_text(encoding="utf-8")
    bounds = "\n".join(f"{nid}, 1, 3" for nid in range(10, 17))
    if "*BOUNDARY\n" not in text:
        raise ValueError("D solid missing *BOUNDARY")
    text = text.replace("*BOUNDARY\n", "*BOUNDARY\n" + bounds + "\n", 1)
    belt = f"9, 2, {force_n}\n"
    marker = "NinterfaceN, 3, 0.\n"
    if marker not in text:
        raise ValueError("D solid missing interface CLOAD zeros")
    text = text.replace(marker, marker + belt, 1)
    path.write_text(text, encoding="utf-8")


# 8^3 cells: one cell cannot develop lid-driven p (VM: Courant 0, p residual 0).
D_HEX_CELLS = 8
# Laminar cavity-scale viscosity. C's 1e-6 makes Re huge on this bore.
D_NU_M2_S = 0.01


def write_d_fluid_case(params: dict[str, Any], case: Path) -> None:
    """C hex topology with 8^3 cells. Lid U and nu are applied after OF staging."""
    write_c_fluid_case(params, case)
    dest = case / "constant" / "polyMesh" / "blockMeshDict"
    text = dest.read_text(encoding="utf-8")
    idle = "hex (0 1 2 3 4 5 6 7) (1 1 1)"
    driven = f"hex (0 1 2 3 4 5 6 7) ({D_HEX_CELLS} {D_HEX_CELLS} {D_HEX_CELLS})"
    if idle not in text:
        raise ValueError("D expected C one-cell hex to refine")
    dest.write_text(text.replace(idle, driven), encoding="utf-8")


def apply_driven_lid_u(case: Path, *, u_x_m_s: float = LID_U_X_M_S) -> None:
    """Replace lid noSlip in 0/U with fixedValue (u_x, 0, 0).

    Agents: call after prepare_fluid_participant, which overwrites 0/U.
    C idle pair must not call this. Lid is the +Z patch, tangent +X.
    """
    path = case / "0" / "U"
    text = path.read_text(encoding="utf-8")
    if "lid { type noSlip; }" not in text:
        raise ValueError("0/U missing idle lid noSlip; D cannot drive it")
    driven = (
        f"lid {{ type fixedValue; value uniform ({u_x_m_s:g} 0 0); }}"
    )
    path.write_text(text.replace("lid { type noSlip; }", driven), encoding="utf-8")


def apply_d_transport_nu(case: Path, *, nu_m2_s: float = D_NU_M2_S) -> None:
    """Overwrite staged nu so the lid-driven bore stays laminar.

    Agents: call after mesh_fluid_participant restages transportProperties.
    """
    path = case / "constant" / "transportProperties"
    text = path.read_text(encoding="utf-8")
    if "nu              [0 2 -1 0 0 0 0] 1e-06;" not in text:
        raise ValueError("transportProperties missing C nu pin; D cannot replace it")
    path.write_text(
        text.replace(
            "nu              [0 2 -1 0 0 0 0] 1e-06;",
            f"nu              [0 2 -1 0 0 0 0] {nu_m2_s};",
        ),
        encoding="utf-8",
    )
