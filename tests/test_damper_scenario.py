"""Damper-keyway scenario: params, B relations, solvers, fake-tool orchestration."""

from __future__ import annotations

import json
import os
import re
from importlib import resources
from pathlib import Path

from engineering_tools.damper_cfd import parse_internal_field_p, write_chamber_case
from engineering_tools.damper_fea import (
    mapped_deck_has_wall_cload,
    parse_von_mises,
    sample_frd_von_mises,
    write_solid_inp,
    write_solid_map_inp,
)
from engineering_tools.damper_params import (
    FLUID_PROBES,
    REQUIRED_PROBES,
    SOLID_PROBES,
    kinematic_to_pa,
    load_params,
    params_digest,
    probes_from_params,
    require_density,
)
from engineering_tools.damper_relations import evaluate_relations
from engineering_tools.damper_scenario import run_damper_keyway
from engineering_tools.project import init_project


def test_packaged_params_include_fluid_density() -> None:
    assert load_params()["fluid_density_kg_m3"] == 850.0


def test_kinematic_to_pa_multiplies_density() -> None:
    assert kinematic_to_pa(0.067, 850.0) == 0.067 * 850.0


def test_require_density_rejects_missing() -> None:
    try:
        require_density({"housing_id_mm": 50.0})
    except ValueError as exc:
        assert "fluid_density_kg_m3" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_packaged_params_define_required_probes() -> None:
    params = load_params()
    probes = probes_from_params(params)
    assert set(REQUIRED_PROBES) <= set(probes)
    assert set(SOLID_PROBES) == {"key_fillet", "keyway_root", "belt_land"}
    assert set(FLUID_PROBES) == {"chamber_center", "chamber_wall"}
    for xyz in probes.values():
        assert len(xyz) == 3
        assert all(isinstance(v, float) for v in xyz)
    assert len(params_digest(params)) == 64
    gap = (float(params["housing_id_mm"]) - float(params["shaft_od_mm"])) / 2.0
    assert float(params["key_height_mm"]) >= gap + float(params["keyway_depth_mm"])
    xyzs = [tuple(probes[n]) for n in REQUIRED_PROBES]
    assert len(set(xyzs)) == len(REQUIRED_PROBES)
    assert probes["key_fillet"][0] == float(params["shaft_od_mm"]) / 2.0
    assert probes["keyway_root"][0] == float(params["housing_id_mm"]) / 2.0 + float(params["keyway_depth_mm"])
    assert probes["chamber_wall"][0] == -float(params["housing_id_mm"]) / 2.0
    assert probes["chamber_center"] == [0.0, 0.0, 0.0]


def test_relations_pass_when_frame_and_scalars_align() -> None:
    params = load_params()
    probes = probes_from_params(params)
    rho = float(params["fluid_density_kg_m3"])
    state = {
        name: {
            "xyz_mm": list(xyz),
            "fea": {"von_mises": 12.0} if name in SOLID_PROBES else None,
            "fea_mapped": {"von_mises": 12.1} if name in SOLID_PROBES else None,
            "cfd": (
                {"p": 1000.0, "p_kinematic": 1000.0 / rho}
                if name in FLUID_PROBES
                else None
            ),
        }
        for name, xyz in probes.items()
    }
    rows = evaluate_relations(
        probes=probes,
        state_probes=state,
        belt_land_traction_mpa=params["belt_land_traction_mpa"],
        mapped_deck_has_wall_cload=True,
        mapped_frd_exists=True,
    )
    assert {row["id"]: row["ok"] for row in rows} == {
        "shared-frame": True,
        "named-coverage": True,
        "order-of-magnitude-traction": True,
        "weak-map": True,
    }


def test_relations_fail_when_cfd_p_is_kinematic_scale() -> None:
    params = load_params()
    probes = probes_from_params(params)
    state = {
        name: {
            "xyz_mm": list(xyz),
            "fea": {"von_mises": 12.0} if name in SOLID_PROBES else None,
            "fea_mapped": {"von_mises": 12.0} if name in SOLID_PROBES else None,
            "cfd": {"p": 0.067, "p_kinematic": 0.067} if name in FLUID_PROBES else None,
        }
        for name, xyz in probes.items()
    }
    rows = evaluate_relations(
        probes=probes,
        state_probes=state,
        belt_land_traction_mpa=2.0,
        mapped_deck_has_wall_cload=True,
        mapped_frd_exists=True,
    )
    assert next(r for r in rows if r["id"] == "order-of-magnitude-traction")["ok"] is False


def test_weak_map_fails_without_mapped_frd() -> None:
    params = load_params()
    probes = probes_from_params(params)
    state = {
        name: {
            "xyz_mm": list(xyz),
            "fea": {"von_mises": 12.0} if name in SOLID_PROBES else None,
            "fea_mapped": {"von_mises": 12.0} if name in SOLID_PROBES else None,
            "cfd": {"p": 1000.0, "p_kinematic": 1.0} if name in FLUID_PROBES else None,
        }
        for name, xyz in probes.items()
    }
    rows = evaluate_relations(
        probes=probes,
        state_probes=state,
        belt_land_traction_mpa=2.0,
        mapped_deck_has_wall_cload=True,
        mapped_frd_exists=False,
    )
    assert next(r for r in rows if r["id"] == "weak-map")["ok"] is False


def test_relations_fail_on_xyz_mismatch() -> None:
    params = load_params()
    probes = probes_from_params(params)
    rho = float(params["fluid_density_kg_m3"])
    state = {
        name: {
            "xyz_mm": [0.0, 0.0, 0.0],
            "fea": {"von_mises": 1.0},
            "fea_mapped": {"von_mises": 1.0},
            "cfd": {"p": 1000.0, "p_kinematic": 1000.0 / rho},
        }
        for name in probes
    }
    rows = evaluate_relations(
        probes=probes,
        state_probes=state,
        belt_land_traction_mpa=2.0,
        mapped_deck_has_wall_cload=True,
        mapped_frd_exists=True,
    )
    assert next(row for row in rows if row["id"] == "shared-frame")["ok"] is False


def test_write_solid_inp_contains_c3d8_and_cload(tmp_path: Path) -> None:
    params = load_params()
    path = write_solid_inp(params, tmp_path / "solid.inp")
    text = path.read_text(encoding="utf-8")
    assert "*ELEMENT, TYPE=C3D8" in text
    assert "*CLOAD" in text
    assert ", 2, " in text
    shaft_r = float(params["shaft_od_mm"]) / 2.0
    od_r = float(params["housing_od_mm"]) / 2.0
    assert f"{shaft_r:.6f}" in text or f"{shaft_r}" in text
    assert f"{od_r:.6f}" in text or f"{od_r}" in text
    assert text.count("*ELEMENT, TYPE=C3D8") == 1
    assert text.count("\n1, ") >= 1
    assert len(re.findall(r"^\d+,\s+\d+,\s+\d+,\s+\d+,\s+\d+,\s+\d+,\s+\d+,\s+\d+,\s+\d+", text, re.M)) >= 4


def test_write_solid_map_inp_adds_inward_wall_cload(tmp_path: Path) -> None:
    from engineering_tools.damper_fea import _nid, _radial_stations

    params = load_params()
    wall_p_pa = 56.0
    path = write_solid_map_inp(params, tmp_path / "solid-map.inp", wall_p_pa=wall_p_pa)
    text = path.read_text(encoding="utf-8")
    belt = write_solid_inp(params, tmp_path / "solid.inp").read_text(encoding="utf-8")
    assert "*CLOAD" in text
    assert ", 2, " in text
    assert "** mapped chamber_wall Pa" in text
    # Pa -> MPa, then quartered over four ID nodes: -(p/1e6)*key_width*key_length/4.
    area = float(params["key_width_mm"]) * float(params["key_length_mm"])
    force = -(float(wall_p_pa) / 1e6) * area / 4.0
    xs, _ys, _zs = _radial_stations(params)
    ix = xs.index(float(params["housing_id_mm"]) / 2.0)
    wall_lines = [f"{_nid(ix, iy, iz)}, 1, {force}" for iy in range(2) for iz in range(2)]
    assert len(wall_lines) == 4
    for line in wall_lines:
        assert line in text
    assert mapped_deck_has_wall_cload(text) is True
    assert mapped_deck_has_wall_cload(belt) is False
    assert mapped_deck_has_wall_cload("** mapped chamber_wall Pa\n") is False
    assert text.count("*NODE") == belt.count("*NODE")


def test_parse_von_mises_reads_dat_sample() -> None:
    sample = " forces\n SXX,SYY,SZZ\n  12.0  0.1  0.1\n Mises  15.5\n"
    assert parse_von_mises(sample) == 15.5


def test_parse_frd_von_mises_reads_stress_block() -> None:
    frd = """
 -4  STRESS      6    1
 -5  SXX         1    4    1    1
 -1         1 2.00000E+02 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00
 -3
"""
    from engineering_tools.damper_fea import parse_frd_von_mises

    assert parse_frd_von_mises(frd) == 200.0


def test_sample_frd_von_mises_nearest_named_probes() -> None:
    frd = """
    2C                             2                                     1
 -1         1 1.00000E+01 3.00000E+00 0.00000E+00
 -1         2 2.80000E+01 0.00000E+00 0.00000E+00
 -3
 -4  STRESS      6    1
 -1         1 1.20000E+02 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00
 -1         2 8.00000E+01 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00
 -3
"""
    got = sample_frd_von_mises(
        frd,
        {"key_fillet": [10.0, 3.0, 0.0], "keyway_root": [28.0, 0.0, 0.0]},
    )
    assert got["key_fillet"] == 120.0
    assert got["keyway_root"] == 80.0


def test_build_damper_cuts_keyway_and_centers_origin() -> None:
    text = (resources.files("engineering_tools") / "data" / "damper" / "build_damper.py").read_text(encoding="utf-8")
    assert "keyway" in text
    assert "housing.cut" in text
    assert "-length / 2" in text or "-length/2" in text
    assert "keyway_depth" in text


def test_write_chamber_case_sizes_block_from_params(tmp_path: Path) -> None:
    work = tmp_path / "foam"
    meta = write_chamber_case(load_params(), work)
    text = (work / "system" / "blockMeshDict").read_text(encoding="utf-8")
    lx = float(load_params()["housing_id_mm"]) * 1e-3
    lz = float(load_params()["chamber_length_mm"]) * 1e-3
    assert f"{lx}" in text
    assert f"{lz}" in text
    assert "convertToMeters 1" in text
    assert meta["nx"] == 20
    assert meta["ny"] == 20


def test_parse_internal_field_p_center_cell() -> None:
    text = "internalField   nonuniform List<scalar> \n4\n(\n1.0\n2.0\n3.0\n4.0\n)\n;\n"
    assert parse_internal_field_p(text, cell_index=0) == 1.0
    assert parse_internal_field_p(text, cell_index=3) == 4.0


def test_write_chamber_case_has_control_dict(tmp_path: Path) -> None:
    work = tmp_path / "foam"
    write_chamber_case(load_params(), work)
    assert (work / "system" / "controlDict").is_file()
    assert (work / "0" / "p").is_file()


def test_parse_internal_field_p_uniform() -> None:
    assert parse_internal_field_p("internalField uniform 101325;\n") == 101325.0


def test_parse_internal_field_p_nonuniform_max_abs() -> None:
    text = "internalField   nonuniform List<scalar> \n3\n(\n-0.01\n0.5\n-2.0\n)\n;\n"
    assert parse_internal_field_p(text) == 2.0


def test_build_damper_script_is_packaged() -> None:
    text = (resources.files("engineering_tools") / "data" / "damper" / "build_damper.py").read_text(encoding="utf-8")
    assert "import Part" in text
    assert "solid.step" in text


def _seed_frd(path: Path, mises: float) -> None:
    """Minimal FRD with 2C nodes on solid probes and a uniaxial STRESS block."""
    lines = ["    2C"]
    ids: list[int] = []
    nid = 1
    for name in SOLID_PROBES:
        xyz = probes_from_params(load_params())[name]
        lines.append(f" -1         {nid} {xyz[0]:.5e} {xyz[1]:.5e} {xyz[2]:.5e}")
        ids.append(nid)
        nid += 1
    lines.append(" -3")
    lines.append(" -4  STRESS      6    1")
    for node in ids:
        lines.append(
            f" -1         {node} {mises:.5e} 0.00000e+00 0.00000e+00 0.00000e+00 0.00000e+00 0.00000e+00"
        )
    lines.append(" -3")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def executable(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _fake_cad_script(probes_path: Path) -> str:
    """Fake FreeCADCmd copies an agreed probes.json into cwd, then the CAD files."""
    return f"cp '{probes_path}' probes.json\ntouch damper.FCStd solid.step fluid.step\nexit 0\n"


def _write_agreed_probes(path: Path) -> None:
    path.write_text(json.dumps(probes_from_params(load_params())), encoding="utf-8")


def test_run_damper_keyway_ok_with_fakes(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    probes_path = tmp_path / "probes.json"
    _write_agreed_probes(probes_path)
    executable(binary_dir / "FreeCADCmd", _fake_cad_script(probes_path))
    pass1 = tmp_path / "pass1.frd"
    pass2 = tmp_path / "pass2.frd"
    _seed_frd(pass1, 15.5)
    _seed_frd(pass2, 40.0)
    # $1 is the CalculiX job name: solid is pass 1, solid-map is the wall-Pa pass.
    executable(
        binary_dir / "ccx",
        f"""case "$1" in
  solid) cp '{pass1}' solid.frd; printf 'Mises  15.5\\n' > solid.dat ;;
  solid-map) cp '{pass2}' solid-map.frd ;;
esac
exit 0
""",
    )
    executable(
        binary_dir / "blockMesh",
        "mkdir -p constant/polyMesh\ntouch constant/polyMesh/points\nexit 0\n",
    )
    executable(
        binary_dir / "icoFoam",
        "mkdir -p 0.1\nprintf 'internalField uniform 2.0;\\n' > 0.1/p\nexit 0\n",
    )
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    project = init_project(tmp_path / "part", name="Damper")
    result = run_damper_keyway(project)
    assert result["ok"] is True
    assert result["report"]["b_ok"] is True
    assert result["report"]["a_ok"] is True
    assert result["status"] == "ok"
    assert all(row["ok"] for row in result["report"]["relations"])
    state = json.loads((project / "artifacts" / "scenario-damper-keyway" / "product-state.json").read_text(encoding="utf-8"))
    assert state["coupling"] == "weak-map"
    assert state["fluid_density_kg_m3"] == 850
    for name in SOLID_PROBES:
        row = state["probes"][name]
        assert row["fea"]["von_mises"] != row["fea_mapped"]["von_mises"]
    for name in FLUID_PROBES:
        cfd = state["probes"][name]["cfd"]
        assert "p" in cfd
        assert "p_kinematic" in cfd


def test_run_damper_keyway_fails_when_cad_probes_mismatch(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    bad = tmp_path / "probes.json"
    agreed = probes_from_params(load_params())
    bad.write_text(json.dumps({name: [0.0, 0.0, 0.0] for name in agreed}), encoding="utf-8")
    executable(binary_dir / "FreeCADCmd", _fake_cad_script(bad))
    seed = tmp_path / "seed.frd"
    _seed_frd(seed, 15.5)
    executable(
        binary_dir / "ccx",
        f"cp '{seed}' solid.frd\ncp '{seed}' solid-map.frd\nprintf 'Mises  15.5\\n' > solid.dat\nexit 0\n",
    )
    executable(binary_dir / "blockMesh", "mkdir -p constant/polyMesh\ntouch constant/polyMesh/points\nexit 0\n")
    executable(
        binary_dir / "icoFoam",
        "mkdir -p 0.1\nprintf 'internalField uniform 2.0;\\n' > 0.1/p\nexit 0\n",
    )
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    result = run_damper_keyway(init_project(tmp_path / "part", name="Damper"))
    assert result["ok"] is False
    assert "xyz" in result["message"]


def test_run_damper_keyway_fails_without_pass2_frd(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    probes_path = tmp_path / "probes.json"
    _write_agreed_probes(probes_path)
    executable(binary_dir / "FreeCADCmd", _fake_cad_script(probes_path))
    seed = tmp_path / "seed.frd"
    _seed_frd(seed, 15.5)
    executable(binary_dir / "ccx", f"cp '{seed}' solid.frd\nprintf 'Mises  15.5\\n' > solid.dat\nexit 0\n")
    executable(binary_dir / "blockMesh", "mkdir -p constant/polyMesh\ntouch constant/polyMesh/points\nexit 0\n")
    executable(
        binary_dir / "icoFoam",
        "mkdir -p 0.1\nprintf 'internalField uniform 2.0;\\n' > 0.1/p\nexit 0\n",
    )
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    result = run_damper_keyway(init_project(tmp_path / "part", name="Damper"))
    assert result["ok"] is False
    assert "solid-map" in result["message"]


def test_run_damper_keyway_fails_without_pressure_field(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    probes_path = tmp_path / "probes.json"
    _write_agreed_probes(probes_path)
    executable(binary_dir / "FreeCADCmd", _fake_cad_script(probes_path))
    seed = tmp_path / "seed.frd"
    _seed_frd(seed, 15.5)
    executable(binary_dir / "ccx", f"cp '{seed}' solid.frd\nprintf 'Mises  15.5\\n' > solid.dat\nexit 0\n")
    executable(binary_dir / "blockMesh", "mkdir -p constant/polyMesh\ntouch constant/polyMesh/points\nexit 0\n")
    executable(binary_dir / "icoFoam", "exit 0\n")
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    project = init_project(tmp_path / "part", name="Damper")
    result = run_damper_keyway(project)
    assert result["ok"] is False
    assert "p" in result["message"]


def test_run_damper_keyway_fails_when_both_key_stresses_zero(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    probes_path = tmp_path / "probes.json"
    _write_agreed_probes(probes_path)
    executable(binary_dir / "FreeCADCmd", _fake_cad_script(probes_path))
    seed = tmp_path / "seed.frd"
    _seed_frd(seed, 0.0)
    executable(binary_dir / "ccx", f"cp '{seed}' solid.frd\ntouch solid.dat\nexit 0\n")
    executable(binary_dir / "blockMesh", "mkdir -p constant/polyMesh\ntouch constant/polyMesh/points\nexit 0\n")
    executable(binary_dir / "icoFoam", "mkdir -p 0.1\nprintf 'internalField uniform 101325;\\n' > 0.1/p\nexit 0\n")
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    result = run_damper_keyway(init_project(tmp_path / "part", name="Damper"))
    assert result["ok"] is False
    assert "zero" in result["message"]


def test_coupling_c_not_evaluated_when_freecad_missing(tmp_path, monkeypatch) -> None:
    """A/B prerequisite failure must not start C or write c-session.json."""
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    project = init_project(tmp_path / "part", name="Damper")
    result = run_damper_keyway(project, coupling="c")
    assert result["ok"] is False
    assert result["c"]["evaluated"] is False
    assert result["c"]["reason"] == "prerequisite_not_ok"
    session = project / "artifacts" / "scenario-damper-keyway" / "c-fsi" / "c-session.json"
    assert not session.exists()
    # Disk copy is written after report["c"] is attached, not before.
    report_path = project / "artifacts" / "scenario-damper-keyway" / "scenario-report.json"
    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    assert persisted["c"]["evaluated"] is False
    assert persisted["c"]["reason"] == "prerequisite_not_ok"


def test_coupling_d_not_evaluated_when_freecad_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    project = init_project(tmp_path / "part", name="Damper")
    result = run_damper_keyway(project, coupling="d")
    assert result["ok"] is False
    assert result["d"]["evaluated"] is False
    assert result["d"]["reason"] == "prerequisite_not_ok"
    session = project / "artifacts" / "scenario-damper-keyway" / "d-fsi" / "d-session.json"
    assert not session.exists()


def test_coupling_c_ab_success_reports_c_ok_with_fakes(tmp_path, monkeypatch) -> None:
    """A/B fakes plus precice/pimpleFoam yield A+B+C and c_ok on the report.

    Agents: sample_c_probes is not monkeypatched. The fake ccx writes an FRD
    whose nodes are the C deck, and the fake pimpleFoam writes kinematic p.
    """
    from engineering_tools.c_fsi_meshes import interface_node_ids, write_c_solid_inp

    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    probes_path = tmp_path / "probes.json"
    _write_agreed_probes(probes_path)
    executable(binary_dir / "FreeCADCmd", _fake_cad_script(probes_path))
    pass1 = tmp_path / "pass1.frd"
    pass2 = tmp_path / "pass2.frd"
    _seed_frd(pass1, 15.5)
    _seed_frd(pass2, 40.0)
    preview = tmp_path / "c-preview.inp"
    write_c_solid_inp(load_params(), preview)
    nodes: dict[int, tuple[float, float, float]] = {}
    in_nodes = False
    for line in preview.read_text(encoding="utf-8").splitlines():
        if line.startswith("*NODE"):
            in_nodes = True
            continue
        if in_nodes and line.startswith("*"):
            break
        if not in_nodes or not line.strip():
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 4:
            nodes[int(parts[0])] = (float(parts[1]), float(parts[2]), float(parts[3]))
    frd_lines = ["    2C"]
    for nid, xyz in nodes.items():
        frd_lines.append(f" -1         {nid} {xyz[0]:.5e} {xyz[1]:.5e} {xyz[2]:.5e}")
    frd_lines.append(" -3")
    frd_lines.append(" -4  DISP        4    1")
    for nid in interface_node_ids():
        frd_lines.append(f" -1         {nid} 1.00000e-03 0.00000e+00 0.00000e+00")
    frd_lines.append(" -3")
    frd_lines.append(" -4  STRESS      6    1")
    for nid in nodes:
        frd_lines.append(
            f" -1         {nid} 4.00000e+01 0.00000e+00 0.00000e+00 0.00000e+00 0.00000e+00 0.00000e+00"
        )
    frd_lines.append(" -3")
    c_frd = tmp_path / "c-solid.frd"
    c_frd.write_text("\n".join(frd_lines) + "\n", encoding="utf-8")
    executable(
        binary_dir / "ccx",
        f"""case "$1" in
  solid) cp '{pass1}' solid.frd; printf 'Mises  15.5\\n' > solid.dat ;;
  solid-map) cp '{pass2}' solid-map.frd ;;
esac
exit 0
""",
    )
    executable(
        binary_dir / "ccx_preCICE",
        f"cp '{c_frd}' c-solid.frd\nprintf 'Time window completed\\nTime window completed\\n'\nexit 0\n",
    )
    executable(binary_dir / "blockMesh", "mkdir -p constant/polyMesh\ntouch constant/polyMesh/points\nexit 0\n")
    executable(
        binary_dir / "icoFoam",
        "mkdir -p 0.1\nprintf 'internalField uniform 2.0;\\n' > 0.1/p\nexit 0\n",
    )
    executable(
        binary_dir / "pimpleFoam",
        "printf 'Time window completed\\nTime window completed\\n'\n"
        "mkdir -p 0.1\nprintf 'internalField uniform 2.0;\\n' > 0.1/p\nexit 0\n",
    )
    executable(binary_dir / "precice-tools", "exit 0\n")
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    project = init_project(tmp_path / "part", name="Damper")
    result = run_damper_keyway(project, coupling="c")
    assert result["ok"] is True
    assert result["message"] == "damper-keyway A+B+C passed"
    assert result["report"]["c_ok"] is True
    assert result["c"]["c_ok"] is True
    assert result["c"]["status"] == "ok"


def test_coupling_c_broken_when_c_adapter_import_fails(tmp_path, monkeypatch) -> None:
    """A missing first-party C adapter is C broken, after A/B succeeded.

    Agents: run_c_fsi is imported inside the coupling branch. A meta-path
    finder raises ImportError for the façade and the CalculiX adapter so
    the branch cannot use a previously imported module.
    """
    import sys

    class _BlockCAdapters:
        """Raise ImportError when the C façade or CalculiX adapter is imported."""

        def find_spec(self, fullname, path, target=None):
            blocked = {
                "engineering_tools.c_facade",
                "engineering_tools.c_adapter_calculix",
            }
            if fullname in blocked:
                raise ImportError(f"blocked {fullname}")
            return None

    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    probes_path = tmp_path / "probes.json"
    _write_agreed_probes(probes_path)
    executable(binary_dir / "FreeCADCmd", _fake_cad_script(probes_path))
    seed = tmp_path / "seed.frd"
    _seed_frd(seed, 15.5)
    mapped = tmp_path / "mapped.frd"
    _seed_frd(mapped, 40.0)
    executable(
        binary_dir / "ccx",
        f"""case "$1" in
  solid) cp '{seed}' solid.frd; printf 'Mises  15.5\\n' > solid.dat ;;
  solid-map) cp '{mapped}' solid-map.frd ;;
esac
exit 0
""",
    )
    executable(binary_dir / "blockMesh", "mkdir -p constant/polyMesh\ntouch constant/polyMesh/points\nexit 0\n")
    executable(
        binary_dir / "icoFoam",
        "mkdir -p 0.1\nprintf 'internalField uniform 2.0;\\n' > 0.1/p\nexit 0\n",
    )
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    blocker = _BlockCAdapters()
    sys.meta_path.insert(0, blocker)
    sys.modules.pop("engineering_tools.c_facade", None)
    try:
        result = run_damper_keyway(init_project(tmp_path / "part", name="Damper"), coupling="c")
    finally:
        sys.meta_path.remove(blocker)
        sys.modules.pop("engineering_tools.c_facade", None)
    assert result["ok"] is False
    assert result["status"] == "broken"
    assert result["c"]["status"] == "broken"
    assert result["c"]["evaluated"] is True
    assert "import" in result["message"].lower()


def test_run_damper_keyway_fails_when_key_stress_exceeds_a_band(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    probes_path = tmp_path / "probes.json"
    _write_agreed_probes(probes_path)
    executable(binary_dir / "FreeCADCmd", _fake_cad_script(probes_path))
    seed = tmp_path / "seed.frd"
    _seed_frd(seed, 5000.0)
    executable(binary_dir / "ccx", f"cp '{seed}' solid.frd\ntouch solid.dat\nexit 0\n")
    executable(binary_dir / "blockMesh", "mkdir -p constant/polyMesh\ntouch constant/polyMesh/points\nexit 0\n")
    executable(
        binary_dir / "icoFoam",
        "mkdir -p 0.1\nprintf 'internalField uniform 101325;\\n' > 0.1/p\nexit 0\n",
    )
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    result = run_damper_keyway(init_project(tmp_path / "part", name="Damper"))
    assert result["ok"] is False
    assert "A band" in result["message"]
