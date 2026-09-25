"""CalculiX deck for the damper scenario.

Coarse radial sandwich of C3D8 bricks from damper-params (not a tet of STEP):
shaft | key-in-gap | key-in-keyway | housing rim. Shaft-axis nodes held.
Belt torque is a tangential (+Y) CLOAD on the OD face, traction * belt-land area.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _floats(payload: str) -> list[float]:
    """Split FRD numeric fields, including glued scientific notation."""
    return [float(x) for x in re.findall(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?", payload)]


def _radial_stations(params: dict[str, Any]) -> tuple[list[float], list[float], list[float]]:
    """x (radial), y, z stations in mm matching probes_from_params."""
    shaft_r = float(params["shaft_od_mm"]) / 2.0
    id_r = float(params["housing_id_mm"]) / 2.0
    od_r = float(params["housing_od_mm"]) / 2.0
    depth = float(params["keyway_depth_mm"])
    hy = float(params["key_width_mm"]) / 2.0
    hz = float(params["key_length_mm"]) / 2.0
    xs = [0.0, shaft_r, id_r, id_r + depth, od_r]
    return xs, [-hy, hy], [-hz, hz]


def _nid(ix: int, iy: int, iz: int) -> int:
    """Node number: x-plane, then y, then z. 2 y × 2 z per plane."""
    return ix * 4 + iy * 2 + iz + 1


def write_solid_inp(params: dict[str, Any], destination: Path) -> Path:
    """Write four C3D8 bricks; belt-land CLOAD is direction 2 (tangential)."""
    xs, ys, zs = _radial_stations(params)
    youngs = float(params["youngs_mpa"])
    poisson = float(params["poisson"])
    traction = float(params["belt_land_traction_mpa"])
    area = float(params["key_width_mm"]) * float(params["key_length_mm"])
    force = traction * area / 4.0
    node_lines = []
    for ix, x in enumerate(xs):
        for iy, y in enumerate(ys):
            for iz, z in enumerate(zs):
                node_lines.append(f"{_nid(ix, iy, iz)}, {x:.6f}, {y:.6f}, {z:.6f}")
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
        elem_lines.append(f"{ix + 1}, {n000}, {n100}, {n110}, {n010}, {n001}, {n101}, {n111}, {n011}")
    od_ix = len(xs) - 1
    cload_nodes = [_nid(od_ix, iy, iz) for iy in range(2) for iz in range(2)]
    axis_nodes = [_nid(0, iy, iz) for iy in range(2) for iz in range(2)]
    cload = "\n".join(f"{n}, 2, {force}" for n in cload_nodes)
    bounds = "\n".join(f"{n}, 1, 3" for n in axis_nodes)
    text = f"""** engineering-tools damper-keyway solid (MIT sample deck)
*HEADING
damper-keyway solid
*NODE
{chr(10).join(node_lines)}
*ELEMENT, TYPE=C3D8, ELSET=EALL
{chr(10).join(elem_lines)}
*MATERIAL, NAME=Steel
*ELASTIC
{youngs}, {poisson}
*SOLID SECTION, ELSET=EALL, MATERIAL=Steel
*BOUNDARY
{bounds}
*STEP
*STATIC
*CLOAD
{cload}
*NODE FILE
U
*EL FILE
S
*EL PRINT, ELSET=EALL
S
*END STEP
"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")
    return destination


def mapped_deck_has_wall_cload(text: str) -> bool:
    """True when the pass-2 marker comment is present (agents: do not rely on force magnitude)."""
    return "** mapped chamber_wall Pa" in text


def write_solid_map_inp(params: dict[str, Any], destination: Path, wall_p_pa: float) -> Path:
    """Pass-1 deck plus inward CLOAD on housing-ID nodes from wall_p_pa."""
    write_solid_inp(params, destination)
    text = destination.read_text(encoding="utf-8")
    xs, _ys, _zs = _radial_stations(params)
    id_r = float(params["housing_id_mm"]) / 2.0
    ix = xs.index(id_r)
    area = float(params["key_width_mm"]) * float(params["key_length_mm"])
    force = -(float(wall_p_pa) / 1e6) * area / 4.0
    extra = ["** mapped chamber_wall Pa"] + [
        f"{_nid(ix, iy, iz)}, 1, {force}" for iy in range(2) for iz in range(2)
    ]
    needle = "*CLOAD\n"
    at = text.index(needle) + len(needle)
    node_file = text.index("*NODE FILE", at)
    destination.write_text(
        text[:node_file] + "\n".join(extra) + "\n" + text[node_file:],
        encoding="utf-8",
    )
    return destination


def _mises_from_tensor(sxx: float, syy: float, szz: float, sxy: float, syz: float, szx: float) -> float:
    """Von Mises from a 3D Cauchy tensor (CalculiX SXX..SZX order)."""
    return (
        0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2)
        + 3.0 * (sxy**2 + syz**2 + szx**2)
    ) ** 0.5


def parse_von_mises(dat_text: str) -> float:
    """Read Mises from CalculiX .dat text, else max abs float on an SXX line."""
    mises_line = None
    for line in dat_text.splitlines():
        if "Mises" in line:
            mises_line = line
    if mises_line is not None:
        numbers = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", mises_line)
        if numbers:
            return float(numbers[-1])
        raise ValueError("Mises line had no float")
    values: list[float] = []
    for line in dat_text.splitlines():
        if "SXX" in line:
            values.extend(float(n) for n in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", line))
    if not values:
        raise ValueError("no stress numbers in dat text")
    return max(abs(v) for v in values)


def parse_frd_von_mises(frd_text: str) -> float:
    """Max nodal von Mises from a CalculiX .frd STRESS block (*EL FILE, S)."""
    in_stress = False
    peak = 0.0
    found = False
    for line in frd_text.splitlines():
        if line.startswith(" -4") and "STRESS" in line:
            in_stress = True
            continue
        if in_stress and line.startswith(" -3"):
            in_stress = False
            continue
        if not in_stress or not line.startswith(" -1"):
            continue
        numbers = _floats(line[3:].strip())
        if len(numbers) < 7:
            continue
        peak = max(peak, _mises_from_tensor(*numbers[1:7]))
        found = True
    if not found:
        raise ValueError("no STRESS tensor in frd text")
    return peak


def sample_frd_von_mises(frd_text: str, probes: dict[str, list[float]]) -> dict[str, float]:
    """Nearest-node von Mises in mm for each named probe (FRD 2C coords + STRESS)."""
    coords: dict[int, tuple[float, float, float]] = {}
    stress: dict[int, float] = {}
    mode: str | None = None
    for line in frd_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("2C"):
            mode = "nodes"
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
        elif mode == "stress" and len(nums) >= 7:
            nid = int(nums[0])
            stress[nid] = _mises_from_tensor(*nums[1:7])
    if not coords or not stress:
        raise ValueError("frd missing nodes or STRESS")
    out: dict[str, float] = {}
    for name, xyz in probes.items():
        best: float | None = None
        best_d: float | None = None
        for nid, xyz_n in coords.items():
            if nid not in stress:
                continue
            dist = (xyz_n[0] - xyz[0]) ** 2 + (xyz_n[1] - xyz[1]) ** 2 + (xyz_n[2] - xyz[2]) ** 2
            if best_d is None or dist < best_d:
                best_d = dist
                best = stress[nid]
        if best is None:
            raise ValueError(f"no stressed node for {name}")
        out[name] = best
    return out


def parse_solid_von_mises(dat_path: Path, frd_path: Path) -> float:
    """Prefer .dat Mises; *EL FILE alone leaves .dat empty so fall back to .frd."""
    if dat_path.is_file():
        text = dat_path.read_text(encoding="utf-8", errors="replace")
        if text.strip():
            try:
                return parse_von_mises(text)
            except ValueError:
                pass
    if frd_path.is_file():
        return parse_frd_von_mises(frd_path.read_text(encoding="utf-8", errors="replace"))
    raise ValueError("no stress numbers in dat or frd")
