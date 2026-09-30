"""Solid/fluid E mesh writers. Fakes only; no live gmsh/blockMesh required."""

from pathlib import Path

from engineering_tools.e_cad import import_identity
from engineering_tools.e_mesh_fluid import write_fluid_mesh
from engineering_tools.e_mesh_pair import mesh_e_reference
from engineering_tools.e_mesh_solid import write_solid_mesh


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
        msh.write_text("$MeshFormat\n2.2 0 8\n$EndMeshFormat\n$Nodes\n4\n1 0 0 0\n$EndNodes\n", encoding="utf-8")
        return {"status": "ok", "n_nodes": 21}

    got = write_solid_mesh(tmp_path / "s", _identity(), run_gmsh=_gmsh)
    assert got["status"] == "ok"
    assert got["bindings"][0]["entity_id"] == "face.inner_wall"
    assert got["bindings"][0]["node_count"] == 21
    assert (tmp_path / "s" / "solid-mesh.json").is_file()


def test_fluid_missing_blockmesh(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("engineering_tools.e_mesh_fluid.blockmesh_available", lambda: False)
    got = write_fluid_mesh(tmp_path / "f", _identity())
    assert got["status"] == "missing"


def test_fluid_fake_blockmesh_binds_inner_wall(tmp_path: Path) -> None:
    def _bm(case: Path) -> dict:
        poly = case / "constant" / "polyMesh"
        poly.mkdir(parents=True, exist_ok=True)
        (poly / "points").write_text("FoamFile { class vectorField; }\n9\n(\n)\n", encoding="utf-8")
        return {"status": "ok", "n_nodes": 9}

    got = write_fluid_mesh(tmp_path / "f", _identity(), run_blockmesh=_bm)
    assert got["status"] == "ok"
    assert got["bindings"][0]["mesh_set"] == "patch:inner_wall"
    assert got["bindings"][0]["node_count"] == 9


def test_pair_unequal_nodes_ok(tmp_path: Path) -> None:
    def _gmsh(geo: Path, msh: Path) -> dict:
        msh.write_text("ok\n", encoding="utf-8")
        return {"status": "ok", "n_nodes": 40}

    def _bm(case: Path) -> dict:
        return {"status": "ok", "n_nodes": 9}

    got = mesh_e_reference(
        tmp_path / "pair",
        identity=_identity(),
        run_gmsh=_gmsh,
        run_blockmesh=_bm,
    )
    assert got["e_mesh_ok"] is True
    assert got["solid_nodes"] != got["fluid_nodes"]
    assert (tmp_path / "pair" / "pair.json").is_file()


def test_pair_stale_topology_broken(tmp_path: Path) -> None:
    ident = _identity()
    ident = dict(ident)
    ident["topology_version"] = 1

    def _gmsh(geo: Path, msh: Path) -> dict:
        msh.write_text("ok\n", encoding="utf-8")
        return {"status": "ok", "n_nodes": 8}

    def _bm(case: Path) -> dict:
        return {"status": "ok", "n_nodes": 7}

    solid = write_solid_mesh(tmp_path / "s", ident, run_gmsh=_gmsh)
    assert solid["status"] == "ok"
    stale = dict(ident)
    stale["topology_version"] = 2
    fluid = write_fluid_mesh(tmp_path / "f", stale, run_blockmesh=_bm)
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
