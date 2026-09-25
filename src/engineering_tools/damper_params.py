"""Pinned damper scenario parameters and probe coordinates.

Comments are for other agents: this module is the source of truth for XYZ.
The FreeCAD script must not be allowed to drift the B shared-frame check;
the orchestrator overwrites probes.json from probes_from_params.
"""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from typing import Any

REQUIRED_PROBES: tuple[str, ...] = (
    "key_fillet",
    "keyway_root",
    "belt_land",
    "chamber_center",
    "chamber_wall",
)
SOLID_PROBES: tuple[str, ...] = ("key_fillet", "keyway_root", "belt_land")
FLUID_PROBES: tuple[str, ...] = ("chamber_center", "chamber_wall")


def load_params() -> dict[str, Any]:
    """Load the packaged damper-params.json pin."""
    root = resources.files("engineering_tools")
    text = (root / "data" / "damper" / "damper-params.json").read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("damper-params.json must be an object")
    return data


def params_digest(params: dict[str, Any]) -> str:
    """SHA-256 of canonical JSON so product-state can pin the run."""
    payload = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def probes_from_params(params: dict[str, Any]) -> dict[str, list[float]]:
    """Named probe XYZ in mm. Origin at chamber center, housing axis +Z.

    key_fillet: shaft OD at the key (+X, +Y edge).
    keyway_root: bottom of the housing slot (+X).
    belt_land: housing OD at z=0.
    chamber_center: origin.
    chamber_wall: inner housing wall opposite the key (−X) so it is not the slot.
    """
    shaft_r = float(params["shaft_od_mm"]) / 2.0
    housing_id_r = float(params["housing_id_mm"]) / 2.0
    housing_od_r = float(params["housing_od_mm"]) / 2.0
    hy = float(params["key_width_mm"]) / 2.0
    depth = float(params["keyway_depth_mm"])
    return {
        "key_fillet": [shaft_r, hy, 0.0],
        "keyway_root": [housing_id_r + depth, 0.0, 0.0],
        "belt_land": [housing_od_r, 0.0, 0.0],
        "chamber_center": [0.0, 0.0, 0.0],
        "chamber_wall": [-housing_id_r, 0.0, 0.0],
    }
