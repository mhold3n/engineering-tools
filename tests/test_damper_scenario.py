"""Damper-keyway scenario: params, B relations, solvers, fake-tool orchestration."""

from __future__ import annotations

import os
import re
from importlib import resources
from pathlib import Path

from engineering_tools.damper_cfd import parse_internal_field_p, write_chamber_case
from engineering_tools.damper_fea import parse_von_mises, sample_frd_von_mises, write_solid_inp
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
    state = {
        name: {
            "xyz_mm": list(xyz),
            "fea": {"von_mises": 12.0} if name in {"key_fillet", "keyway_root", "belt_land"} else None,
            "cfd": {"p": 1000.0} if name in {"chamber_center", "chamber_wall"} else None,
        }
        for name, xyz in probes.items()
    }
    rows = evaluate_relations(
        probes=probes,
        state_probes=state,
        belt_land_traction_mpa=params["belt_land_traction_mpa"],
    )
    assert {row["id"]: row["ok"] for row in rows} == {
        "shared-frame": True,
        "named-coverage": True,
        "order-of-magnitude-traction": True,
    }


def test_relations_fail_on_xyz_mismatch() -> None:
    params = load_params()
    probes = probes_from_params(params)
    state = {
        name: {"xyz_mm": [0.0, 0.0, 0.0], "fea": {"von_mises": 1.0}, "cfd": {"p": 1.0}}
        for name in probes
    }
    rows = evaluate_relations(probes=probes, state_probes=state, belt_land_traction_mpa=2.0)
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


def test_run_damper_keyway_ok_with_fakes(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(
        binary_dir / "FreeCADCmd",
        """
touch damper.FCStd solid.step fluid.step
exit 0
""",
    )
    seed = tmp_path / "seed.frd"
    _seed_frd(seed, 15.5)
    executable(
        binary_dir / "ccx",
        f"cp '{seed}' solid.frd\nprintf 'Mises  15.5\\n' > solid.dat\nexit 0\n",
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
    assert result["report"]["a_ok"] is True
    assert result["status"] == "ok"
    assert all(row["ok"] for row in result["report"]["relations"])


def test_run_damper_keyway_fails_without_pressure_field(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(
        binary_dir / "FreeCADCmd",
        """
touch damper.FCStd solid.step fluid.step
exit 0
""",
    )
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
    executable(binary_dir / "FreeCADCmd", "touch damper.FCStd solid.step fluid.step\nexit 0\n")
    seed = tmp_path / "seed.frd"
    _seed_frd(seed, 0.0)
    executable(binary_dir / "ccx", f"cp '{seed}' solid.frd\ntouch solid.dat\nexit 0\n")
    executable(binary_dir / "blockMesh", "mkdir -p constant/polyMesh\ntouch constant/polyMesh/points\nexit 0\n")
    executable(binary_dir / "icoFoam", "mkdir -p 0.1\nprintf 'internalField uniform 101325;\\n' > 0.1/p\nexit 0\n")
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    result = run_damper_keyway(init_project(tmp_path / "part", name="Damper"))
    assert result["ok"] is False
    assert "zero" in result["message"]


def test_run_damper_keyway_fails_when_key_stress_exceeds_a_band(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(binary_dir / "FreeCADCmd", "touch damper.FCStd solid.step fluid.step\nexit 0\n")
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
