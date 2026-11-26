"""Solid/fluid E mesh writers. Fakes only; no live gmsh required."""

from pathlib import Path

from engineering_tools.e_cad import import_identity
from engineering_tools.e_mesh_fluid import write_fluid_mesh
from engineering_tools.e_mesh_pair import mesh_e_reference
from engineering_tools.e_mesh_solid import write_solid_mesh

_IFACE_MSH = """$MeshFormat
2.2 0 8
$EndMeshFormat
$PhysicalNames
1
2 99 "face.inner_wall"
$EndPhysicalNames
$Nodes
4
1 -0.02 0 0
2 -0.02 0.01 0
3 -0.02 0 0.04
4 0 0 0.02
$EndNodes
$Elements
2
1 2 2 99 1 1 2 3
2 4 2 1 1 1 2 3 4
$EndElements
"""


def _identity() -> dict:
    ident = import_identity()
    assert ident["status"] == "ok"
    return ident


def test_solid_missing_gmsh(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("engineering_tools.e_mesh_solid.gmsh_available", lambda: False)
    got = write_solid_mesh(tmp_path / "s", _identity())
    assert got["status"] == "missing"


def test_solid_fake_gmsh_binds_inner_wall(tmp_path: Path) -> None:
    def _gmsh(geo: Path, msh: Path) -> dict:
        msh.write_text(_IFACE_MSH, encoding="utf-8")
        return {"status": "ok", "n_nodes": 4}

    got = write_solid_mesh(tmp_path / "s", _identity(), run_gmsh=_gmsh)
    assert got["status"] == "ok"
    assert got["bindings"][0]["entity_id"] == "face.inner_wall"
    assert got["bindings"][0]["mesh_set"] == "PhysicalSurface:face.inner_wall"
    assert got["interface_vertices"] == 3
    assert got["bindings"][0]["node_count"] == 3
    assert (tmp_path / "s" / "solid-mesh.json").is_file()


def test_fluid_missing_gmsh(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("engineering_tools.e_mesh_fluid.gmsh_available", lambda: False)
    got = write_fluid_mesh(tmp_path / "f", _identity())
    assert got["status"] == "missing"


def test_fluid_fake_gmsh_binds_inner_wall(tmp_path: Path) -> None:
    def _gmsh(geo: Path, msh: Path) -> dict:
        msh.write_text(_IFACE_MSH, encoding="utf-8")
        return {"status": "ok", "n_nodes": 4}

    got = write_fluid_mesh(tmp_path / "f", _identity(), run_gmsh=_gmsh)
    assert got["status"] == "ok"
    assert got["bindings"][0]["mesh_set"] == "PhysicalSurface:face.inner_wall"
    assert got["interface_locations"] == 1
    assert got["bindings"][0]["node_count"] == 1


def test_pair_reports_interface_discretization(tmp_path: Path) -> None:
    def _gmsh(geo: Path, msh: Path) -> dict:
        msh.write_text(_IFACE_MSH, encoding="utf-8")
        return {"status": "ok", "n_nodes": 4}

    got = mesh_e_reference(tmp_path / "pair", identity=_identity(), run_gmsh=_gmsh)
    assert got["e_mesh_ok"] is True
    assert got["solid_interface_vertices"] == 3
    assert got["fluid_interface_locations"] == 1
    assert got["independent"] is True
    assert (tmp_path / "pair" / "pair.json").is_file()


def test_pair_stale_topology_broken(tmp_path: Path) -> None:
    ident = _identity()
    ident = dict(ident)
    ident["topology_version"] = 1

    def _gmsh(geo: Path, msh: Path) -> dict:
        msh.write_text(_IFACE_MSH, encoding="utf-8")
        return {"status": "ok", "n_nodes": 4}

    solid = write_solid_mesh(tmp_path / "s", ident, run_gmsh=_gmsh)
    assert solid["status"] == "ok"
    stale = dict(ident)
    stale["topology_version"] = 2
    fluid = write_fluid_mesh(tmp_path / "f", stale, run_gmsh=_gmsh)
    assert fluid["status"] == "ok"
    from engineering_tools.e_mesh import validate_interface_meshes

    got = validate_interface_meshes(
        [solid, fluid],
        canonical_face_id="face.inner_wall",
        current_topology_version=2,
    )
    assert got["status"] == "broken"


def test_identity_without_gas_is_broken(tmp_path: Path) -> None:
    ident = {"status": "ok", "entity_ids": ["body.shell"], "topology_version": 1}

    def _gmsh(geo: Path, msh: Path) -> dict:
        return {"status": "ok", "n_nodes": 4}

    got = write_solid_mesh(tmp_path / "s", ident, run_gmsh=_gmsh)
    assert got["status"] == "broken"


def test_no_damper_hex_imports() -> None:
    import inspect

    import engineering_tools.e_mesh_fluid as fluid
    import engineering_tools.e_mesh_solid as solid

    for mod in (solid, fluid):
        src = inspect.getsource(mod)
        assert "from engineering_tools.d_" not in src
        assert "write_d_solid_inp" not in src


def test_vessel_step_geo_merges_and_scales_without_cylinder(tmp_path: Path) -> None:
    from engineering_tools.e_mesh_fluid import write_fluid_geo
    from engineering_tools.e_mesh_solid import write_solid_geo

    solid = tmp_path / "solid.geo"
    fluid = tmp_path / "fluid.geo"
    assert write_solid_geo(solid, h_max=0.012) is True
    assert write_fluid_geo(fluid, h_max=0.012) is True
    for path in (solid, fluid):
        text = path.read_text(encoding="utf-8")
        assert 'Merge "' in text
        assert "vessel.step" in text
        assert "Dilate" in text
        assert "0.001" in text
        assert "Cylinder(" not in text
        assert "Mesh.CharacteristicLengthMax" in text
        assert "Geometry.OCCBoundsUseStl = 1;" in text.split("Merge", 1)[0]


def test_real_gmsh_meshes_step_inner_wall_at_0p02(tmp_path: Path) -> None:
    import math
    import shutil
    import subprocess

    import pytest

    from engineering_tools.e_mesh_fluid import write_fluid_geo
    from engineering_tools.e_mesh_solid import write_solid_geo
    from engineering_tools.e_msh2 import interface_facecenter_xyz, interface_vertex_xyz

    gmsh = shutil.which("gmsh")
    if gmsh is None:
        pytest.skip("gmsh not on PATH")
    solid_geo = tmp_path / "solid.geo"
    fluid_geo = tmp_path / "fluid.geo"
    solid_msh = tmp_path / "solid.msh"
    fluid_msh = tmp_path / "fluid.msh"
    assert write_solid_geo(solid_geo, h_max=0.012) is True
    assert write_fluid_geo(fluid_geo, h_max=0.012) is True
    solid_geo_text = solid_geo.read_text(encoding="utf-8")
    assert 'Physical Volume("body.shell")' in solid_geo_text
    assert 'Physical Volume("body.lid")' in solid_geo_text
    assert "BooleanUnion" not in solid_geo_text
    for geo, msh in ((solid_geo, solid_msh), (fluid_geo, fluid_msh)):
        proc = subprocess.run(
            [gmsh, "-3", str(geo), "-o", str(msh), "-format", "msh2"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert proc.returncode == 0, (proc.stderr or proc.stdout or "")[-500:]
        assert msh.is_file()
    solid_xyz = interface_vertex_xyz(solid_msh.read_text(encoding="utf-8", errors="replace"))
    assert solid_xyz
    for x, y, _z in solid_xyz:
        assert abs(math.hypot(x, y) - 0.02) <= 1e-6
    fluid_xyz = interface_facecenter_xyz(fluid_msh.read_text(encoding="utf-8", errors="replace"))
    assert fluid_xyz
    for x, y, _z in fluid_xyz:
        radius = math.hypot(x, y)
        assert 0.015 <= radius <= 0.021
