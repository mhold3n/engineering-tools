"""Phase E CalculiX deck from independent Gmsh tets, FSI NSET on inner wall.

Agents: live Solid is C3D4 from solid.msh, not the 8-node hex envelope.
NinterfaceN is nodes with r≈0.02 m (gas wall). Outer r≈0.025 is *BOUNDARY.
NSET must stay NinterfaceN for ccx_preCICE mesh `interface`. Zero *CLOAD
reserves Force slots. No damper sandwich.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from engineering_tools.c_adapter_calculix import _latest_frd, _parse_frd, prepare_solid_participant
from engineering_tools.e_mesh_solid import write_solid_mesh

INNER_WALL = "face.inner_wall"
_E_PA = 2.0e11
_NU = 0.3
_RHO = 7850.0
_DT = 0.01
_T_END = 0.02
# Gas radius 0.02 m, housing OD 0.025 m (build_vessel).
_INNER_R = (0.018, 0.022)
_OUTER_R_MIN = 0.0235

# Packaged 6-node wedge for pytest mapping tests when gmsh is absent.
CI_SOLID_MSH2 = """$MeshFormat
2.2 0 8
$EndMeshFormat
$Nodes
6
1 -0.02 -0.005 0
2 -0.02 0.005 0
3 -0.02 0 0.04
4 -0.025 -0.005 0
5 -0.025 0.005 0
6 -0.025 0 0.04
$EndNodes
$Elements
3
1 4 2 1 1 1 2 3 4
2 4 2 1 1 2 5 3 6
3 4 2 1 1 2 3 4 6
$EndElements
"""


def _radius(xyz: tuple[float, float, float]) -> float:
    return math.hypot(xyz[0], xyz[1])


def parse_msh2(text: str) -> tuple[dict[int, tuple[float, float, float]], list[tuple[int, int, int, int]]]:
    """MSH 2 nodes and type-4 tets. Surface triangles are ignored."""
    nodes: dict[int, tuple[float, float, float]] = {}
    tets: list[tuple[int, int, int, int]] = []
    if "$Nodes" not in text or "$Elements" not in text:
        return nodes, tets
    node_body = text.split("$Nodes", 1)[1].split("$EndNodes", 1)[0].strip().splitlines()
    for line in node_body[1:]:
        parts = line.split()
        if len(parts) >= 4:
            nodes[int(parts[0])] = (float(parts[1]), float(parts[2]), float(parts[3]))
    elem_body = text.split("$Elements", 1)[1].split("$EndElements", 1)[0].strip().splitlines()
    for line in elem_body[1:]:
        parts = line.split()
        if len(parts) < 8:
            continue
        # MSH2: id type ntags phys ... nodes. Type 4 = tet4.
        if int(parts[1]) != 4:
            continue
        ntags = int(parts[2])
        nids = [int(p) for p in parts[3 + ntags :]]
        if len(nids) == 4:
            tets.append((nids[0], nids[1], nids[2], nids[3]))
    return nodes, tets


def _chunk_csv(ids: list[int], per_line: int = 12) -> str:
    lines = []
    for start in range(0, len(ids), per_line):
        lines.append(", ".join(str(n) for n in ids[start : start + per_line]))
    return "\n".join(lines)


def write_e_solid_inp(path: Path, identity: dict[str, Any], *, msh: Path | None = None) -> dict[str, Any]:
    """C3D4 deck from a Gmsh msh2. msh is required (no hex fallback)."""
    ids = set(identity.get("entity_ids") or [])
    if INNER_WALL not in ids:
        return {"status": "broken", "detail": f"identity missing {INNER_WALL}"}
    if msh is None:
        return {"status": "broken", "detail": "independent solid msh required"}
    msh = Path(msh)
    if not msh.is_file():
        return {"status": "broken", "detail": f"missing msh {msh}"}
    nodes, tets = parse_msh2(msh.read_text(encoding="utf-8", errors="replace"))
    if len(nodes) < 4 or not tets:
        return {"status": "broken", "detail": "msh has no C3D4 tets"}
    iface = sorted(nid for nid, xyz in nodes.items() if _INNER_R[0] <= _radius(xyz) <= _INNER_R[1])
    outer = sorted(nid for nid, xyz in nodes.items() if _radius(xyz) >= _OUTER_R_MIN)
    if not iface:
        return {"status": "broken", "detail": "no inner-wall nodes at r≈0.02 m"}
    if not outer:
        return {"status": "broken", "detail": "no outer-wall nodes to constrain"}
    node_lines = [f"{nid}, {xyz[0]:.8f}, {xyz[1]:.8f}, {xyz[2]:.8f}" for nid, xyz in sorted(nodes.items())]
    elem_lines = [f"{i}, {a}, {b}, {c}, {d}" for i, (a, b, c, d) in enumerate(tets, start=1)]
    cload_zero = "\n".join(f"{n}, {dof}, 0." for n in iface for dof in (1, 2, 3))
    bounds = "\n".join(f"{n}, 1, 3" for n in outer)
    text = f"""** E-FSI solid: Gmsh tet housing. CAD face {INNER_WALL}. Independent of fluid hex.
*HEADING
e-vessel solid tets
*NODE
{chr(10).join(node_lines)}
*ELEMENT, TYPE=C3D4, ELSET=EALL
{chr(10).join(elem_lines)}
*NSET, NSET=NinterfaceN
{_chunk_csv(iface)}
*MATERIAL, NAME=Steel
*ELASTIC
{_E_PA}, {_NU}
*DENSITY
{_RHO}
*SOLID SECTION, ELSET=EALL, MATERIAL=Steel
*BOUNDARY
{bounds}
*STEP, INC=1000000
*DYNAMIC, ALPHA=0.0, DIRECT
{_DT}, {_T_END}
*CLOAD
{cload_zero}
*NODE FILE
U, RF
*EL FILE
S
*END STEP
"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return {
        "status": "ok",
        "detail": str(path),
        "nset": "NinterfaceN",
        "entity_id": INNER_WALL,
        "topology_version": int(identity.get("topology_version") or 1),
        "node_ids": iface,
        "volume_nodes": len(nodes),
        "n_tets": len(tets),
        "path": str(path),
        "msh": str(msh),
    }


def prepare_e_solid_participant(
    workdir: Path,
    config_xml: Path,
    identity: dict[str, Any],
    *,
    msh: Path | None = None,
) -> dict[str, Any]:
    """Gmsh tets → e-solid.inp + CalculiX adapter config.yml."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    msh_path = Path(msh) if msh is not None else None
    if msh_path is None:
        generated = write_solid_mesh(workdir / "gmsh", identity)
        if generated.get("status") != "ok":
            return generated
        msh_path = Path(str(generated["artifact"]))
    deck = write_e_solid_inp(workdir / "e-solid.inp", identity, msh=msh_path)
    if deck.get("status") != "ok":
        return deck
    prepare_solid_participant(workdir, config_xml)
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


def sample_e_solid_probes(out: Path) -> dict[str, Any]:
    """Interface DISP magnitude in metres from the latest FRD."""
    frd_path = _latest_frd(out)
    if frd_path is None:
        return {}
    coords, disp, _stress = _parse_frd(frd_path.read_text(encoding="utf-8", errors="replace"))
    iface = [nid for nid in _ninterface_ids(out) if nid in coords]
    if not iface or not disp:
        return {}
    mags: list[float] = []
    centroid = [0.0, 0.0, 0.0]
    for nid in iface:
        centroid[0] += coords[nid][0]
        centroid[1] += coords[nid][1]
        centroid[2] += coords[nid][2]
        if nid not in disp:
            continue
        ux, uy, uz = disp[nid]
        mags.append(math.sqrt(ux * ux + uy * uy + uz * uz))
    centroid = [component / len(iface) for component in centroid]
    if not mags:
        return {}
    return {
        "face.inner_wall.displacement": {
            "value": max(mags),
            "unit": "m",
            "entity_id": INNER_WALL,
            "xyz_m": centroid,
        }
    }
