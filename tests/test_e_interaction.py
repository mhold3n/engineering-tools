"""CFD-FEA wall interaction.

Agents: these tests observe the step a caller can run. They do not import
the facade or generate preCICE XML. A missing unit fails. An unknown name
stays on the record. Solid displacement toward the fluid fails.
"""

from __future__ import annotations

from engineering_tools.e_interaction import interaction_step


def test_wall_item_missing_unit_fails() -> None:
    step = interaction_step(wall_items=[{"name": "force", "value": [0.0, 0.0, 1.0]}])
    assert step["status"] == "broken"
    assert "unit" in step["detail"]


def test_unknown_wall_quantity_is_kept_and_not_emitted() -> None:
    step = interaction_step(
        wall_items=[{"name": "wall_shear_stress", "value": [1.0, 0.0, 0.0], "unit": "Pa"}]
    )
    assert step["status"] == "ok"
    assert step["wall"] == [
        {
            "name": "wall_shear_stress",
            "value": [1.0, 0.0, 0.0],
            "unit": "Pa",
            "emission": "not_emitted",
        }
    ]
    assert step["exchanges"] == []
    assert step["participants"][0]["name"] == "Fluid"
    assert step["solid_updates_fluid_mesh"] is False


def test_static_steady_and_dynamic_stop_rules() -> None:
    force = {"name": "force", "value": [0.0, 0.0, 1.0], "unit": "N"}
    static = interaction_step(wall_items=[force], stop_rule="static")
    assert static["status"] == "ok"
    assert static["stop"] == {"rule": "static", "steps": 1, "continue": False}

    first = interaction_step(wall_items=[force], stop_rule="steady")
    assert first["stop"]["continue"] is True
    repeated = interaction_step(
        wall_items=[force],
        stop_rule="steady",
        previous_wall=first["wall"],
    )
    assert repeated["stop"]["continue"] is False
    changed = interaction_step(
        wall_items=[{"name": "force", "value": [0.0, 0.0, 2.0], "unit": "N"}],
        stop_rule="steady",
        previous_wall=first["wall"],
    )
    assert changed["stop"]["continue"] is True

    bad_clock = interaction_step(
        wall_items=[force],
        stop_rule="dynamic",
        window_dt_s=0.01,
        fluid_dt_s=0.003,
    )
    assert bad_clock["status"] == "broken"
    assert "integer multiple" in bad_clock["detail"]
    good_clock = interaction_step(
        wall_items=[force],
        stop_rule="dynamic",
        window_dt_s=0.01,
        fluid_dt_s=0.002,
    )
    assert good_clock["status"] == "ok"
    assert good_clock["stop"]["clock"]["participants"]["Fluid"]["subcycles"] == 5


def test_prescribed_spin_is_stored_on_the_fluid_region() -> None:
    step = interaction_step(
        wall_items=[{"name": "force", "value": [0.0, 0.0, 1.0], "unit": "N"}],
        prescribed_spin={"origin": [0.0, 0.0, 0.0], "axis": [0.0, 0.0, 1.0], "schedule": [[0.0, 0.0], [1.0, 1.0]]},
    )
    assert step["status"] == "ok"
    assert step["fluid_region"]["motion_model"] == "prescribed_rigid_motion"
    assert step["fluid_region"]["prescribed_spin"] == {
        "origin": [0.0, 0.0, 0.0],
        "axis": [0.0, 0.0, 1.0],
        "schedule": [[0.0, 0.0], [1.0, 1.0]],
    }
    missing = interaction_step(
        prescribed_spin={"origin": [0.0, 0.0, 0.0], "axis": [0.0, 0.0, 1.0]},
    )
    assert missing["status"] == "broken"
    assert "schedule" in missing["detail"]


def test_solid_to_fluid_displacement_fails() -> None:
    step = interaction_step(
        wall_items=[{"name": "force", "value": [0.0, 0.0, 1.0], "unit": "N"}],
        exchanges=[{"quantity": "displacement", "from": "Solid", "to": "Fluid"}],
    )
    assert step["status"] == "broken"
    assert "displacement" in step["detail"]
