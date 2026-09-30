"""Phase E time quantities and multirate coupling schedules.

Agents: coupling window, solver timestep, and global analysis time are three
different clocks (R42). Participants may subcycle inside a window (R41).
This module compiles schedules only; it does not march live solvers.
"""

from __future__ import annotations

from typing import Any


def compile_multirate_schedule(
    *,
    window_dt_s: float,
    global_time_s: float,
    participants: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Compile per-participant subcycles for one coupling window.

    Fluid vs solid: e.g. fluid dt 0.002 inside a 0.01 solid/window step → 5
    fluid subcycles. Window dt that is not an integer multiple of a solver dt
    is broken (no silent rounding).
    """
    if window_dt_s <= 0:
        return {"status": "broken", "detail": "window_dt_s must be positive"}
    compiled: dict[str, Any] = {}
    for name, spec in participants.items():
        dt = float(spec["dt_s"])
        if dt <= 0:
            return {"status": "broken", "detail": f"{name} dt_s must be positive"}
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
