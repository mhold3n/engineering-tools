"""C orchestration contract helpers.

Comments for other agents: CAD frame identity is authoritative for geometry;
this module never stores millimeters in C-side field values. Unlisted capability
names return broken; names marked unavailable return missing (fail-closed).
"""

from __future__ import annotations

from typing import Any

CAPABILITIES: dict[str, str] = {
    "session": "implemented",
    "precice": "implemented",
    "checkpoint": "unavailable",
    "rollback": "unavailable",
    "multirate": "unavailable",
    "thermal": "unavailable",
    "cad-in-loop": "unavailable",
    "meshing-adapter": "unavailable",
    "assemblies": "unavailable",
}

CAD_FRAME_ID = "damper-cad"


def mm_to_m(xyz_mm: list[float]) -> list[float]:
    """Convert a 3-vector from millimeters to meters for C field payloads."""
    return [float(xyz_mm[0]) / 1000.0, float(xyz_mm[1]) / 1000.0, float(xyz_mm[2]) / 1000.0]


def request_capability(name: str) -> dict[str, Any]:
    """Resolve a named C capability; unknown → broken, unavailable → missing."""
    state = CAPABILITIES.get(name)
    if state is None:
        return {"status": "broken", "detail": f"unknown capability: {name}"}
    if state == "unavailable":
        return {"status": "missing", "detail": f"specified/unavailable: {name}"}
    return {"status": "ok", "detail": name}


def new_session(*, scenario: str, backend: str) -> dict[str, Any]:
    """Create an empty evaluated session shell for the given scenario and backend."""
    return {
        "schema_version": 1,
        "scenario": scenario,
        "backend": backend,
        "frame_id": CAD_FRAME_ID,
        "evaluated": True,
        "status": "ok",
        "participants": [],
        "interfaces": [],
        "probes": {},
        "parity": [],
        "snapshot_digest": None,
        "steps": [],
        "c_ok": False,
    }
