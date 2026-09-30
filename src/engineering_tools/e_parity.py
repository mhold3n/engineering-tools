"""Phase E fixture bands for live CAD-mapped probes.

Agents: first Ubuntu green run is calibration. Tighten parity in this JSON
with provenance; a later clean --coupling e is acceptance. Zeros vs finite
pressure fail in_band.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from engineering_tools.c_parity import in_band


def load_e_fsi_bands() -> dict[str, Any]:
    """Load packaged E live bands from data/e-demo/e-fsi-bands.json."""
    root = resources.files("engineering_tools")
    text = (root / "data" / "e-demo" / "e-fsi-bands.json").read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("e-fsi-bands.json must be an object")
    return data


def probe_in_band(value: float, target: float, band: dict[str, Any]) -> bool:
    """Abs+rel check used by the live façade."""
    return in_band(value, target, float(band["abs"]), float(band["rel"]))
