"""C-FSI mesh and canonical probe resolution tests.

Agents: these tests pin metres from damper-params probes and the shared
interface name. They do not run CalculiX or OpenFOAM.
"""

from pathlib import Path

import pytest

from engineering_tools.c_fsi_meshes import canonical_xyz_m, write_c_fluid_case, write_c_solid_inp
from engineering_tools.damper_params import load_params


def test_canonical_xyz_matches_params_in_metres() -> None:
    params = load_params()
    xyz = canonical_xyz_m(params)
    wall = xyz["housing.wall.pressure"]
    assert wall[0] == pytest.approx(-float(params["housing_id_mm"]) / 2000.0)


def test_c_solid_and_fluid_share_interface_name(tmp_path: Path) -> None:
    params = load_params()
    write_c_solid_inp(params, tmp_path / "c-solid.inp")
    write_c_fluid_case(params, tmp_path / "c-foam")
    inp = (tmp_path / "c-solid.inp").read_text(encoding="utf-8")
    foam = (tmp_path / "c-foam" / "constant" / "polyMesh" / "blockMeshDict").read_text(encoding="utf-8")
    assert "interface" in inp.lower() or "INTERFACE" in inp
    assert "interface" in foam
