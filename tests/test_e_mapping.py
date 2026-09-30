"""Phase E U5: conservative/consistent mapping on one CAD face. No solvers."""

from engineering_tools.e_field import QUANTITIES
from engineering_tools.e_mapping import map_surface_field


def _square_two_triangles(entity_id: str = "face.wall") -> dict:
    """Unit square split into two triangles (source-style tessellation)."""
    return {
        "entity_id": entity_id,
        "topology_version": 1,
        "cells": [
            {"cell_id": "t0", "vertices": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0)]},
            {"cell_id": "t1", "vertices": [(0.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]},
        ],
    }


def _square_one_quad(entity_id: str = "face.wall") -> dict:
    """Same unit square as a single quad (non-conformal vs triangles)."""
    return {
        "entity_id": entity_id,
        "topology_version": 1,
        "cells": [
            {
                "cell_id": "q0",
                "vertices": [
                    (0.0, 0.0, 0.0),
                    (1.0, 0.0, 0.0),
                    (1.0, 1.0, 0.0),
                    (0.0, 1.0, 0.0),
                ],
            }
        ],
    }


def _square_four_quads(entity_id: str = "face.wall") -> dict:
    """Same unit square as four 0.5×0.5 quads."""
    cells = []
    idx = 0
    for i in range(2):
        for j in range(2):
            x0, y0 = 0.5 * i, 0.5 * j
            cells.append(
                {
                    "cell_id": f"q{idx}",
                    "vertices": [
                        (x0, y0, 0.0),
                        (x0 + 0.5, y0, 0.0),
                        (x0 + 0.5, y0 + 0.5, 0.0),
                        (x0, y0 + 0.5, 0.0),
                    ],
                }
            )
            idx += 1
    return {"entity_id": entity_id, "topology_version": 1, "cells": cells}


def test_constant_pressure_preserves_integrated_load() -> None:
    """force = p * area is conserved under conservative pressure map."""
    p = 2500.0
    source = _square_two_triangles()
    target = _square_four_quads()
    got = map_surface_field(
        source,
        target,
        quantity="pressure",
        source_values=[p, p],
        coupling_residual={"l2": 0.12, "iteration": 4},
    )
    assert got["status"] == "ok"
    face_area = 1.0
    expected_force = p * face_area
    target_force = sum(v * 0.25 for v in got["target_values"])
    rel = abs(target_force - expected_force) / expected_force
    assert rel < 1e-9
    assert abs(got["mapping_error"]["relative_integral"]) < 1e-9


def test_heat_flux_preserves_integrated_heat_flow() -> None:
    q = (0.0, 0.0, 80.0)
    source = _square_one_quad()
    target = _square_two_triangles()
    got = map_surface_field(
        source,
        target,
        quantity="heat_flux",
        source_values=[q],
        coupling_residual={"l2": 1e-4},
    )
    assert got["status"] == "ok"
    # n = +z on this face → q·n * area = 80 * 1
    expected_flow = 80.0
    rel = abs(got["mapping_error"]["target_integral"] - expected_flow) / expected_flow
    assert rel < 1e-9
    assert abs(got["mapping_error"]["relative_integral"]) < 1e-9


def test_constant_displacement_matches_at_corresponding_centroids() -> None:
    u = (0.003, -0.001, 0.0)
    source = _square_one_quad()
    target = _square_two_triangles()
    got = map_surface_field(
        source,
        target,
        quantity="displacement",
        source_values=[u],
        coupling_residual={"l2": 0.0},
    )
    assert got["status"] == "ok"
    for value in got["target_values"]:
        assert value == u or (
            abs(value[0] - u[0]) < 1e-12
            and abs(value[1] - u[1]) < 1e-12
            and abs(value[2] - u[2]) < 1e-12
        )


def test_wrong_dimensions_fail_broken() -> None:
    source = _square_two_triangles()
    target = _square_one_quad()
    # pressure is scalar per QUANTITIES
    assert QUANTITIES["pressure"][0] == "scalar"
    bad_p = map_surface_field(
        source,
        target,
        quantity="pressure",
        source_values=[(1.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
    )
    assert bad_p["status"] == "broken"
    # displacement is vector
    assert QUANTITIES["displacement"][0] == "vector"
    bad_u = map_surface_field(
        source,
        target,
        quantity="displacement",
        source_values=[1.0, 1.0],
    )
    assert bad_u["status"] == "broken"


def test_mapping_error_independent_from_coupling_residual() -> None:
    residual = {"l2": 0.08, "iteration": 2}
    got = map_surface_field(
        _square_two_triangles(),
        _square_one_quad(),
        quantity="pressure",
        source_values=[10.0, 10.0],
        coupling_residual=residual,
    )
    assert got["status"] == "ok"
    assert "mapping_error" in got
    assert "coupling_residual" in got
    assert got["mapping_error"] is not got["coupling_residual"]
    assert got["coupling_residual"] is not residual
    assert got["coupling_residual"]["l2"] == 0.08
    assert "relative_integral" in got["mapping_error"]
    got["mapping_error"]["l2"] = "should-not-alias"
    assert residual["l2"] == 0.08
    assert got["coupling_residual"]["l2"] == 0.08
    got["coupling_residual"]["iteration"] = 99
    assert residual["iteration"] == 2
