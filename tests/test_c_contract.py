from pathlib import Path

import pytest

from engineering_tools.c_cli import parse_coupling_flags
from engineering_tools.c_backend_precice import default_policy, generate_precice_config
from engineering_tools.c_contract import mm_to_m, new_session, request_capability
from engineering_tools.c_parity import in_band, load_c_fsi_bands, mpa_to_pa
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


def test_in_band_abs_rel() -> None:
    assert in_band(10.0, 10.0, 0.0, 0.0) is True
    assert in_band(12.0, 10.0, 1.0, 0.0) is False
    assert in_band(12.0, 10.0, 1.0, 0.2) is True


def test_mpa_to_pa() -> None:
    assert mpa_to_pa(2.0) == 2.0e6


def test_packaged_c_fsi_bands_have_required_keys() -> None:
    bands = load_c_fsi_bands()
    assert bands["motion_floor_m"] > 0
    assert "housing.wall.pressure" in bands["parity"]
    assert bands["parity"]["housing.wall.pressure"]["abs"] >= 0
    assert "housing.wall.displacement" not in bands["parity"]


def test_generated_xml_uses_policy_names_not_a_checked_in_file() -> None:
    policy = default_policy()
    xml = generate_precice_config(policy)
    assert "<participant name=\"Solid\">" in xml or 'name="Solid"' in xml
    assert "Displacement" in xml
    assert "Traction" in xml
    policy["participants"][0]["name"] = "Steel"
    xml2 = generate_precice_config(policy)
    assert "Steel" in xml2
    assert "Steel" not in xml


def _participant_block(xml: str, name: str) -> str:
    marker = f'name="{name}"'
    start = xml.index(f"<participant {marker}")
    end = xml.index("</participant>", start)
    return xml[start:end]


def test_precice_participant_read_write_matches_c_policy() -> None:
    policy = default_policy()
    xml = generate_precice_config(policy)
    solid = _participant_block(xml, "Solid")
    fluid = _participant_block(xml, "Fluid")
    assert 'write-data name="Displacement"' in solid
    assert 'read-data name="Traction"' in solid
    assert 'write-data name="Traction"' not in solid
    assert 'write-data name="Displacement"' not in fluid
    assert 'write-data name="Traction"' in fluid
    assert 'read-data name="Displacement"' in fluid


def test_precice_exchanges_match_c_policy() -> None:
    policy = default_policy()
    xml = generate_precice_config(policy)
    assert (
        f'exchange data="Traction" mesh="interface" from="Fluid" to="Solid"' in xml
    )
    assert (
        f'exchange data="Displacement" mesh="interface" from="Solid" to="Fluid"'
        in xml
    )


def _serial_implicit_scheme_block(xml: str) -> str:
    start = xml.index("<coupling-scheme:serial-implicit>")
    end = xml.index("</coupling-scheme:serial-implicit>", start)
    return xml[start:end]


def test_max_iterations_not_encoded_as_max_time() -> None:
    policy = default_policy()
    xml = generate_precice_config(policy)
    bogus = float(policy["time_window"]) * int(policy["max_iterations"])
    assert "<max-time" not in xml
    assert f'<max-time value="{bogus}"' not in xml
    assert "coupling-scheme:parallel-explicit" not in xml
    scheme = _serial_implicit_scheme_block(xml)
    assert 'exchange data="Traction"' in scheme
    assert 'exchange data="Displacement"' in scheme
    assert f'<max-iterations value="{policy["max_iterations"]}"' in scheme
    assert f'<time-window-size value="{policy["time_window"]}"' in scheme


def test_generate_precice_config_is_independent_of_on_disk_xml(tmp_path: Path) -> None:
    policy = default_policy()
    stale = tmp_path / "precice-config.xml"
    stale.write_text("<stale-participant name=\"CheckedIn\"/>", encoding="utf-8")
    xml_before = generate_precice_config(policy)
    assert "CheckedIn" not in xml_before
    stale.unlink()
    xml_after = generate_precice_config(policy)
    assert xml_after == xml_before


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


def test_freeze_ab_snapshot_missing_json_raises(tmp_path: Path) -> None:
    """A/B freeze fails closed when either JSON pin is absent.

    Agents: FileNotFoundError is the contract the façade maps to C broken.
    An empty directory is not a snapshot.
    """
    src = tmp_path / "ab"
    src.mkdir()
    with pytest.raises(FileNotFoundError):
        freeze_ab_snapshot(src, tmp_path / "snap")
