"""Phase E CalculiX deck: SI vessel envelope, FSI NSET on face.inner_wall.

Agents: this is not the D sandwich. Inner wall is x=-0.02 m (gas radius),
matching the fluid hex envelope -X patch `inner_wall`. NSET must be
NinterfaceN so ccx_preCICE maps preCICE mesh `interface`. Zero *CLOAD
reserves Force slots. No belt CLOAD. No damper DLOAD.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from engineering_tools.c_adapter_calculix import _latest_frd, _parse_frd, prepare_solid_participant

INNER_WALL = "face.inner_wall"
_E_PA = 2.0e11
_NU = 0.3
_RHO = 7850.0
_DT = 0.01
_T_END = 0.02


def _nid(ix: int, iy: int, iz: int) -> int:
    return ix * 4 + iy * 2 + iz + 1


def write_e_solid_inp(path: Path, identity: dict[str, Any]) -> dict[str, Any]:
    """One C3D8 through the housing thickness. FSI nodes on the gas wall."""
    ids = set(identity.get("entity_ids") or [])
    if INNER_WALL not in ids:
        return {"status": "broken", "detail": f"identity missing {INNER_WALL}"}
    xs = [-0.025, -0.020]
    ys = [-0.020, 0.020]
    zs = [0.0, 0.040]
    node_lines = []
    for ix, x in enumerate(xs):
        for iy, y in enumerate(ys):
            for iz, z in enumerate(zs):
                node_lines.append(
                    f"{_nid(ix, iy, iz)}, {x:.8f}, {y:.8f}, {z:.8f}"
                )
    n000, n100 = _nid(0, 0, 0), _nid(1, 0, 0)
    n110, n010 = _nid(1, 1, 0), _nid(0, 1, 0)
    n001, n101 = _nid(0, 0, 1), _nid(1, 0, 1)
    n111, n011 = _nid(1, 1, 1), _nid(0, 1, 1)
    elem = f"1, {n000}, {n100}, {n110}, {n010}, {n001}, {n101}, {n111}, {n011}"
    iface = [_nid(1, iy, iz) for iy in range(2) for iz in range(2)]
    outer = [_nid(0, iy, iz) for iy in range(2) for iz in range(2)]
    iface_set = ", ".join(str(n) for n in iface)
    cload_zero = "\n".join(f"{n}, {dof}, 0." for n in iface for dof in (1, 2, 3))
    bounds = "\n".join(f"{n}, 1, 3" for n in outer)
    text = f"""** E-FSI solid: vessel housing envelope in SI. CAD face {INNER_WALL}.
*HEADING
e-vessel solid
*NODE
{chr(10).join(node_lines)}
*ELEMENT, TYPE=C3D8, ELSET=EALL
{elem}
*NSET, NSET=NinterfaceN
{iface_set}
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
        "path": str(path),
    }


def prepare_e_solid_participant(workdir: Path, config_xml: Path, identity: dict[str, Any]) -> dict[str, Any]:
    """Write e-solid.inp + CalculiX adapter config.yml (Force/Displacement)."""
    workdir = Path(workdir)
    deck = write_e_solid_inp(workdir / "e-solid.inp", identity)
    if deck.get("status") != "ok":
        return deck
    prepare_solid_participant(workdir, config_xml)
    return deck


def _ninterface_ids(workdir: Path) -> list[int]:
    """Parse NinterfaceN from e-solid.inp. Empty if the set is missing."""
    import re

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

