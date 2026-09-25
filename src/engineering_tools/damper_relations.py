"""B-baseline point-value relations for the damper scenario.

Not FSI: shared frame, named coverage, Pa traction ratio, and optional weak-map
(pass 2) when the orchestrator sets mapped_deck_has_wall_cload / mapped_frd_exists.
"""

from __future__ import annotations

import math
from typing import Any

from .damper_params import FLUID_PROBES, REQUIRED_PROBES, SOLID_PROBES

# Key solid probes checked for finite mapped stress when weak-map is active.
_WEAK_MAP_SOLIDS = ("key_fillet", "keyway_root")


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def evaluate_relations(
    *,
    probes: dict[str, list[float]],
    state_probes: dict[str, Any],
    belt_land_traction_mpa: float,
    mapped_deck_has_wall_cload: bool = False,
    mapped_frd_exists: bool = False,
) -> list[dict[str, Any]]:
    """B relations. wall cfd.p must already be Pa. Not FSI."""
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

    weak_map_active = mapped_deck_has_wall_cload or mapped_frd_exists
    coverage_ok = True
    coverage_detail = "solid fea and fluid cfd present"
    for name in SOLID_PROBES:
        von = ((state_probes.get(name) or {}).get("fea") or {}).get("von_mises")
        if not _finite(von):
            coverage_ok = False
            coverage_detail = f"missing fea.von_mises at {name}"
            break
        if weak_map_active:
            mapped = ((state_probes.get(name) or {}).get("fea_mapped") or {}).get("von_mises")
            if not _finite(mapped):
                coverage_ok = False
                coverage_detail = f"missing fea_mapped.von_mises at {name}"
                break
    if coverage_ok:
        for name in FLUID_PROBES:
            cfd = (state_probes.get(name) or {}).get("cfd") or {}
            pressure = cfd.get("p")
            if not _finite(pressure):
                coverage_ok = False
                coverage_detail = f"missing cfd.p at {name}"
                break
            if weak_map_active:
                p_kin = cfd.get("p_kinematic")
                if not _finite(p_kin):
                    coverage_ok = False
                    coverage_detail = f"missing cfd.p_kinematic at {name}"
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

    if not weak_map_active:
        weak_ok = True
        weak_detail = "weak-map not requested"
    elif not mapped_deck_has_wall_cload or not mapped_frd_exists:
        weak_ok = False
        weak_detail = "missing solid-map deck CLOADs or solid-map.frd"
    else:
        weak_ok = True
        weak_detail = "mapped key stresses finite"
        for name in _WEAK_MAP_SOLIDS:
            mapped = ((state_probes.get(name) or {}).get("fea_mapped") or {}).get("von_mises")
            if not _finite(mapped):
                weak_ok = False
                weak_detail = f"non-finite fea_mapped.von_mises at {name}"
                break
    rows.append({"id": "weak-map", "ok": weak_ok, "detail": weak_detail})
    return rows
