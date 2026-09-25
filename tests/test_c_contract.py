from engineering_tools.c_cli import parse_coupling_flags
from engineering_tools.c_contract import mm_to_m, new_session, request_capability


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
