"""CalculiX participant adapter for C-FSI.

Agents: the façade calls `run_step` then `sample_c_probes`. This module may
execute `ccx`. It must not execute `precice` (that stays in
`c_backend_precice.run_step`). Probe values are SI: stress Pa, displacement
metres. Do not invent a displacement when DISP is missing or near zero; the
deck's *DLOAD is what is supposed to move the interface.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path
from typing import Any

from engineering_tools.c_contract import mm_to_m
from engineering_tools.c_fsi_meshes import interface_node_ids
from engineering_tools.c_parity import mpa_to_pa
from engineering_tools.damper_fea import _floats, _mises_from_tensor
from engineering_tools.damper_params import load_params, probes_from_params


def run_step(workdir: Path, step: int) -> bool:
    """Run `ccx` on the C deck in workdir. True only when the process exits 0.

    Each coupling index re-runs the static deck. `step` is recorded by the
    façade; CalculiX itself has no window counter in this deck.
    """
    del step
    decks = sorted(workdir.glob("*.inp"))
    ccx = shutil.which("ccx")
    if not decks or not ccx:
        return False
    try:
        proc = subprocess.run(
            [ccx, decks[0].stem],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _parse_frd(text: str) -> tuple[dict[int, tuple[float, float, float]], dict[int, tuple[float, float, float]], dict[int, float]]:
    """Return node coords (mm), DISP vectors (mm), and von Mises (MPa)."""
    coords: dict[int, tuple[float, float, float]] = {}
    disp: dict[int, tuple[float, float, float]] = {}
    stress: dict[int, float] = {}
    mode: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("2C"):
            mode = "nodes"
            continue
        if line.startswith(" -4") and "DISP" in line:
            mode = "disp"
            continue
        if line.startswith(" -4") and "STRESS" in line:
            mode = "stress"
            continue
        if line.startswith(" -3"):
            mode = None
            continue
        if not line.startswith(" -1"):
            continue
        nums = _floats(line[3:].strip())
        if mode == "nodes" and len(nums) >= 4:
            coords[int(nums[0])] = (nums[1], nums[2], nums[3])
        elif mode == "disp" and len(nums) >= 4:
            disp[int(nums[0])] = (nums[1], nums[2], nums[3])
        elif mode == "stress" and len(nums) >= 7:
            stress[int(nums[0])] = _mises_from_tensor(*nums[1:7])
    return coords, disp, stress


def _latest_frd(workdir: Path) -> Path | None:
    frds = [path for path in workdir.glob("*.frd") if path.is_file() and path.stat().st_size > 0]
    if not frds:
        return None
    return max(frds, key=lambda path: path.stat().st_mtime)


def sample_c_probes(out: Path) -> dict[str, Any]:
    """Sample the solid workdir FRD into SI probe rows.

    `housing.wall.displacement` xyz is the centroid of interface nodes.
    `key.root.von_mises` uses the nearest node to the keyway_root pin.
    That pin is not on the one-element −X hex, so the reported xyz will
    miss geometric_tolerance_m until the mesh includes the key root.
    Missing FRD or DISP yields a partial dict; the façade fail-closes.
    """
    frd_path = _latest_frd(out)
    if frd_path is None:
        return {}
    coords, disp, stress = _parse_frd(frd_path.read_text(encoding="utf-8", errors="replace"))
    probes: dict[str, Any] = {}
    iface = [nid for nid in interface_node_ids() if nid in coords]
    if iface and disp:
        mags: list[float] = []
        centroid = [0.0, 0.0, 0.0]
        for nid in iface:
            centroid[0] += coords[nid][0]
            centroid[1] += coords[nid][1]
            centroid[2] += coords[nid][2]
            if nid not in disp:
                continue
            ux, uy, uz = disp[nid]
            mags.append(math.sqrt(ux * ux + uy * uy + uz * uz) / 1000.0)
        centroid = [component / len(iface) for component in centroid]
        if mags:
            probes["housing.wall.displacement"] = {
                "value": max(mags),
                "xyz_m": mm_to_m(centroid),
            }
    if coords and stress:
        target = probes_from_params(load_params())["keyway_root"]
        best_id: int | None = None
        best_d: float | None = None
        for nid, xyz in coords.items():
            if nid not in stress:
                continue
            dist = (xyz[0] - target[0]) ** 2 + (xyz[1] - target[1]) ** 2 + (xyz[2] - target[2]) ** 2
            if best_d is None or dist < best_d:
                best_d = dist
                best_id = nid
        if best_id is not None:
            node = coords[best_id]
            probes["key.root.von_mises"] = {
                "value": mpa_to_pa(stress[best_id]),
                "xyz_m": mm_to_m([node[0], node[1], node[2]]),
            }
    return probes
