"""B-baseline point-value relations for the damper scenario.

Not FSI: only checks shared frame, named coverage, and a loose traction ratio.
"""

from __future__ import annotations

import math
from typing import Any

from .damper_params import FLUID_PROBES, REQUIRED_PROBES, SOLID_PROBES


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def evaluate_relations(
    *,
    probes: dict[str, list[float]],
    state_probes: dict[str, Any],
    belt_land_traction_mpa: float,
) -> list[dict[str, Any]]:
    """Return shared-frame, named-coverage, and order-of-magnitude-traction rows."""
    rows: list[dict[str, Any]] = []
    frame_ok = True
    frame_detail = "xyz match probes.json"
    for name in REQUIRED_PROBES:
        expected = probes.get(name)
        got = (state_probes.get(name) or {}).get("xyz_mm")
        if expected is None or got is None or list(map(float, got)) != list(map(float, expected)):
            frame_ok = False
            frame_detail = f"xyz mismatch at {name}"
            break
    rows.append({"id": "shared-frame", "ok": frame_ok, "detail": frame_detail})

    coverage_ok = True
    coverage_detail = "solid fea and fluid cfd present"
    for name in SOLID_PROBES:
        von = ((state_probes.get(name) or {}).get("fea") or {}).get("von_mises")
        if not _finite(von):
            coverage_ok = False
            coverage_detail = f"missing fea.von_mises at {name}"
            break
    if coverage_ok:
        for name in FLUID_PROBES:
            pressure = ((state_probes.get(name) or {}).get("cfd") or {}).get("p")
            if not _finite(pressure):
                coverage_ok = False
                coverage_detail = f"missing cfd.p at {name}"
                break
    rows.append({"id": "named-coverage", "ok": coverage_ok, "detail": coverage_detail})

    wall = ((state_probes.get("chamber_wall") or {}).get("cfd") or {}).get("p")
    traction_pa = abs(float(belt_land_traction_mpa)) * 1e6
    if not _finite(wall) or traction_pa == 0.0:
        traction_ok = False
        traction_detail = "cannot form p/traction ratio"
    else:
        ratio = abs(float(wall)) / traction_pa
        traction_ok = 1e-6 <= ratio <= 1e6
        traction_detail = f"ratio={ratio}"
    rows.append({"id": "order-of-magnitude-traction", "ok": traction_ok, "detail": traction_detail})
    return rows
