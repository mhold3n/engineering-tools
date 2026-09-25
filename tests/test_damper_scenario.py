"""Damper-keyway scenario: params, B relations, solvers, fake-tool orchestration."""

from __future__ import annotations

import os
from importlib import resources
from pathlib import Path

from engineering_tools.damper_cfd import parse_internal_field_p, write_chamber_case
from engineering_tools.damper_fea import parse_von_mises, write_solid_inp
from engineering_tools.damper_params import (
    FLUID_PROBES,
    REQUIRED_PROBES,
    SOLID_PROBES,
    load_params,
    params_digest,
    probes_from_params,
)
from engineering_tools.damper_relations import evaluate_relations
from engineering_tools.damper_scenario import run_damper_keyway
from engineering_tools.project import init_project


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
    path = write_solid_inp(load_params(), tmp_path / "solid.inp")
    text = path.read_text(encoding="utf-8")
    assert "*ELEMENT, TYPE=C3D8" in text
    assert "*CLOAD" in text


def test_parse_von_mises_reads_dat_sample() -> None:
    sample = " forces\n SXX,SYY,SZZ\n  12.0  0.1  0.1\n Mises  15.5\n"
    assert parse_von_mises(sample) == 15.5


def test_write_chamber_case_has_control_dict(tmp_path: Path) -> None:
    work = tmp_path / "foam"
    write_chamber_case(load_params(), work)
    assert (work / "system" / "controlDict").is_file()
    assert (work / "0" / "p").is_file()


def test_parse_internal_field_p_uniform() -> None:
    assert parse_internal_field_p("internalField uniform 101325;\n") == 101325.0


def test_build_damper_script_is_packaged() -> None:
    text = (resources.files("engineering_tools") / "data" / "damper" / "build_damper.py").read_text(encoding="utf-8")
    assert "import Part" in text
    assert "solid.step" in text


def executable(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)


def test_run_damper_keyway_ok_with_fakes(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(
        binary_dir / "FreeCADCmd",
        """
out="$3"
mkdir -p "$out"
touch "$out/damper.FCStd" "$out/solid.step" "$out/fluid.step"
exit 0
""",
    )
    executable(
        binary_dir / "ccx",
        """
printf 'Mises  15.5\\n' > solid.dat
touch solid.frd
exit 0
""",
    )
    executable(
        binary_dir / "blockMesh",
        "mkdir -p constant/polyMesh\ntouch constant/polyMesh/points\nexit 0\n",
    )
    executable(
        binary_dir / "icoFoam",
        "mkdir -p 0.1\nprintf 'internalField uniform 101325;\\n' > 0.1/p\nexit 0\n",
    )
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    project = init_project(tmp_path / "part", name="Damper")
    result = run_damper_keyway(project)
    assert result["ok"] is True
    assert result["status"] == "ok"
    assert all(row["ok"] for row in result["report"]["relations"])


def test_run_damper_keyway_fails_without_pressure_field(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(
        binary_dir / "FreeCADCmd",
        """
out="$3"
mkdir -p "$out"
touch "$out/damper.FCStd" "$out/solid.step" "$out/fluid.step"
exit 0
""",
    )
    executable(binary_dir / "ccx", "printf 'Mises  15.5\\n' > solid.dat\ntouch solid.frd\nexit 0\n")
    executable(binary_dir / "blockMesh", "mkdir -p constant/polyMesh\ntouch constant/polyMesh/points\nexit 0\n")
    executable(binary_dir / "icoFoam", "exit 0\n")
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    project = init_project(tmp_path / "part", name="Damper")
    result = run_damper_keyway(project)
    assert result["ok"] is False
    assert "p" in result["message"]
