"""Break campaign and coupled-point succession.

Agents: do not loosen an assertion to match today's acceptance.
Do not add a guard probe while any current row's observed field differs
from required. The coupled test walks run_e_session with the PATH mock.
A mock session is not an engineering edge.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from e_break_campaign import BREAK_PROBES, COUPLED_FIELDS, DEBUG_KEYS, run_break_campaign, run_coupled_campaign
from test_e_live import _e_frd, _e_live_tools


def test_break_campaign_records_each_probe_and_matches_required(tmp_path: Path) -> None:
    record_path = tmp_path / "break-record.json"
    records = run_break_campaign(record_path)
    saved = json.loads(record_path.read_text(encoding="utf-8"))
    assert saved == records
    assert [row["id"] for row in records] == [probe["id"] for probe in BREAK_PROBES]
    for row in records:
        assert set(DEBUG_KEYS) <= set(row)
        assert row["axis"] in {"dimension", "magnitude", "transient"}
        assert isinstance(row["site"], str) and ".py:" in row["site"]
        assert row["call"]
        if row["observed"] == "raised":
            assert row["exception_type"]
            assert row["traceback"]
        assert row["observed"] == row["required"]
        if row["id"] == "negative-element-size":
            assert row["evidence"]["geo_exists"] is False


def test_coupled_points_record_session_fields_and_a_mock_is_not_an_engineering_edge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frd = tmp_path / "seed.frd"
    _e_frd(frd)
    _e_live_tools(tmp_path, monkeypatch, solid_frd=frd)
    points = [
        {"id": "two-windows", "h_max": 0.012, "physical_time_s": 0.02, "time_window_s": 0.01},
        {"id": "uneven-window", "h_max": 0.012, "physical_time_s": 0.02, "time_window_s": 0.003},
    ]
    record_path = tmp_path / "coupled-record.json"
    report = run_coupled_campaign(record_path, points)
    saved = json.loads(record_path.read_text(encoding="utf-8"))
    assert saved == report
    assert [row["id"] for row in report["points"]] == ["two-windows", "uneven-window"]
    directories = [Path(row["directory"]) for row in report["points"]]
    assert directories[0] != directories[1]
    assert all((path / "e-session.json").is_file() for path in directories)
    first, second = report["points"]
    assert first["status"] == "mock"
    assert first["e_ok"] is False
    assert first["engineering"] is False
    assert isinstance(first["probes"], dict)
    assert isinstance(first["completed_windows"], int)
    assert "mapping_error" in first
    for field in COUPLED_FIELDS:
        assert field in first and field in second
    assert second["status"] == "broken"
    assert second["e_ok"] is False
    assert second["engineering"] is False
    assert second["probes"] is None
    assert report["edges"]
    assert all(edge["engineering"] is False for edge in report["edges"])
    assert "probes" in report["edges"][0]["changed"]
