"""Phase E CalculiX deck from independent Gmsh tets, FSI NSET on inner wall.

Agents: live Solid is C3D4 Eshell plus C3D4 Elid. Every Elid node has a
stiffness row and a 1-3 zero boundary. Do not constrain a node that is in
no element: SPOOLES dereferences a null row. No *RIGID BODY and no 1-6 range.
Elid nodes stay off NinterfaceN and out of the *DFLUX matcher. Heat-Flux is
*DFLUX on Eshell faces (faces-mesh interface-faces). The adapter looks up
SINTERFACET (S + patch interface + T) before the step; that ELEMENT surface
uses the same elem/face pairs as *DFLUX. Temperature is nodes-mesh NT.
NinterfaceN is face.inner_wall. No damper sandwich.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from engineering_tools.c_adapter_calculix import _latest_frd, _parse_frd, prepare_solid_participant
from engineering_tools.e_mesh_solid import write_solid_mesh
from engineering_tools.e_msh2 import (
    interface_nodes_from_physical,
    interface_triangles,
    parse_msh2_volume,
    tets_from_physical_volume,
)

INNER_WALL = "face.inner_wall"
_E_PA = 2.0e11
_NU = 0.3
_RHO = 7850.0
_K_W_MK = 45.0
_CP_J_KGK = 500.0
_T0_K = 300.0
_DT = 0.01
_T_END = 0.02
# Gas radius 0.02 m, housing OD 0.025 m (build_vessel).
_INNER_R = (0.018, 0.022)
_OUTER_R_MIN = 0.0235

# Packaged wedge: Physical Surface face.inner_wall (nodes 1-3), body.shell tets,
# and a body.lid tet on nodes 7-10 above the wedge. PATH Gmsh copies this file.
CI_SOLID_MSH2 = """$MeshFormat
2.2 0 8
$EndMeshFormat
$PhysicalNames
3
2 99 "face.inner_wall"
3 1 "body.shell"
3 2 "body.lid"
$EndPhysicalNames
$Nodes
10
1 -0.02 -0.005 0
2 -0.02 0.005 0
3 -0.02 0 0.04
4 -0.025 -0.005 0
5 -0.025 0.005 0
6 -0.025 0 0.04
7 -0.025 -0.005 0.044
8 -0.025 0.005 0.044
9 -0.02 0 0.044
10 -0.022 0 0.042
$EndNodes
$Elements
5
1 2 2 99 1 1 2 3
2 4 2 1 1 1 2 3 4
3 4 2 1 1 2 5 3 6
4 4 2 1 1 2 3 4 6
5 4 2 2 1 7 8 9 10
$EndElements
"""


def _dflux_lines(
    triangles: list[tuple[int, int, int]],
    shell_tets: list[tuple[int, int, int, int]],
) -> list[str] | None:
    """Zero *DFLUX on each inner-wall triangle's unique Eshell face. None if unmatched."""
    lines: list[str] = []
    for tri in triangles:
        tri_set = set(tri)
        matches: list[tuple[int, tuple[int, int, int, int]]] = []
        for index, tet in enumerate(shell_tets, start=1):
            if tri_set <= set(tet):
                matches.append((index, tet))
        if len(matches) != 1:
            return None
        elem_id, (n1, n2, n3, n4) = matches[0]
        opposite = (set((n1, n2, n3, n4)) - tri_set).pop()
        if opposite == n4:
            face = "S1"
        elif opposite == n3:
            face = "S2"
        elif opposite == n1:
            face = "S3"
        elif opposite == n2:
            face = "S4"
        else:
            return None
        lines.append(f"{elem_id}, {face}, 0.")
    return lines


def _sinterfacet_lines(dflux: list[str]) -> list[str] | None:
    """ELEMENT rows for SINTERFACET. Same element and S1 to S4 as each *DFLUX line.

    Agents: CalculiX names the face set S + patch + T. Patch stays interface,
    so the set is SINTERFACET. faces-mesh interface-faces is not this name.
    None when no face would be written.
    """
    rows: list[str] = []
    for line in dflux:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 3 or parts[2] != "0." or parts[1] not in {"S1", "S2", "S3", "S4"}:
            return None
        rows.append(f"{parts[0]}, {parts[1]}")
    if not rows:
        return None
    return rows


def _write_e_solid_adapter_config(workdir: Path, config_xml: Path) -> None:
    """Overwrite config.yml: nodes-mesh Force/U/T, faces-mesh Heat-Flux."""
    precice_config = Path(config_xml).resolve()
    text = (
        "participants:\n"
        "  Solid:\n"
        "    interfaces:\n"
        "    - nodes-mesh: interface\n"
        "      patch: interface\n"
        "      read-data: [Force]\n"
        "      write-data: [Displacement, Temperature]\n"
        "    - faces-mesh: interface-faces\n"
        "      patch: interface\n"
        "      read-data: [Heat-Flux]\n"
        f"precice-config-file: {precice_config}\n"
    )
    (Path(workdir) / "config.yml").write_text(text, encoding="utf-8")


def _radius(xyz: tuple[float, float, float]) -> float:
    return math.hypot(xyz[0], xyz[1])


def _chunk_csv(ids: list[int], per_line: int = 12) -> str:
    lines = []
    for start in range(0, len(ids), per_line):
        lines.append(", ".join(str(n) for n in ids[start : start + per_line]))
    return "\n".join(lines)


def write_e_solid_inp(
    path: Path,
    identity: dict[str, Any],
    *,
    msh: Path | None = None,
    dt_s: float = _DT,
    t_end_s: float = _T_END,
) -> dict[str, Any]:
    """C3D4 shell plus C3D4 lid. Interface NSET from Physical Surface.

    Agents: Elid ids continue after Eshell. Boundary and 300 K initial
    temperature cover every Elid node, which is now in the coupled step.
    Shell ids and the *DFLUX face match stay on Eshell only.
    """
    ids = set(identity.get("entity_ids") or [])
    if INNER_WALL not in ids:
        return {"status": "broken", "detail": f"identity missing {INNER_WALL}"}
    if msh is None:
        return {"status": "broken", "detail": "independent solid msh required"}
    msh = Path(msh)
    if not msh.is_file():
        return {"status": "broken", "detail": f"missing msh {msh}"}
    text = msh.read_text(encoding="utf-8", errors="replace")
    nodes, _all_tets = parse_msh2_volume(text)
    shell_tets = tets_from_physical_volume(text, "body.shell")
    lid_tets = tets_from_physical_volume(text, "body.lid")
    if not lid_tets:
        return {"status": "broken", "detail": "Physical Volume body.lid is missing"}
    if len(nodes) < 4 or not shell_tets:
        return {"status": "broken", "detail": "msh has no C3D4 shell tets"}
    iface = interface_nodes_from_physical(text, INNER_WALL)
    if not iface:
        return {"status": "broken", "detail": "Physical Surface face.inner_wall has no vertices"}
    lid_nodes = sorted({nid for tet in lid_tets for nid in tet})
    lid_set = set(lid_nodes)
    shell_ids = {nid for tet in shell_tets for nid in tet}
    # Shared nodes stay in both element sets. The interface set and DFLUX stay on the shell.
    iface = [nid for nid in iface if nid not in lid_set]
    if not iface:
        return {"status": "broken", "detail": "face.inner_wall vertices are only on Elid"}
    lid_only = sorted(nid for nid in lid_nodes if nid not in shell_ids)
    iface_set = set(iface)
    outer = sorted(
        nid
        for nid, xyz in nodes.items()
        if nid not in iface_set and nid not in lid_set and _radius(xyz) >= _OUTER_R_MIN
    )
    if not outer:
        return {"status": "broken", "detail": "no outer-wall nodes to constrain"}
    triangles = interface_triangles(text, INNER_WALL)
    dflux = _dflux_lines(triangles, shell_tets)
    if not triangles or dflux is None:
        return {"status": "broken", "detail": "inner-wall triangle does not match exactly one Eshell tet"}
    surface = _sinterfacet_lines(dflux)
    if surface is None:
        return {"status": "broken", "detail": "SINTERFACET would be empty"}
    node_lines = [f"{nid}, {xyz[0]:.8f}, {xyz[1]:.8f}, {xyz[2]:.8f}" for nid, xyz in sorted(nodes.items())]
    elem_lines = [f"{i}, {a}, {b}, {c}, {d}" for i, (a, b, c, d) in enumerate(shell_tets, start=1)]
    lid_elem_lines = [
        f"{i}, {a}, {b}, {c}, {d}"
        for i, (a, b, c, d) in enumerate(lid_tets, start=len(shell_tets) + 1)
    ]
    cload_zero = "\n".join(f"{n}, {dof}, 0." for n in iface for dof in (1, 2, 3))
    lid_bounds = "\n".join(f"{nid}, 1, 3, 0." for nid in lid_nodes)
    bounds = "\n".join(f"{n}, 1, 3" for n in outer)
    thermal_nodes = sorted(shell_ids | lid_set)
    t_init = "\n".join(f"{nid}, {_T0_K}" for nid in thermal_nodes)
    dflux_block = "\n".join(dflux)
    surface_block = "\n".join(surface)
    deck = f"""** E-FSI solid: elastic shell + rigid lid. CAD face {INNER_WALL}.
*HEADING
e-vessel solid tets
*NODE
{chr(10).join(node_lines)}
*ELEMENT, TYPE=C3D4, ELSET=Eshell
{chr(10).join(elem_lines)}
*ELEMENT, TYPE=C3D4, ELSET=Elid
{chr(10).join(lid_elem_lines)}
*NSET, NSET=NinterfaceN
{_chunk_csv(iface)}
*NSET, NSET=NlidRigid
{_chunk_csv(lid_nodes)}
*SURFACE, NAME=SINTERFACET, TYPE=ELEMENT
{surface_block}
*MATERIAL, NAME=Steel
*ELASTIC
{_E_PA}, {_NU}
*DENSITY
{_RHO}
*CONDUCTIVITY
{_K_W_MK}
*SPECIFIC HEAT
{_CP_J_KGK}
*SOLID SECTION, ELSET=Eshell, MATERIAL=Steel
*SOLID SECTION, ELSET=Elid, MATERIAL=Steel
*BOUNDARY
{lid_bounds}
*BOUNDARY
{bounds}
*INITIAL CONDITIONS, TYPE=TEMPERATURE
{t_init}
*STEP, INC=1000000
*COUPLED TEMPERATURE-DISPLACEMENT, DIRECT
{dt_s}, {t_end_s}
*CLOAD
{cload_zero}
*DFLUX
{dflux_block}
*NODE FILE
U, RF, FORC, NT
*EL FILE
S
*END STEP
"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(deck, encoding="utf-8")
    return {
        "status": "ok",
        "detail": str(path),
        "nset": "NinterfaceN",
        "entity_id": INNER_WALL,
        "topology_version": int(identity.get("topology_version") or 1),
        "node_ids": iface,
        "volume_nodes": len(nodes),
        "n_tets": len(shell_tets),
        "lid_nodes": lid_nodes,
        "lid_only": lid_only,
        "path": str(path),
        "msh": str(msh),
    }


def prepare_e_solid_participant(
    workdir: Path,
    config_xml: Path,
    identity: dict[str, Any],
    *,
    msh: Path | None = None,
    dt_s: float = _DT,
    t_end_s: float = _T_END,
) -> dict[str, Any]:
    """Gmsh tets become e-solid.inp and the CalculiX adapter config.yml."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    msh_path = Path(msh) if msh is not None else None
    if msh_path is None:
        generated = write_solid_mesh(workdir / "gmsh", identity)
        if generated.get("status") != "ok":
            return generated
        msh_path = Path(str(generated["artifact"]))
    deck = write_e_solid_inp(workdir / "e-solid.inp", identity, msh=msh_path, dt_s=dt_s, t_end_s=t_end_s)
    if deck.get("status") != "ok":
        return deck
    prepare_solid_participant(workdir, config_xml)
    _write_e_solid_adapter_config(workdir, config_xml)
    gmsh_json = workdir / "gmsh" / "solid-mesh.json"
    if gmsh_json.is_file():
        deck["mesh_record"] = str(gmsh_json)
    return deck


def _ninterface_ids(workdir: Path) -> list[int]:
    """Parse NinterfaceN from e-solid.inp. Empty if the set is missing."""
    inp = Path(workdir) / "e-solid.inp"
    if not inp.is_file():
        return []
    text = inp.read_text(encoding="utf-8")
    match = re.search(r"\*NSET,\s*NSET=NinterfaceN\s*\n([^\*]+)", text, re.I)
    if not match:
        return []
    return [int(n) for n in re.findall(r"\d+", match.group(1))]


def _parse_frd_forc(text: str) -> dict[int, tuple[float, float, float]]:
    """Nodal FORC vectors from an FRD. Empty if the block is absent."""
    from engineering_tools.c_adapter_calculix import _floats

    forc: dict[int, tuple[float, float, float]] = {}
    mode = False
    for line in text.splitlines():
        if line.startswith(" -4") and "FORC" in line:
            mode = True
            continue
        if line.startswith(" -3"):
            mode = False
            continue
        if not mode or not line.startswith(" -1"):
            continue
        nums = _floats(line[3:].strip())
        if len(nums) >= 4:
            forc[int(nums[0])] = (nums[1], nums[2], nums[3])
    return forc


def sample_e_solid_probes(out: Path) -> dict[str, Any]:
    """Complete-interface DISP max (m) and traction magnitude (N) from FRD FORC.

    Agents: FRD FORC is treated as nodal applied/received load on NinterfaceN,
    not proven preCICE mapped Force arrays. Missing any interface DISP or FORC
    yields no measurement. value is sum ||FORC||, not net resultant.
    """
    frd_path = _latest_frd(out)
    if frd_path is None:
        return {}
    text = frd_path.read_text(encoding="utf-8", errors="replace")
    coords, disp, _stress = _parse_frd(text)
    expected = _ninterface_ids(out)
    if not expected:
        return {}
    if any(nid not in coords or nid not in disp for nid in expected):
        return {}
    mags: list[tuple[int, float]] = []
    for nid in expected:
        ux, uy, uz = disp[nid]
        mags.append((nid, math.sqrt(ux * ux + uy * uy + uz * uz)))
    max_nid, max_mag = max(mags, key=lambda item: item[1])
    probes: dict[str, Any] = {
        "face.inner_wall.displacement": {
            "value": max_mag,
            "unit": "m",
            "entity_id": INNER_WALL,
            "kind": "max_magnitude",
            "xyz_m": list(coords[max_nid]),
            "node_id": max_nid,
            "expected_interface_nodes": len(expected),
            "observed_disp_nodes": len(expected),
        }
    }
    forc = _parse_frd_forc(text)
    if any(nid not in forc for nid in expected):
        return probes
    fx = fy = fz = 0.0
    l1 = 0.0
    for nid in expected:
        vx, vy, vz = forc[nid]
        fx += vx
        fy += vy
        fz += vz
        l1 += math.sqrt(vx * vx + vy * vy + vz * vz)
    net_mag = math.sqrt(fx * fx + fy * fy + fz * fz)
    probes["face.inner_wall.integrated_force"] = {
        "value": l1,
        "unit": "N",
        "entity_id": INNER_WALL,
        "kind": "integrated_traction_magnitude",
        "l1_N": l1,
        "net_components_N": [fx, fy, fz],
        "net_magnitude_N": net_mag,
        "components_N": [fx, fy, fz],
        "expected_interface_nodes": len(expected),
        "observed_forc_nodes": len(expected),
        "endpoint": "frd_FORC_complete_NinterfaceN",
    }
    return probes
