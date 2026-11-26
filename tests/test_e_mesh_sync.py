"""Vessel mesh sync. Gmsh pair and CalculiX deck on this machine.

Agents: OpenFOAM gmshToFoam is missing here, so the run status is missing
and e_ok is false. The test does not skip and does not start the coupled solve.
"""

from __future__ import annotations

from pathlib import Path

from engineering_tools.e_mesh_sync import mesh_sync_run


def test_mesh_sync_pair_and_missing_openfoam(tmp_path: Path) -> None:
    out = tmp_path / "mesh-sync"
    report = mesh_sync_run(out)
    pair = report["stages"]["pair"]
    assert pair["status"] == "ok"
    assert pair["solid_volume_nodes"] > 0
    assert pair["fluid_volume_nodes"] > 0
    assert pair["canonical_face_id"] == "face.inner_wall"
    solid = report["stages"]["calculix_mesh"]
    assert solid["status"] == "ok"
    assert solid["n_interface_nodes"] > 0
    inp = (out / "e-solid" / "e-solid.inp").read_text(encoding="utf-8")
    assert "NinterfaceN" in inp
    assert "face.inner_wall" in inp
    assert report["stages"]["openfoam_mesh"]["status"] == "missing"
    assert report["stages"]["sync"]["status"] == "ok"
    xml = (out / "precice-config.xml").read_text(encoding="utf-8")
    assert '<participants first="Fluid" second="Solid"/>' in xml
    assert 'exchange data="Displacement"' not in xml
    assert 'from="Solid" to=' not in xml
    assert 'write-data name="Displacement"' not in xml
    assert report["e_ok"] is False
    assert report["status"] == "missing"
    saved = (out / "mesh-sync.json").read_text(encoding="utf-8")
    assert '"e_ok": false' in saved
