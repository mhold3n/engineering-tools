"""Phase E time/state/checkpoint contract (U6). No live solvers."""

from engineering_tools.e_state import (
    FakeHistoryParticipant,
    participant_state,
    request_topology_mutation,
)
from engineering_tools.e_time import compile_multirate_schedule


def test_failed_coupling_iteration_restores_window_start_state() -> None:
    """Implicit iteration that fails must return to the window-start checkpoint."""
    part = FakeHistoryParticipant(participant_id="Solid", topology_version=3)
    part.begin_window(window_index=2, time_s=0.04)
    window_start = part.snapshot()
    part.advance_iteration(plastic_increment=0.25)
    assert part.state["internal_state"]["plastic_strain"] == 0.25
    restored = part.restore_window_start()
    assert restored["internal_state"]["plastic_strain"] == window_start["internal_state"]["plastic_strain"]
    assert restored["time_s"] == window_start["time_s"]
    assert restored["window_index"] == 2
    assert restored["iteration"] == 0
    assert restored["checkpoint_id"] == window_start["checkpoint_id"]
    assert restored["topology_version"] == 3
    assert restored["internal_state_provenance"].startswith("restored:")


def test_irreversible_participant_does_not_double_accumulate_across_iterations() -> None:
    """Checkpoint/restore: two implicit tries of +1.0 must not leave +2.0."""
    part = FakeHistoryParticipant(participant_id="Solid")
    part.begin_window(window_index=0, time_s=0.0)
    part.advance_iteration(plastic_increment=1.0)
    part.restore_window_start()
    part.advance_iteration(plastic_increment=1.0)
    assert part.state["internal_state"]["plastic_strain"] == 1.0
    assert part.state["iteration"] == 1


def test_multirate_schedule_compiles_fluid_subcycles_vs_solid_window() -> None:
    """Coupling window, solver dt, and global time stay distinct (R41/R42)."""
    schedule = compile_multirate_schedule(
        window_dt_s=0.01,
        global_time_s=0.04,
        participants={
            "Fluid": {"dt_s": 0.002},
            "Solid": {"dt_s": 0.01},
        },
    )
    assert schedule["status"] == "ok"
    assert schedule["window_dt_s"] == 0.01
    assert schedule["global_time_s"] == 0.04
    assert schedule["participants"]["Fluid"]["subcycles"] == 5
    assert schedule["participants"]["Fluid"]["solver_dt_s"] == 0.002
    assert schedule["participants"]["Solid"]["subcycles"] == 1
    assert schedule["participants"]["Solid"]["solver_dt_s"] == 0.01
    assert schedule["window_dt_s"] != schedule["participants"]["Fluid"]["solver_dt_s"]
    assert schedule["global_time_s"] != schedule["window_dt_s"]


def test_unsupported_topology_mutation_fails_closed() -> None:
    """R48/R49: unavailable mutation is missing/broken, never treated as fixed topology."""
    state = participant_state(
        participant_id="Solid",
        time_s=0.0,
        window_index=0,
        iteration=0,
        topology_version=1,
    )
    for kind in ("crack_propagation", "erosion", "ablation", "phase_boundary_mutation"):
        got = request_topology_mutation(state, kind=kind, adapter_id="calculix")
        assert got["status"] in {"missing", "broken"}
        assert state["topology_version"] == 1
    unknown = request_topology_mutation(state, kind="not-a-mutation", adapter_id="calculix")
    assert unknown["status"] == "broken"
    assert state["topology_version"] == 1
    no_adapter = request_topology_mutation(state, kind="crack_propagation", adapter_id="not-a-solver")
    assert no_adapter["status"] == "broken"
    assert state["topology_version"] == 1
