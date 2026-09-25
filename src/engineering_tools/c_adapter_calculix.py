"""CalculiX participant adapter for C-FSI.

Agents: CalculiX joins preCICE through the calculix-adapter binary
(`ccx_preCICE`), not a finished standalone `ccx` job. Plain `ccx` remains
the A/B solver only. This module must not execute a process named `precice`
(`c_backend_precice.run_step` owns that). The façade calls `run_step` then
`sample_c_probes`. Probe values are SI: stress Pa, displacement metres.
Do not invent a displacement when DISP is missing or near zero; the deck's
*DLOAD is what is supposed to move the interface.

Launch argv (https://precice.org/adapter-calculix-config.html), stem without
`.inp`, participant name matching the YAML and the preCICE XML:

    ccx_preCICE -i <deck-stem> -precice-participant Solid

The adapter reads `config.yml` from the process working directory. It does
not take that filename on the command line.
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


# Search order matches upstream binary names. Do not add plain `ccx`.
_PARTICIPANT_BINARIES = ("ccx_preCICE", "ccx_precice", "calculix-precice")
# preCICE participant name in XML, YAML, and `-precice-participant`.
_SOLID_PARTICIPANT = "Solid"
# Filename the CalculiX-preCICE adapter opens in cwd. Do not rename.
_ADAPTER_CONFIG_NAME = "config.yml"


def find_calculix_participant() -> Path | None:
    """Return the calculix-adapter binary, or None when it is not on PATH.

    Order: `ccx_preCICE`, then `ccx_precice`, then `calculix-precice`.
    A hit on plain `ccx` is ignored; that binary is not a preCICE participant.
    """
    for name in _PARTICIPANT_BINARIES:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def prepare_solid_participant(workdir: Path, config_xml: Path) -> Path:
    """Write `config.yml` for the CalculiX-preCICE adapter and return that path.

    Schema follows https://precice.org/adapter-calculix-config.html: a
    `participants` map (historical plural) keyed by participant name Solid,
    one `nodes-mesh` interface, `read-data` Traction, `write-data`
    Displacement, and `precice-config-file` pointing at the façade XML.

    Agents: the mesh name `interface` is `default_policy()["mesh_name"]`.
    The adapter prefixes `N` onto a nodes-mesh patch when it looks up the
    CalculiX *NSET, so a live deck NSET must be `Ninterface` for patch
    `interface`. Data names are the C policy fields, not the tutorial
    aliases Forces/DisplacementDeltas; the adapter classifies names by
    prefix (Force, Displacement, Pressure).
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    config_xml = Path(config_xml)
    # Absolute path so the adapter finds the XML regardless of case cwd.
    precice_config = config_xml.resolve()
    text = (
        "participants:\n"
        f"  {_SOLID_PARTICIPANT}:\n"
        "    interfaces:\n"
        "    - nodes-mesh: interface\n"
        "      patch: interface\n"
        "      read-data: [Traction]\n"
        "      write-data: [Displacement]\n"
        f"precice-config-file: {precice_config}\n"
    )
    destination = workdir / _ADAPTER_CONFIG_NAME
    destination.write_text(text, encoding="utf-8")
    return destination


def run_step(workdir: Path, step: int) -> bool:
    """Launch the CalculiX-preCICE participant on the deck in `workdir`.

    True only when `ccx_preCICE` (or a documented alias) exits 0. Missing
    participant binary or missing `*.inp` returns False and does not spawn
    `ccx` or `precice`. `step` is the façade coupling index; the adapter
    argv has no window counter (upstream runs the coupled step inside one
    process). When the façade has already written `precice-config.xml`
    beside this workdir, this call also refreshes `config.yml` so the
    participant can open it.
    """
    del step
    workdir = Path(workdir)
    binary = find_calculix_participant()
    decks = sorted(workdir.glob("*.inp"))
    if binary is None or not decks:
        return False
    # Refuse the two binaries this module must never treat as the participant.
    if binary.name in {"ccx", "precice"}:
        return False
    sibling_xml = workdir.parent / "precice-config.xml"
    if sibling_xml.is_file():
        prepare_solid_participant(workdir, sibling_xml)
    argv = [str(binary), "-i", decks[0].stem, "-precice-participant", _SOLID_PARTICIPANT]
    try:
        proc = subprocess.run(
            argv,
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
    `key.root.von_mises` uses the nearest stressed node to the keyway_root
    pin. That node is element 2's first corner (1 mm +Y of the pin). Report
    that node's coordinates. Do not substitute canonical_xyz_m; a substituted
    pin is not a mesh node and fails the live sample test.
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
