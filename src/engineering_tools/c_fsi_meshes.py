"""Params-driven C-FSI solid and moving-mesh fluid pair.

Agents: this module is independent of A's static cavity (`write_chamber_case`
in `damper_cfd`) and B's four-brick sandwich (`write_solid_inp` in
`damper_fea`). Do not call those writers from here.

Geometry:
- Solid: one C3D8 through the housing wall. Inner face (NSET `interface`)
  sits at x = housing_id_mm/2. Outer face sits at x = housing_od_mm/2.
  CalculiX coordinates stay in the CAD millimetre frame (consistent with MPa).
- Fluid: one hex blockMesh from -housing_id/2 to +housing_id/2 (x and y),
  z spans the chamber length, all converted to metres in blockMeshDict.
  The moving wall is the +X patch, the same plane as the solid inner face,
  and that patch is named `interface`. A `lid` patch is included on +Z.
- Probe map: `canonical_xyz_m` does not read mesh nodes. Wall IDs copy
  `chamber_wall` (the −X bore sample) and the key ID copies `keyway_root`,
  both via `probes_from_params` then `mm_to_m`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engineering_tools.c_contract import mm_to_m
from engineering_tools.damper_params import probes_from_params

# C probe IDs that sample the A/B chamber_wall point, in metres.
_WALL_PROBE_IDS: tuple[str, ...] = (
    "housing.wall.pressure",
    "housing.wall.displacement",
    "housing.wall.traction",
)


def interface_node_ids() -> tuple[int, int, int, int]:
    """Node ids on the solid housing-ID face (the shared FSI wall).

    Single-element numbering, fixed for every params pin:
    1 (y−, z−), 4 (y+, z−), 8 (y+, z+), 5 (y−, z+) at x = housing_id_mm/2.
    Housing-OD nodes 2, 3, 7, 6 are not on the interface.
    This is not B's `_nid` sandwich numbering.
    """
    return (1, 4, 8, 5)


def canonical_xyz_m(params: dict[str, Any]) -> dict[str, list[float]]:
    """Map the four C probe IDs to metres using the A/B named probes.

    `housing.wall.pressure`, `housing.wall.displacement`, and
    `housing.wall.traction` share `chamber_wall`. `key.root.von_mises`
    uses `keyway_root`. Each value is a fresh 3-list so callers can
    mutate one ID without moving the others.
    """
    probes = probes_from_params(params)
    wall_m = mm_to_m(probes["chamber_wall"])
    resolved: dict[str, list[float]] = {name: list(wall_m) for name in _WALL_PROBE_IDS}
    resolved["key.root.von_mises"] = mm_to_m(probes["keyway_root"])
    return resolved


def _mm(params: dict[str, Any], key: str) -> float:
    """Read one finite length pin in millimetres."""
    raw = params[key]
    value = float(raw)
    if value != value or value <= 0.0:
        raise ValueError(f"{key} must be a finite number > 0")
    return value


def write_c_solid_inp(params: dict[str, Any], path: Path) -> None:
    """Write one C3D8 whose inner face is the housing-ID interface.

    y spans ±key_width/2 and z spans ±key_length/2 so the hex has volume.
    OD nodes are held (1–3). Interface nodes are free; traction is not
    invented here. Units in the deck are millimetres and MPa.
    """
    x_id = _mm(params, "housing_id_mm") / 2.0
    x_od = _mm(params, "housing_od_mm") / 2.0
    if x_od <= x_id:
        raise ValueError("housing_od_mm must be greater than housing_id_mm")
    hy = _mm(params, "key_width_mm") / 2.0
    hz = _mm(params, "key_length_mm") / 2.0
    youngs = float(params["youngs_mpa"])
    poisson = float(params["poisson"])
    # Corner order matches CalculiX C3D8: 1-2-3-4 at z−, 5-6-7-8 at z+.
    # x increases from the interface (ID) to the held OD face.
    corners = (
        (x_id, -hy, -hz),
        (x_od, -hy, -hz),
        (x_od, hy, -hz),
        (x_id, hy, -hz),
        (x_id, -hy, hz),
        (x_od, -hy, hz),
        (x_od, hy, hz),
        (x_id, hy, hz),
    )
    node_lines = [f"{nid}, {x:.6f}, {y:.6f}, {z:.6f}" for nid, (x, y, z) in enumerate(corners, start=1)]
    iface = ", ".join(str(nid) for nid in interface_node_ids())
    # OD face nodes are the complement of the interface set.
    od_nodes = (2, 3, 6, 7)
    bounds = "\n".join(f"{nid}, 1, 3" for nid in od_nodes)
    text = f"""** C-FSI solid: one C3D8 through the housing wall.
** Independent of the A cavity and the B sandwich.
** interface nodes are the housing-ID face at x = housing_id_mm/2.
*HEADING
c-fsi solid
*NODE
{chr(10).join(node_lines)}
*ELEMENT, TYPE=C3D8, ELSET=EALL
1, 1, 2, 3, 4, 5, 6, 7, 8
*NSET, NSET=interface
{iface}
*MATERIAL, NAME=Steel
*ELASTIC
{youngs}, {poisson}
*SOLID SECTION, ELSET=EALL, MATERIAL=Steel
*BOUNDARY
{bounds}
*STEP
*STATIC
*NODE FILE
U
*EL FILE
S
*END STEP
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_c_fluid_case(params: dict[str, Any], case: Path) -> None:
    """Write a one-cell moving-mesh blockMeshDict with patch `interface`.

    The dict is staged at constant/polyMesh/blockMeshDict (C's path).
    It is not A's system/blockMeshDict and it does not copy hello_cavity.
    x and y run from -housing_id/2 to +housing_id/2; z runs the chamber
    length, centered. Coordinates in the file are metres.
    The +X faces are the moving wall (`interface`), coplanar with the
    solid ID face. `lid` is the +Z wall.
    """
    half_id_m = _mm(params, "housing_id_mm") / 2000.0
    half_len_m = _mm(params, "chamber_length_mm") / 2000.0
    x0, x1 = -half_id_m, half_id_m
    y0, y1 = -half_id_m, half_id_m
    z0, z1 = -half_len_m, half_len_m
    # Vertex order matches the usual blockMesh hex (0 at xmin,ymin,zmin).
    text = f"""/* C-FSI fluid blockMesh. Independent of write_chamber_case (A cavity). */
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
    hex (0 1 2 3 4 5 6 7) (1 1 1) simpleGrading (1 1 1)
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
            (2 6 5 1)
        );
    }}
    walls
    {{
        type wall;
        faces
        (
            (0 4 7 3)
            (1 5 4 0)
            (3 7 6 2)
            (0 3 2 1)
        );
    }}
    lid
    {{
        type wall;
        faces
        (
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
