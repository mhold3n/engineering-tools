"""CalculiX deck for the damper scenario (one C3D8 brick, belt-land CLOAD)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def write_solid_inp(params: dict[str, Any], destination: Path) -> Path:
    """Write a hello_beam-style C3D8 deck; load scale follows belt_land_traction_mpa."""
    load = float(params["belt_land_traction_mpa"]) * 25.0
    youngs = float(params["youngs_mpa"])
    poisson = float(params["poisson"])
    text = f"""** engineering-tools damper-keyway solid (MIT sample deck)
*HEADING
damper-keyway solid
*NODE
1, 0.000000000000e+00, 0.000000000000e+00, 0.000000000000e+00
2, 1.000000000000e+01, 0.000000000000e+00, 0.000000000000e+00
3, 1.000000000000e+01, 1.000000000000e+00, 0.000000000000e+00
4, 0.000000000000e+00, 1.000000000000e+00, 0.000000000000e+00
5, 0.000000000000e+00, 0.000000000000e+00, 1.000000000000e+00
6, 1.000000000000e+01, 0.000000000000e+00, 1.000000000000e+00
7, 1.000000000000e+01, 1.000000000000e+00, 1.000000000000e+00
8, 0.000000000000e+00, 1.000000000000e+00, 1.000000000000e+00
*ELEMENT, TYPE=C3D8, ELSET=EALL
1, 1, 2, 3, 4, 5, 6, 7, 8
*MATERIAL, NAME=Steel
*ELASTIC
{youngs}, {poisson}
*SOLID SECTION, ELSET=EALL, MATERIAL=Steel
*BOUNDARY
1, 1, 3
4, 1, 3
5, 1, 3
8, 1, 3
*STEP
*STATIC
*CLOAD
2, 1, {load}
3, 1, {load}
6, 1, {load}
7, 1, {load}
*NODE FILE
U
*EL FILE
S
*END STEP
"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")
    return destination


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
