"""Tests for first-party GEOVIA toy models and their hello probes."""

from __future__ import annotations

from engineering_tools.geovia_models import mine_schedule, pit_optimize
from engineering_tools.hello_probes import probe_mine_scheduling, probe_pit_optimization


def test_mine_schedule_assigns_within_capacity() -> None:
    result = mine_schedule([{"tonnage": 0.6}, {"tonnage": 0.6}, {"tonnage": 0.6}], periods=2)
    assert result["scheduled"] == 2
    assert result["assignment"][2]["period"] is None
    assert result["objective"] == 1.2


def test_pit_optimize_selects_positive_surplus() -> None:
    result = pit_optimize(
        [{"value": 10, "cost": 3}, {"value": 2, "cost": 5}, {"value": 8, "cost": 1}],
        cutoff=0.0,
    )
    assert result["count"] == 2
    assert result["objective"] == 14.0


def test_mine_scheduling_probe_ok() -> None:
    outcome = probe_mine_scheduling()
    assert outcome["status"] == "ok"
    assert outcome["id"] == "first-party-mine-scheduling-model"


def test_pit_optimization_probe_ok() -> None:
    outcome = probe_pit_optimization()
    assert outcome["status"] == "ok"
    assert outcome["id"] == "first-party-pit-optimization-model"
