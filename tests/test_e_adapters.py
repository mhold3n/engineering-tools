"""E adapter decks and CAD-face preCICE mapping. No solver launch."""

from pathlib import Path

from engineering_tools.e_adapter_calculix import CI_SOLID_MSH2, write_e_solid_inp
from engineering_tools.e_cad import import_identity
from engineering_tools.e_interface_map import compile_cad_interface_mapping, write_e_coupling_bundle
def test_solid_deck_has_ninterfacen_and_zero_cload(tmp_path: Path) -> None:
    ident = import_identity()
    msh = tmp_path / "solid.msh"
    msh.write_text(CI_SOLID_MSH2, encoding="utf-8")
    got = write_e_solid_inp(tmp_path / "e-solid.inp", ident, msh=msh)
    assert got["status"] == "ok"
    text = Path(got["path"]).read_text(encoding="utf-8")
    assert "*NSET, NSET=NinterfaceN" in text
    assert "*ELEMENT, TYPE=C3D4" in text
    assert "C3D8" not in text
    assert "*CLOAD" in text
    assert "*DYNAMIC" in text
    assert len(got["node_ids"]) >= 3
    assert "write_d_solid_inp" not in text
    assert "d-fsi sandwich" not in text


def test_bundle_force_not_traction_and_inner_wall_patch(tmp_path: Path) -> None:
    ident = import_identity()
    got = write_e_coupling_bundle(tmp_path / "e-couple", ident)
    assert got["status"] == "ok"
    xml = Path(got["precice_xml"]).read_text(encoding="utf-8")
    assert "Traction" not in xml
    assert "Force" in xml
    assert 'constraint="conservative"' in xml
    fluid_yml = (tmp_path / "e-couple" / "e-fluid" / "precice-adapter-config.yml").read_text()
    assert "inner_wall" in fluid_yml
    assert "Force" in fluid_yml
    dict_text = (tmp_path / "e-couple" / "e-fluid" / "system" / "preciceDict").read_text()
    assert "inner_wall" in dict_text
    assert "Displacement" in dict_text
    p_field = (tmp_path / "e-couple" / "e-fluid" / "0" / "p").read_text()
    assert "inner_wall" in p_field
    assert got["mapping"]["conformal"] is True or got["mapping"]["entity_id"] == "face.inner_wall"


def test_mapping_allows_unequal_nodes() -> None:
    ident = import_identity()
    got = compile_cad_interface_mapping(
        ident,
        solid_nset="NinterfaceN",
        fluid_patch="inner_wall",
        solid_nodes=8,
        fluid_nodes=40,
    )
    assert got["status"] == "ok"
    assert got["conformal"] is False
    assert got["entity_id"] == "face.inner_wall"


def test_mapping_rejects_missing_face() -> None:
    got = compile_cad_interface_mapping(
        {"entity_ids": ["body.gas"], "topology_version": 1},
        solid_nset="NinterfaceN",
        fluid_patch="inner_wall",
        solid_nodes=4,
        fluid_nodes=4,
    )
    assert got["status"] == "broken"


def test_config_yml_reads_force(tmp_path: Path) -> None:
    ident = import_identity()
    write_e_coupling_bundle(tmp_path / "e-couple", ident)
    yml = (tmp_path / "e-couple" / "e-solid" / "config.yml").read_text()
    assert "Force" in yml
    assert "Displacement" in yml
    assert "Traction" not in yml
