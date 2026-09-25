"""C-FSI parity helpers: abs+rel band check and packaged acceptance bands.

For agents: `in_band` is the single comparison primitive for scalar parity.
`load_c_fsi_bands` reads `data/damper/c-fsi-bands.json` (same importlib.resources
pattern as `damper_params.load_a_bands`). Displacement uses `motion_floor_m` only;
it is intentionally absent from the `parity` map in the JSON pin.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any


def in_band(c: float, b: float, abs_tol: float, rel_tol: float) -> bool:
    """True iff |c - b| <= abs_tol + rel_tol * |b|."""
    return abs(float(c) - float(b)) <= float(abs_tol) + float(rel_tol) * abs(float(b))


def mpa_to_pa(mpa: float) -> float:
    """Convert megapascals to pascals for solid stress parity."""
    return float(mpa) * 1.0e6


def load_c_fsi_bands() -> dict[str, Any]:
    """Load packaged C-FSI parity bands and motion floor from c-fsi-bands.json."""
    root = resources.files("engineering_tools")
    text = (root / "data" / "damper" / "c-fsi-bands.json").read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("c-fsi-bands.json must be an object")
    return data
