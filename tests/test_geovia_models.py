"""Tests for first-party GEOVIA toy models and their hello probes."""

from __future__ import annotations

from engineering_tools.geovia_models import grade_above_cutoff, mine_schedule, pit_optimize
from engineering_tools.hello_probes import probe_mine_scheduling, probe_pit_optimization
from engineering_tools.product_probes import PRODUCT_PROBES


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


def test_grade_screen_keeps_samples_at_cutoff() -> None:
    result = grade_above_cutoff([{"grade": 2.0}, {"grade": 0.4}], cutoff=1.0)
    assert result["count"] == 1
    assert result["mean_grade"] == 2.0


def test_geovia_product_probes_cover_from_numeric_models() -> None:
    for probe_id in (
        "geovia-minesched-capability",
        "geovia-whittle-capability",
        "geovia-surpac-capability",
    ):
        outcome = PRODUCT_PROBES[probe_id]({})
        assert outcome["status"] == "covered"
