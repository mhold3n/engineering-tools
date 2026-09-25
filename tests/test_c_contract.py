from pathlib import Path

import pytest

from engineering_tools.c_cli import parse_coupling_flags
from engineering_tools.c_backend_precice import (
    default_policy,
    find_precice,
    generate_precice_config,
)
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
    # mesh= is required: preCICE binds each read/write to a mesh, not a bare name.
    assert 'write-data name="Displacement" mesh="' in solid
    assert 'read-data name="Traction" mesh="' in solid
    assert 'write-data name="Traction"' not in solid
    assert 'write-data name="Displacement"' not in fluid
    assert 'write-data name="Traction" mesh="' in fluid
    assert 'read-data name="Displacement" mesh="' in fluid
    assert 'use-mesh name="interface" provide="yes"' in solid
    assert 'use-mesh name="interface" from="Solid"' in fluid


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
    """Iteration cap and the time horizon are different preCICE knobs.

    Agents: time_window * max_iterations must not be written as max-time.
    max-iterations is the implicit loop inside one window. The scheme also
    needs max-time or max-time-windows as the coupling horizon.
    """
    policy = default_policy()
    # Horizon is its own policy field. Missing means the generator has nothing
    # real to emit, which is the failure this test is here to catch.
    assert policy.get("max_time_windows") not in (
        None,
        policy["time_window"] * policy["max_iterations"],
    )
    xml = generate_precice_config(policy)
    bogus = float(policy["time_window"]) * int(policy["max_iterations"])
    assert f'<max-time value="{bogus}"' not in xml
    assert f'<max-time-windows value="{bogus}"' not in xml
    assert "coupling-scheme:parallel-explicit" not in xml
    scheme = _serial_implicit_scheme_block(xml)
    assert 'exchange data="Traction"' in scheme
    assert 'exchange data="Displacement"' in scheme
    assert f'<max-iterations value="{policy["max_iterations"]}"' in scheme
    assert f'<time-window-size value="{policy["time_window"]}"' in scheme
    assert f'<max-time-windows value="{policy["max_time_windows"]}"' in scheme
    assert "relative-convergence-measure" in scheme


def test_generated_xml_is_precice2_config_not_invented_solver_tags() -> None:
    """Policy becomes a config participants can load, not a fake driver script.

    Agents: `<solver:calculix/>` is not a preCICE element. CalculiX and
    OpenFOAM are the participants; they read this XML. data:vector names the
    interface fields. m2n is how those participants connect. mapping places
    values between the provided mesh and the received mesh.
    """
    xml = generate_precice_config(default_policy())
    assert '<data:vector name="Displacement"' in xml
    assert '<data:vector name="Traction"' in xml
    assert "m2n:sockets" in xml
    assert "mapping:nearest-neighbor" in xml
    # `<solver-interface>` is the preCICE 2 wrapper. `<solver:calculix/>` is not.
    without_v2_wrapper = xml.replace("solver-interface", "precice-root")
    assert "<solver:" not in without_v2_wrapper
    assert "provide-mesh" in xml or 'provide="yes"' in xml
    assert "receive-mesh" in xml or 'from="' in xml


def test_precice_v2_solver_interface_dimensions_m2n_and_mapping() -> None:
    """XML matches the v2 tutorial shape CalculiX and OpenFOAM adapters load.

    Agents: preCICE 2 (tutorials tag v202211.0, perpendicular-flap and
    elastic-tube-3d) wraps data, meshes, participants, m2n, and the scheme
    in `<solver-interface dimensions="N">`. That attribute is the mesh
    dimension; a `dimensions` attribute on `<mesh>` is unknown and the v2
    parser aborts. m2n uses `from`/`to` (v3 renamed those to acceptor/
    connector). Mapping uses `direction` and `constraint` the same way the
    tutorials do. Do not emit `<solver:…/>`.
    """
    xml = generate_precice_config(default_policy())
    assert '<solver-interface dimensions="3">' in xml
    assert xml.index("<solver-interface") < xml.index("<data:vector")
    assert xml.index("</solver-interface>") > xml.index("</coupling-scheme:serial-implicit>")
    assert '<mesh name="interface">' in xml
    assert '<mesh name="interface-fluid">' in xml
    assert 'dimensions="' not in xml.split("<solver-interface", 1)[1].split(">", 1)[1]
    assert 'm2n:sockets from="Fluid" to="Solid"' in xml
    assert "acceptor=" not in xml
    assert "connector=" not in xml
    fluid = _participant_block(xml, "Fluid")
    assert 'mapping:nearest-neighbor direction="write"' in fluid
    assert 'constraint="conservative"' in fluid
    assert 'mapping:nearest-neighbor direction="read"' in fluid
    assert 'constraint="consistent"' in fluid


def test_find_precice_checks_tools_then_binprecice_then_ci_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Coupler lookup is a binary on PATH, in official-name order.

    Agents: `precice` is the CI stand-in, last so a fake still resolves when
    the real names are absent. `precice-tools` and `binprecice` are the names
    installs actually ship. This function does not start an FSI solve.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    monkeypatch.setenv("PATH", str(bindir))
    assert find_precice() is None

    alias = bindir / "precice"
    alias.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    alias.chmod(0o755)
    assert find_precice() == alias

    driver = bindir / "binprecice"
    driver.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    driver.chmod(0o755)
    assert find_precice() == driver

    tools = bindir / "precice-tools"
    tools.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tools.chmod(0o755)
    assert find_precice() == tools


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
