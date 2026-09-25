from pathlib import Path

from engineering_tools.c_cli import parse_coupling_flags
from engineering_tools.c_contract import mm_to_m, new_session, request_capability
from engineering_tools.c_snapshot import freeze_ab_snapshot


def test_default_is_no_coupling() -> None:
    req = parse_coupling_flags(coupling=None, fsi=False)
    assert req.token is None
    assert req.status is None


def test_fsi_alias_is_c() -> None:
    assert parse_coupling_flags(coupling=None, fsi=True).token == "c"
    assert parse_coupling_flags(coupling="c", fsi=False).token == "c"
    assert parse_coupling_flags(coupling="c", fsi=True).token == "c"


def test_unknown_coupling_is_broken() -> None:
    req = parse_coupling_flags(coupling="thermal", fsi=False)
    assert req.status == "broken"
    assert req.token is None


def test_conflicting_flags_are_broken() -> None:
    req = parse_coupling_flags(coupling="c", fsi=True)
    # --fsi with --coupling c is not a conflict
    assert req.token == "c"
    bad = parse_coupling_flags(coupling="nope", fsi=True)
    assert bad.status == "broken"


def test_mm_to_m_keeps_three_components() -> None:
    assert mm_to_m([25.0, 0.0, 0.0]) == [0.025, 0.0, 0.0]


def test_new_session_records_backend_and_empty_steps() -> None:
    session = new_session(scenario="damper-keyway", backend="precice")
    assert session["backend"] == "precice"
    assert session["steps"] == []
    assert session["evaluated"] is True


def test_unavailable_capability_is_missing() -> None:
    row = request_capability("checkpoint")
    assert row["status"] == "missing"


def test_unknown_capability_is_broken() -> None:
    row = request_capability("not-a-c-op")
    assert row["status"] == "broken"


def test_freeze_ab_snapshot_copies_and_digests(tmp_path: Path) -> None:
    src = tmp_path / "ab"
    src.mkdir()
    (src / "product-state.json").write_text('{"coupling":"weak-map"}\n', encoding="utf-8")
    (src / "scenario-report.json").write_text('{"a_ok":true,"b_ok":true}\n', encoding="utf-8")
    dest = tmp_path / "snap"
    digest = freeze_ab_snapshot(src, dest)
    assert len(digest) == 64
    assert (dest / "product-state.json").read_text(encoding="utf-8") == (src / "product-state.json").read_text(encoding="utf-8")
    (dest / "product-state.json").write_text("mutated", encoding="utf-8")
    assert (src / "product-state.json").read_text(encoding="utf-8") == '{"coupling":"weak-map"}\n'
