"""Phase E numerical sensitivity: mesh/time refinement comparison.

Agents: a finer mesh is not automatically high-fidelity. Compare declared
engineering outputs and record relative difference vs tolerance.
"""

from __future__ import annotations

from typing import Any

DEFAULT_QUANTITIES = (
    "peak_wall_pressure",
    "integrated_wall_force",
    "peak_structural_displacement",
    "critical_von_mises",
    "wall_temperature",
    "integrated_heat_transfer",
)


def compare_refinement(
    baseline: dict[str, float],
    refined: dict[str, float],
    *,
    relative_tolerance: float = 0.2,
) -> dict[str, Any]:
    """Compare two discretization levels. Missing keys are broken."""
    rows = []
    ok = True
    for name in DEFAULT_QUANTITIES:
        if name not in baseline or name not in refined:
            return {"status": "broken", "detail": f"missing quantity {name}", "rows": rows, "ok": False}
        b = float(baseline[name])
        r = float(refined[name])
        denom = max(abs(b), abs(r), 1e-30)
        rel = abs(r - b) / denom
        row_ok = rel <= float(relative_tolerance)
        ok = ok and row_ok
        rows.append(
            {
                "id": name,
                "baseline": b,
                "refined": r,
                "relative_difference": rel,
                "tolerance": float(relative_tolerance),
                "ok": row_ok,
            }
        )
    return {"status": "ok" if ok else "broken", "ok": ok, "rows": rows, "detail": "refinement"}
