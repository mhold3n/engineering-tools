"""Phase E time quantities and multirate coupling schedules.

Agents: coupling window, solver timestep, and global analysis time are three
different clocks (R42). Participants may subcycle inside a window (R41).
This module compiles schedules only; it does not march live solvers.
"""

from __future__ import annotations

import math
from typing import Any


def _finite_positive(value: float) -> bool:
    """True for a clock value that can be divided and rounded."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def compile_multirate_schedule(
    *,
    window_dt_s: float,
    global_time_s: float,
    participants: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Compile per-participant subcycles for one coupling window.

    Fluid vs solid example. Fluid dt 0.002 inside a 0.01 window is 5
    fluid subcycles. A non-finite window or solver dt is broken before
    round is called. Window dt that is not an integer multiple of a solver
    dt is broken, with no silent rounding.
    """
    if not _finite_positive(window_dt_s):
        return {"status": "broken", "detail": "window_dt_s must be finite and positive"}
    compiled: dict[str, Any] = {}
    for name, spec in participants.items():
        dt = float(spec["dt_s"])
        if not _finite_positive(dt):
            return {"status": "broken", "detail": f"{name} dt_s must be finite and positive"}
        ratio = window_dt_s / dt
        subcycles = round(ratio)
        if abs(ratio - subcycles) > 1e-12 or subcycles < 1:
            return {
                "status": "broken",
                "detail": f"{name}: window_dt_s {window_dt_s} is not an integer multiple of dt_s {dt}",
            }
        compiled[name] = {
            "solver_dt_s": dt,
            "subcycles": int(subcycles),
            "window_dt_s": float(window_dt_s),
        }
    return {
        "status": "ok",
        "detail": "multirate",
        "window_dt_s": float(window_dt_s),
        "global_time_s": float(global_time_s),
        "participants": compiled,
    }
