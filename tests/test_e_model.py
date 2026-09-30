"""Phase E canonical model schema tests. No solvers."""

from engineering_tools.e_field import validate_field
from engineering_tools.e_material import validate_material
from engineering_tools.e_model import dumps_model, empty_model, loads_model, validate_model
from engineering_tools.e_region import validate_region


def _face(entity_id: str = "face.wall") -> dict:
    return {"entity_id": entity_id, "kind": "face", "topology_version": 1}


def _displacement() -> dict:
    return {
        "field_id": "solid.displacement",
        "quantity": "displacement",
        "kind": "vector",
        "si_unit": "m",
        "frame_id": "cad",
        "support_entity_id": "face.wall",
        "owner_participant": "Solid",
        "consumer_participants": ["Fluid"],
        "mapping_method": "consistent",
        "extent": "intensive",
        "conservation": "none",
    }


def _traction() -> dict:
    return {
        "field_id": "fluid.traction",
        "quantity": "traction",
        "kind": "vector",
        "si_unit": "Pa",
        "frame_id": "cad",
        "support_entity_id": "face.wall",
        "owner_participant": "Fluid",
        "consumer_participants": ["Solid"],
        "mapping_method": "conservative",
        "extent": "intensive",
        "conservation": "force",
    }


def test_elastoplastic_solid_is_schema_valid() -> None:
    mat = {
        "material_id": "steel",
        "constitutive_model": "elastoplastic",
    }
    assert validate_material(mat)["status"] == "ok"
    region = {
        "region_id": "shell",
        "entity_id": "body.shell",
        "material_id": "steel",
        "physics_models": ["deformable_solid"],
        "motion_model": "deformable_motion",
    }
    assert validate_region(region)["status"] == "ok"


def test_rigid_body_is_schema_valid() -> None:
    mat = {"material_id": "clamp", "constitutive_model": "rigid"}
    region = {
        "region_id": "lid",
        "entity_id": "body.lid",
        "material_id": "clamp",
        "physics_models": ["rigid_body"],
        "motion_model": "prescribed_rigid_motion",
    }
    assert validate_material(mat)["status"] == "ok"
    assert validate_region(region)["status"] == "ok"


def test_compressible_gas_with_eos_is_schema_valid() -> None:
    mat = {"material_id": "air", "constitutive_model": "linear_elastic", "equation_of_state": "perfect_gas"}
    region = {
        "region_id": "cavity",
        "entity_id": "body.gas",
        "material_id": "air",
        "physics_models": ["compressible_fluid"],
        "motion_model": "fixed",
        "equation_of_state": "perfect_gas",
    }
    assert validate_material(mat)["status"] == "ok"
    assert validate_region(region)["status"] == "ok"


def test_thermal_material_temperature_properties() -> None:
    mat = {
        "material_id": "alloy",
        "constitutive_model": "temperature_dependent_elastic",
        "temperature_properties": ["E(T)", "k(T)"],
    }
    assert validate_material(mat)["status"] == "ok"


def test_incompatible_field_dimensions_fail() -> None:
    bad = _displacement()
    bad["si_unit"] = "Pa"
    assert validate_field(bad)["status"] == "broken"


def test_missing_owner_or_support_fails() -> None:
    field = _displacement()
    field["owner_participant"] = ""
    assert validate_field(field)["status"] == "broken"
    field = _displacement()
    field["support_entity_id"] = ""
    assert validate_field(field)["status"] == "broken"


def test_unsupported_live_capability_does_not_invalidate_model() -> None:
    """Brittle damage is schema-ok; adapters may still report missing."""
    mat = {"material_id": "ceramic", "constitutive_model": "damage_brittle"}
    assert validate_material(mat)["status"] == "ok"
    model = empty_model()
    model["entities"] = [_face(), {"entity_id": "body.ceramic", "kind": "body", "topology_version": 1}]
    model["materials"] = [mat]
    model["regions"] = [
        {
            "region_id": "ceramic",
            "entity_id": "body.ceramic",
            "material_id": "ceramic",
            "physics_models": ["deformable_solid"],
            "motion_model": "deformable_motion",
        }
    ]
    model["fields"] = [_displacement(), _traction()]
    assert validate_model(model)["status"] == "ok"


def test_model_json_round_trip_preserves_ids() -> None:
    model = empty_model()
    model["entities"] = [_face()]
    model["fields"] = [_displacement(), _traction()]
    text = dumps_model(model)
    loaded = loads_model(text)
    assert loaded["fields"][0]["field_id"] == "solid.displacement"
    assert loaded["entities"][0]["entity_id"] == "face.wall"
