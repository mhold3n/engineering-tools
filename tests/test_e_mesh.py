"""Phase E discretization graph tests. Synthetic mesh metadata only; no Gmsh."""

from engineering_tools.e_mesh import validate_interface_meshes, validate_mesh


def _mesh(
    *,
    mesh_id: str = "fluid.wall",
    participant: str = "Fluid",
    topology_version: int = 1,
    entity_id: str | None = "face.wall",
    mesh_set: str = "patch.wall",
    node_count: int = 12,
) -> dict:
    bindings = []
    if entity_id is not None:
        bindings.append(
            {
                "entity_id": entity_id,
                "mesh_set": mesh_set,
                "node_count": node_count,
            }
        )
    return {
        "mesh_id": mesh_id,
        "participant": participant,
        "topology_version": topology_version,
        "bindings": bindings,
        "quality": {"min_quality": 0.4, "max_skewness": 0.8},
        "refinement": {"boundary_layer": True, "levels": 2},
    }


def test_mesh_record_stores_required_fields() -> None:
    record = _mesh()
    got = validate_mesh(record, current_topology_version=1)
    assert got["status"] == "ok"
    assert record["mesh_id"] == "fluid.wall"
    assert record["participant"] == "Fluid"
    assert record["topology_version"] == 1
    assert record["bindings"][0]["entity_id"] == "face.wall"
    assert "quality" in record
    assert "refinement" in record


def test_unequal_interface_node_counts_on_same_canonical_face_are_valid() -> None:
    fluid = _mesh(mesh_id="fluid.iface", participant="Fluid", node_count=40)
    solid = _mesh(mesh_id="solid.iface", participant="Solid", node_count=9)
    got = validate_interface_meshes(
        [fluid, solid],
        canonical_face_id="face.wall",
        current_topology_version=1,
    )
    assert got["status"] == "ok"


def test_missing_canonical_face_binding_is_broken() -> None:
    record = _mesh(entity_id=None)
    got = validate_mesh(record, current_topology_version=1)
    assert got["status"] == "broken"
    empty_bind = _mesh()
    empty_bind["bindings"] = [{"entity_id": "", "mesh_set": "patch.wall", "node_count": 4}]
    got = validate_mesh(empty_bind, current_topology_version=1)
    assert got["status"] == "broken"


def test_stale_topology_version_mesh_is_broken() -> None:
    record = _mesh(topology_version=1)
    got = validate_mesh(record, current_topology_version=2)
    assert got["status"] == "broken"
