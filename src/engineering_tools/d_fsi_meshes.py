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

# Tangential lid speed (m/s) on +Z, +X direction. Q1: smallest cavity-scale
# U that can drive interface p without adding cells. Recorded for agents.
LID_U_X_M_S = 1.0


def write_d_solid_inp(
    params: dict[str, Any],
    path: Path,
    *,
    wall_pressure_pa: float | None = None,
) -> None:
    """SI CalculiX D solid. Same topology as C; independent workdir."""
    write_c_solid_inp(params, path, wall_pressure_pa=wall_pressure_pa)


def write_d_fluid_case(params: dict[str, Any], case: Path) -> None:
    """One-hex D fluid with `interface` and `lid`. Lid U is applied later."""
    write_c_fluid_case(params, case)


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
