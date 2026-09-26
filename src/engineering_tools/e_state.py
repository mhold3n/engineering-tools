"""Phase E participant time/state and checkpoint/restore.

Agents: solver-owned history lives in internal_state. Implicit coupling must
checkpoint at window start and restore before each reevaluation (R43/R44).
Do not let plasticity/damage/creep accumulate across failed iterations.
Topology mutation is requested here; if unavailable, fail closed (R48/R49).
Never treat a refused mutation as "fixed topology, proceed".
"""

from __future__ import annotations

import copy
from typing import Any

from engineering_tools.e_capabilities import request_capability

# Specified first-shipment mutations that remain unavailable until a live
# remesh/topology path exists (plan Q5 / R48).
SPECIFIED_TOPOLOGY_MUTATIONS = frozenset(
    {
        "crack_propagation",
        "erosion",
        "ablation",
        "phase_boundary_mutation",
        "remesh",
    }
)


def participant_state(
    *,
    participant_id: str,
    time_s: float = 0.0,
    window_index: int = 0,
    iteration: int = 0,
    checkpoint_id: str | None = None,
    topology_version: int = 1,
    internal_state: dict[str, Any] | None = None,
    internal_state_provenance: str = "initial",
) -> dict[str, Any]:
    """First-class participant state (R40). Distinct from global analysis time."""
    return {
        "participant_id": participant_id,
        "time_s": float(time_s),
        "window_index": int(window_index),
        "iteration": int(iteration),
        "checkpoint_id": checkpoint_id,
        "topology_version": int(topology_version),
        "internal_state": copy.deepcopy(internal_state or {}),
        "internal_state_provenance": internal_state_provenance,
    }


def checkpoint_state(state: dict[str, Any], *, checkpoint_id: str) -> dict[str, Any]:
    """Immutable snapshot used for window-start restore."""
    snap = copy.deepcopy(state)
    snap["checkpoint_id"] = checkpoint_id
    snap["internal_state_provenance"] = f"checkpoint:{checkpoint_id}"
    return snap


def restore_state(checkpoint: dict[str, Any]) -> dict[str, Any]:
    """Return a working copy of a checkpoint (iteration reset to 0)."""
    restored = copy.deepcopy(checkpoint)
    restored["iteration"] = 0
    cid = checkpoint.get("checkpoint_id")
    restored["internal_state_provenance"] = f"restored:{cid}"
    return restored


def request_topology_mutation(
    state: dict[str, Any],
    *,
    kind: str,
    adapter_id: str,
) -> dict[str, Any]:
    """Ask for a topology-change event. Does not mutate topology_version on failure.

    R47: the request is a described event (kind + current topology_version).
    R48/R49: specified-unavailable or unknown requests fail closed. Status is
    missing when the adapter advertises no topology_change; broken when the
    adapter or mutation kind is unknown. Callers must not fall back to a
    fixed-topology advance.
    """
    if kind not in SPECIFIED_TOPOLOGY_MUTATIONS:
        return {
            "status": "broken",
            "detail": f"unknown topology mutation kind: {kind}",
            "kind": kind,
            "source_topology_version": state.get("topology_version"),
            "lineage": [],
        }
    cap = request_capability(adapter_id, "topology_change", True)
    if cap["status"] != "ok":
        return {
            "status": cap["status"],
            "detail": cap["detail"],
            "kind": kind,
            "source_topology_version": state.get("topology_version"),
            "lineage": [],
        }
    return {
        "status": "ok",
        "detail": f"{kind}@{adapter_id}",
        "kind": kind,
        "source_topology_version": state.get("topology_version"),
        "lineage": [],
    }


class FakeHistoryParticipant:
    """Irreversible fake participant for coupling-iteration proofs (AE11).

    Agents: plastic_strain here stands in for any history variable. Call
    begin_window once per coupling window; restore_window_start after a
    failed implicit iteration before advancing again.
    """

    def __init__(self, *, participant_id: str, topology_version: int = 1) -> None:
        self.state = participant_state(
            participant_id=participant_id,
            topology_version=topology_version,
            internal_state={"plastic_strain": 0.0},
            internal_state_provenance="initial",
        )
        self._window_checkpoint: dict[str, Any] | None = None

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.state)

    def begin_window(self, *, window_index: int, time_s: float) -> dict[str, Any]:
        """Mark coupling-window start; store the restore point (R42/R43)."""
        self.state["window_index"] = int(window_index)
        self.state["time_s"] = float(time_s)
        self.state["iteration"] = 0
        cid = f"{self.state['participant_id']}:w{window_index}:t{time_s}"
        self.state["checkpoint_id"] = cid
        self.state["internal_state_provenance"] = f"checkpoint:{cid}"
        self._window_checkpoint = checkpoint_state(self.state, checkpoint_id=cid)
        return self.snapshot()

    def advance_iteration(self, *, plastic_increment: float) -> dict[str, Any]:
        """One implicit coupling try. Mutates irreversible internal state."""
        if self._window_checkpoint is None:
            raise RuntimeError("begin_window required before advance_iteration")
        self.state["iteration"] = int(self.state["iteration"]) + 1
        strain = float(self.state["internal_state"].get("plastic_strain") or 0.0)
        self.state["internal_state"]["plastic_strain"] = strain + float(plastic_increment)
        self.state["internal_state_provenance"] = (
            f"iteration:{self.state['iteration']}@{self.state['checkpoint_id']}"
        )
        return self.snapshot()

    def restore_window_start(self) -> dict[str, Any]:
        """Discard the failed try; restore window-start participant state."""
        if self._window_checkpoint is None:
            raise RuntimeError("begin_window required before restore_window_start")
        self.state = restore_state(self._window_checkpoint)
        return self.snapshot()
