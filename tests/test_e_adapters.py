"""E adapter decks and CAD-face preCICE mapping. No solver launch."""

from pathlib import Path

from engineering_tools.e_adapter_calculix import CI_SOLID_MSH2, write_e_solid_inp
from engineering_tools.e_adapter_openfoam import fluid_adapter_load_detail, write_e_fluid_fields
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
    assert "*NSET, NSET=NlidRigid" in text
    assert "*RIGID BODY" not in text
    assert "1, 6" not in text
    assert "*ELEMENT, TYPE=C3D4, ELSET=Eshell" in text
    assert "C3D8" not in text
    assert "*CLOAD" in text
    assert "*COUPLED TEMPERATURE-DISPLACEMENT" in text
    assert "*DFLUX" in text
    assert "*CONDUCTIVITY" in text
    assert "*DYNAMIC" not in text
    # Adapter faces-mesh patch is "interface"; CalculiX looks up S+patch+T
    # before the step. Mesh name interface-faces is not that set.
    assert "*SURFACE, NAME=SINTERFACET, TYPE=ELEMENT" in text
    assert text.index("*SURFACE, NAME=SINTERFACET") < text.index("*STEP")
    assert text.index("*DFLUX") > text.index("*STEP")
    dflux_body = text.split("*DFLUX", 1)[1].split("*", 1)[0]
    surface_body = text.split("*SURFACE, NAME=SINTERFACET, TYPE=ELEMENT", 1)[1].split("*", 1)[0]
    dflux_faces = []
    for line in dflux_body.splitlines():
        line = line.strip()
        if not line:
            continue
        elem, face, flux = [part.strip() for part in line.split(",")]
        assert flux == "0."
        assert face in {"S1", "S2", "S3", "S4"}
        dflux_faces.append(f"{elem}, {face}")
    surface_faces = [line.strip() for line in surface_body.splitlines() if line.strip()]
    assert surface_faces
    assert surface_faces == dflux_faces
    assert len(got["node_ids"]) >= 3
    assert got["n_tets"] == 3
    assert got["lid_nodes"] == [7, 8, 9, 10]
    assert "*ELEMENT, TYPE=C3D4, ELSET=Elid" in text
    assert "*SOLID SECTION, ELSET=Elid, MATERIAL=Steel" in text
    # Fixture nodes 7-10 are the lid tet. Each constrained lid node has a C3D4 row.
    for nid in (7, 8, 9, 10):
        assert f"{nid}, 1, 3, 0." in text
    eshell = text.split("*ELEMENT, TYPE=C3D4, ELSET=Eshell", 1)[1].split("*ELEMENT", 1)[0]
    elid = text.split("*ELEMENT, TYPE=C3D4, ELSET=Elid", 1)[1].split("*", 1)[0]
    for nid in (7, 8, 9, 10):
        assert f", {nid}" not in eshell
    member: set[int] = set()
    for block in (eshell, elid):
        for line in block.splitlines():
            parts = [part.strip() for part in line.split(",") if part.strip()]
            if len(parts) >= 5 and parts[0].isdigit():
                member.update(int(part) for part in parts[1:5])
    assert {7, 8, 9, 10} <= member
    for line in text.splitlines():
        if ", 1, 3" not in line:
            continue
        nid = int(line.split(",", 1)[0].strip())
        assert nid in member
    assert "write_d_solid_inp" not in text
    assert "d-fsi sandwich" not in text


def test_solid_deck_missing_lid_volume_is_broken(tmp_path: Path) -> None:
    ident = import_identity()
    msh = tmp_path / "solid.msh"
    msh.write_text(
        CI_SOLID_MSH2.replace('3 2 "body.lid"\n', "").replace("$PhysicalNames\n3\n", "$PhysicalNames\n2\n"),
        encoding="utf-8",
    )
    got = write_e_solid_inp(tmp_path / "e-solid.inp", ident, msh=msh)
    assert got["status"] == "broken"
    assert "body.lid" in str(got.get("detail"))


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
    assert "read-data: [Force]" in yml
    assert "write-data" not in yml
    assert "Displacement" not in yml
    assert "Heat-Flux" in yml
    assert "faces-mesh: interface-faces" in yml
    assert "Traction" not in yml


def test_one_way_fluid_adapter_writes_heat_flux_and_does_not_read_displacement(tmp_path: Path) -> None:
    from engineering_tools.e_adapter_openfoam import write_e_precice_adapter_config
    from engineering_tools.e_backend_precice import generate_e_precice_config
    from engineering_tools.e_facade import _compile_live_policy

    xml_path = tmp_path / "precice-config.xml"
    xml_path.write_text(
        generate_e_precice_config(_compile_live_policy(windows=2, time_window=0.01)),
        encoding="utf-8",
    )
    write_e_precice_adapter_config(tmp_path, xml_path)
    text = (tmp_path / "system" / "preciceDict").read_text(encoding="utf-8")
    assert "Heat-Flux" in text
    assert "Force" in text
    assert "Temperature" in text
    assert "Displacement" not in text
    assert "readData" not in text
    assert "writeData" in text
    assert "Pressure" not in xml_path.read_text(encoding="utf-8")


def test_fluid_control_dict_aborts_when_the_adapter_library_is_missing(tmp_path: Path) -> None:
    write_e_fluid_fields(tmp_path, t_end_s=0.02, dt_s=0.01)
    control = (tmp_path / "system" / "controlDict").read_text(encoding="utf-8")
    assert "errors          strict;" in control
    assert "libpreciceAdapterFunctionObject.so" in control
    assert "preciceAdapterFunctionObject" in control


def test_fluid_log_names_the_missing_adapter_library() -> None:
    log = (
        'Could not load "libpreciceAdapterFunctionObject.so"\n'
        "Unknown function type preciceAdapterFunctionObject\n"
        "End\n"
    )
    detail = fluid_adapter_load_detail(log)
    assert detail is not None
    assert "libpreciceAdapterFunctionObject.so" in detail
    assert fluid_adapter_load_detail("End\n") is None
