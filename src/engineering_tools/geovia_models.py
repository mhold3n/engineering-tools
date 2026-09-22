"""First-party GEOVIA stand-in models (toy Alpha probes, not production solvers)."""

from __future__ import annotations

from typing import Any


def mine_schedule(blocks: list[dict[str, float]], periods: int = 2) -> dict[str, Any]:
    """
    Assign each mining block to the earliest period that still has capacity.

    Toy model: each period has unit capacity 1.0; blocks have tonnage.
    """
    if periods < 1:
        raise ValueError("periods must be >= 1")
    remaining = [1.0] * periods
    assignment: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        tonnage = float(block.get("tonnage", 0.0))
        placed = False
        for period, capacity in enumerate(remaining):
            if tonnage <= capacity + 1e-12:
                remaining[period] = capacity - tonnage
                assignment.append({"block": index, "period": period, "tonnage": tonnage})
                placed = True
                break
        if not placed:
            assignment.append({"block": index, "period": None, "tonnage": tonnage})
    return {
        "periods": periods,
        "assignment": assignment,
        "scheduled": sum(1 for row in assignment if row["period"] is not None),
        "objective": float(sum(row["tonnage"] for row in assignment if row["period"] is not None)),
    }


def pit_optimize(blocks: list[dict[str, float]], cutoff: float = 0.0) -> dict[str, Any]:
    """
    Select blocks with value above cutoff (toy pit shell stand-in).

    Each block supplies value and cost; keep when value - cost >= cutoff.
    """
    selected: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        value = float(block.get("value", 0.0))
        cost = float(block.get("cost", 0.0))
        surplus = value - cost
        if surplus >= cutoff:
            selected.append({"block": index, "surplus": surplus})
    return {
        "cutoff": cutoff,
        "selected": selected,
        "count": len(selected),
        "objective": float(sum(row["surplus"] for row in selected)),
    }
