"""Params-driven C-FSI solid and moving-mesh fluid pair.

Agents: this module is independent of A's static cavity (`write_chamber_case`
in `damper_cfd`) and B's four-brick sandwich (`write_solid_inp` in
`damper_fea`). Do not call those writers from here.

Geometry:
- Solid: two C3D8 elements. Element 1 is the housing wall on the
  chamber_wall side (−X). Inner face (NSET `interface`) sits at
  x = -housing_id_mm/2. Outer face sits at x = -housing_od_mm/2.
  Element 2 is a small hex on +X whose first node sits 1 mm +Y from
  `keyway_root`, inside `geometric_tolerance_m` (0.002 m) and not on the
  canonical pin. CalculiX coordinates stay in the CAD millimetre frame
  (consistent with MPa). Element 1 connectivity is swapped versus node-id
  order so x still increases along the first edge (positive Jacobian):
  global nodes 1,4,8,5 remain the interface. Element 2 uses standard
  node order because its first edge already points +X.
- Fluid: one hex blockMesh from -housing_id/2 to +housing_id/2 (x and y),
  z spans the chamber length, all converted to metres in blockMeshDict.
  The moving wall is the −X patch, the same plane as chamber_wall and the
  solid inner face, and that patch is named `interface`. A `lid` patch is
  included on +Z. The +X housing-ID plane is only a fixed wall.
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
    """Node ids on the solid chamber_wall face (the shared FSI wall).

    Single-element numbering, fixed for every params pin:
    1 (y−, z−), 4 (y+, z−), 8 (y+, z+), 5 (y−, z+) at x = -housing_id_mm/2.
    Housing-OD nodes 2, 3, 7, 6 sit further −X and are not on the interface.
    This is not B's `_nid` sandwich numbering.
    """
    return (1, 4, 8, 5)


def interface_patch_center_m(params: dict[str, Any]) -> list[float]:
    """Centre of the −X `interface` patch, metres, equal to chamber_wall.

    Agents: do not use the hex cell centre (the origin). That point is a
    bore radius away from the named wall and fails geometric_tolerance_m.
    """
    half_id_m = float(params["housing_id_mm"]) / 2000.0
    return [-half_id_m, 0.0, 0.0]


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


def _keyway_sample_node_mm(params: dict[str, Any]) -> tuple[float, float, float]:
    """Return the solid node that sample_c_probes must pick for the key root.

    Agents: this is keyway_root shifted 1 mm in +Y. That offset is inside
    geometric_tolerance_m and is not the canonical pin, so a sampler that
    copies canonical_xyz_m fails a mesh-node comparison. Other corners of
    the key hex are 4 mm away and fall outside the 2 mm tolerance.
    """
    root = probes_from_params(params)["keyway_root"]
    return (float(root[0]), float(root[1]) + 1.0, float(root[2]))


def write_c_solid_inp(params: dict[str, Any], path: Path, *, wall_pressure_pa: float | None = None) -> None:
    """Write the −X interface hex plus a +X keyway hex.

    Element 1: y spans ±key_width/2 and z spans ±key_length/2 so the wall
    hex has volume. OD nodes are held. Interface nodes are free.
    Element 2: one corner is `_keyway_sample_node_mm` so live FRD sampling
    can resolve key.root.von_mises. Units in the deck are millimetres and
    MPa. When wall_pressure_pa is set, *DLOAD applies that B wall pressure
    (Pa converted to MPa) on the interface face so a static step has a
    nonzero u. Do not invent a displacement in the adapter if this load
    still falls under the motion floor; that is calibration.
    """
    x_id = _mm(params, "housing_id_mm") / 2.0
    x_od = _mm(params, "housing_od_mm") / 2.0
    if x_od <= x_id:
        raise ValueError("housing_od_mm must be greater than housing_id_mm")
    hy = _mm(params, "key_width_mm") / 2.0
    hz = _mm(params, "key_length_mm") / 2.0
    youngs = float(params["youngs_mpa"])
    poisson = float(params["poisson"])
    # Node ids 1,4,8,5 stay on the interface. Their x is −ID; OD nodes are
    # more negative. Element order below swaps those pairs so the local
    # first edge still points toward +X.
    corners = (
        (-x_id, -hy, -hz),
        (-x_od, -hy, -hz),
        (-x_od, hy, -hz),
        (-x_id, hy, -hz),
        (-x_id, -hy, hz),
        (-x_od, -hy, hz),
        (-x_od, hy, hz),
        (-x_id, hy, hz),
    )
    # Key hex is separate from the interface. Node 9 is the only node inside
    # geometric_tolerance_m of keyway_root. span_mm keeps the other seven
    # corners outside that ball.
    span_mm = 4.0
    kx, ky, kz = _keyway_sample_node_mm(params)
    key_corners = (
        (kx, ky, kz),
        (kx + span_mm, ky, kz),
        (kx + span_mm, ky + span_mm, kz),
        (kx, ky + span_mm, kz),
        (kx, ky, kz + span_mm),
        (kx + span_mm, ky, kz + span_mm),
        (kx + span_mm, ky + span_mm, kz + span_mm),
        (kx, ky + span_mm, kz + span_mm),
    )
    all_corners = corners + key_corners
    node_lines = [f"{nid}, {x:.6f}, {y:.6f}, {z:.6f}" for nid, (x, y, z) in enumerate(all_corners, start=1)]
    iface = ", ".join(str(nid) for nid in interface_node_ids())
    # OD face nodes are the complement of the interface set.
    od_nodes = (2, 3, 6, 7)
    bounds = "\n".join(f"{nid}, 1, 3" for nid in od_nodes)
    # Connectivity 2,1,4,3,6,5,8,7 puts global interface nodes on local face 4
    # (P4). Positive pressure is compressive on that face.
    dload = ""
    if wall_pressure_pa is not None and wall_pressure_pa == wall_pressure_pa:
        pressure_mpa = float(wall_pressure_pa) / 1.0e6
        dload = f"*DLOAD\n1, P4, {pressure_mpa}\n"
    text = f"""** C-FSI solid: wall hex on −X plus a keyway hex on +X.
** Independent of the A cavity and the B sandwich.
** interface nodes are the chamber_wall face at x = -housing_id_mm/2.
** Element 2 node 9 is the keyway_root sample (1 mm +Y), not the canonical pin.
** DLOAD P4 is B wall pressure in MPa so interface u is not prescribed.
*HEADING
c-fsi solid
*NODE
{chr(10).join(node_lines)}
*ELEMENT, TYPE=C3D8, ELSET=EALL
1, 2, 1, 4, 3, 6, 5, 8, 7
2, 9, 10, 11, 12, 13, 14, 15, 16
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
{dload}*NODE FILE
U, RF
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
    The OpenFOAM adapter copies it to system/blockMeshDict before blockMesh,
    because blockMesh reads the system dict and then rewrites polyMesh.
    x and y run from -housing_id/2 to +housing_id/2; z runs the chamber
    length, centered. Coordinates in the file are metres.
    The −X faces are the moving wall (`interface`), coplanar with
    chamber_wall. The +X face is a fixed wall. `lid` is the +Z wall.
    """
    half_id_m = _mm(params, "housing_id_mm") / 2000.0
    half_len_m = _mm(params, "chamber_length_mm") / 2000.0
    x0, x1 = -half_id_m, half_id_m
    y0, y1 = -half_id_m, half_id_m
    z0, z1 = -half_len_m, half_len_m
    # Vertex order matches the usual blockMesh hex (0 at xmin,ymin,zmin).
    text = f"""/* C-FSI fluid blockMesh. Independent of write_chamber_case (A cavity).
   Moving wall is the −X chamber_wall plane, not the +X housing-ID plane. */
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
            (0 4 7 3)
        );
    }}
    walls
    {{
        type wall;
        faces
        (
            (2 6 5 1)
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
