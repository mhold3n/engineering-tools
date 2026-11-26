"""Mesh h_max wiring. Comparator tests live in test_e_verify.py."""

from pathlib import Path

from engineering_tools.e_cad import import_identity
from engineering_tools.e_mesh_pair import mesh_e_reference


def test_live_refinement_pair_without_kernels_is_not_engineering_ok(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("engineering_tools.e_facade._authoritative_live", lambda: False)
    monkeypatch.delenv("ETOOLS_E_MOCK_SOLVERS", raising=False)
    from engineering_tools.e_verify import run_live_refinement_pair
    from engineering_tools.e_scenario import reference_model

    got = run_live_refinement_pair(tmp_path / "pair-run", reference_model(), kind="spatial")
    assert got["ok"] is False
    assert (tmp_path / "pair-run" / "e-refine.json").is_file()


def test_mesh_pair_h_max_is_in_geo_and_pair_record(tmp_path: Path) -> None:
    ident = import_identity()

    def _gmsh(geo: Path, msh: Path) -> dict:
        assert "Mesh.CharacteristicLengthMax = 0.006;" in geo.read_text(encoding="utf-8")
        msh.write_text(
            """$MeshFormat
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
3
1 2 2 99 1 1 2 3
2 2 2 99 1 1 3 4
3 4 2 1 1 1 2 3 4
$EndElements
""",
            encoding="utf-8",
        )
        return {"status": "ok", "n_nodes": 4}

    got = mesh_e_reference(tmp_path / "pair", identity=ident, run_gmsh=_gmsh, h_max=0.006)
    assert got["e_mesh_ok"] is True
    assert got["h_max_m"] == 0.006
    assert got["solid_interface_vertices"] == 4
    assert got["fluid_interface_locations"] == 2
    assert got["solid_mesh_id"].startswith("sha256:")
    assert got["fluid_mesh_id"].startswith("sha256:")
    assert len(got["solid_interface_vertex_xyz"]) == 4
    assert len(got["fluid_interface_facecenter_xyz"]) == 2
