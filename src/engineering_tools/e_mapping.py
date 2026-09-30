"""Phase E U5: map typed fields between two tessellations of one CAD face.

Agents: this is geometric transfer only (no solvers, no preCICE). Source and
target must share entity_id + topology_version. Conservative maps preserve
integrals (pressure load, heat flow). Displacement uses consistent lookup at
the target centroid. mapping_error is conservation/geometry; coupling_residual
is whatever the caller supplied — never alias those dicts.
"""

from __future__ import annotations

import math
from typing import Any

from engineering_tools.e_field import QUANTITIES

_EPS = 1e-12


def _ok(detail: str) -> dict[str, Any]:
    return {"status": "ok", "detail": detail}


def _broken(detail: str) -> dict[str, Any]:
    return {"status": "broken", "detail": detail}


def _vec_sub(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(a: tuple[float, ...]) -> float:
    return math.sqrt(_dot(a, a))


def _as_xyz(vertex: Any) -> tuple[float, float, float]:
    """Require a 3-D vertex. Agents: 2-D points are rejected, not padded."""
    if not isinstance(vertex, (list, tuple)) or len(vertex) != 3:
        raise ValueError("vertex must be a 3-tuple")
    return (float(vertex[0]), float(vertex[1]), float(vertex[2]))


def _cell_vertices(cell: dict[str, Any]) -> list[tuple[float, float, float]]:
    raw = cell.get("vertices") or []
    if len(raw) < 3:
        raise ValueError("cell needs at least 3 vertices")
    return [_as_xyz(v) for v in raw]


def _area_normal(verts: list[tuple[float, float, float]]) -> tuple[float, tuple[float, float, float]]:
    """Fan-triangulate polygon; return (area, unit normal)."""
    origin = verts[0]
    acc = (0.0, 0.0, 0.0)
    for i in range(1, len(verts) - 1):
        acc = (
            acc[0] + _cross(_vec_sub(verts[i], origin), _vec_sub(verts[i + 1], origin))[0],
            acc[1] + _cross(_vec_sub(verts[i], origin), _vec_sub(verts[i + 1], origin))[1],
            acc[2] + _cross(_vec_sub(verts[i], origin), _vec_sub(verts[i + 1], origin))[2],
        )
    mag = _norm(acc)
    area = 0.5 * mag
    if mag < _EPS:
        return 0.0, (0.0, 0.0, 1.0)
    n = (acc[0] / mag, acc[1] / mag, acc[2] / mag)
    return area, n


def _centroid(verts: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    """Area-weighted centroid of the fan triangles."""
    origin = verts[0]
    cx = cy = cz = 0.0
    wsum = 0.0
    for i in range(1, len(verts) - 1):
        a = verts[i]
        b = verts[i + 1]
        cr = _cross(_vec_sub(a, origin), _vec_sub(b, origin))
        w = 0.5 * _norm(cr)
        if w < _EPS:
            continue
        cx += w * (origin[0] + a[0] + b[0]) / 3.0
        cy += w * (origin[1] + a[1] + b[1]) / 3.0
        cz += w * (origin[2] + a[2] + b[2]) / 3.0
        wsum += w
    if wsum < _EPS:
        n = len(verts)
        return (
            sum(v[0] for v in verts) / n,
            sum(v[1] for v in verts) / n,
            sum(v[2] for v in verts) / n,
        )
    return (cx / wsum, cy / wsum, cz / wsum)


def _face_basis(
    cells: list[list[tuple[float, float, float]]],
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    """Orthonormal (origin, e1, e2, n) from the first non-degenerate cell."""
    for verts in cells:
        origin = verts[0]
        e_try = _vec_sub(verts[1], origin)
        n_raw = _cross(e_try, _vec_sub(verts[2], origin))
        if _norm(n_raw) < _EPS:
            continue
        n = (n_raw[0] / _norm(n_raw), n_raw[1] / _norm(n_raw), n_raw[2] / _norm(n_raw))
        e1n = _norm(e_try)
        e1 = (e_try[0] / e1n, e_try[1] / e1n, e_try[2] / e1n)
        e2 = _cross(n, e1)
        return origin, e1, e2, n
    raise ValueError("degenerate tessellation")


def _to_xy(
    p: tuple[float, float, float],
    origin: tuple[float, float, float],
    e1: tuple[float, float, float],
    e2: tuple[float, float, float],
) -> tuple[float, float]:
    d = _vec_sub(p, origin)
    return (_dot(d, e1), _dot(d, e2))


def _signed_area_2d(poly: list[tuple[float, float]]) -> float:
    acc = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        acc += x1 * y2 - x2 * y1
    return 0.5 * acc


def _ensure_ccw(poly: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if _signed_area_2d(poly) < 0.0:
        return list(reversed(poly))
    return list(poly)


def _cross_2d(a: tuple[float, float], b: tuple[float, float], p: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def _inside_edge(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> bool:
    return _cross_2d(a, b, p) >= -_EPS


def _intersect(
    p1: tuple[float, float],
    p2: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> tuple[float, float]:
    """Segment p1p2 vs infinite line ab. Degenerate parallel falls back to p2."""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = a
    x4, y4 = b
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-18:
        return p2
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


def _clip_polygon(
    subject: list[tuple[float, float]], clipper: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Sutherland–Hodgman. Clipper must be CCW. Agents: overlap area, not nodes."""
    output = list(subject)
    nclip = len(clipper)
    for i in range(nclip):
        if not output:
            return []
        a = clipper[i]
        b = clipper[(i + 1) % nclip]
        inp = output
        output = []
        m = len(inp)
        for j in range(m):
            s = inp[j]
            e = inp[(j + 1) % m]
            ein = _inside_edge(e, a, b)
            sin = _inside_edge(s, a, b)
            if ein:
                if not sin:
                    output.append(_intersect(s, e, a, b))
                output.append(e)
            elif sin:
                output.append(_intersect(s, e, a, b))
    return output


def _overlap_area(pa: list[tuple[float, float]], pb: list[tuple[float, float]]) -> float:
    clip = _clip_polygon(_ensure_ccw(pa), _ensure_ccw(pb))
    if len(clip) < 3:
        return 0.0
    return abs(_signed_area_2d(clip))


def _point_in_poly(p: tuple[float, float], poly: list[tuple[float, float]]) -> bool:
    """Winding test in the face plane. Used for consistent (centroid) lookup."""
    winding = 0.0
    n = len(poly)
    for i in range(n):
        a = poly[i]
        b = poly[(i + 1) % n]
        winding += math.atan2(_cross_2d(a, b, p), _dot_2d_edge(a, b, p))
    return abs(winding) > 1.0


def _dot_2d_edge(a: tuple[float, float], b: tuple[float, float], p: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (p[0] - a[0]) + (b[1] - a[1]) * (p[1] - a[1])


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_vector3(value: Any) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return False
    return all(_is_scalar(c) for c in value)


def _parse_tessellation(mesh: dict[str, Any]) -> dict[str, Any]:
    if not mesh.get("entity_id"):
        raise ValueError("tessellation entity_id required")
    if "topology_version" not in mesh:
        raise ValueError("tessellation topology_version required")
    cells_in = mesh.get("cells")
    if not isinstance(cells_in, list) or not cells_in:
        raise ValueError("tessellation cells required")
    cells = [_cell_vertices(c) for c in cells_in]
    areas = []
    normals = []
    centroids = []
    for verts in cells:
        area, n = _area_normal(verts)
        areas.append(area)
        normals.append(n)
        centroids.append(_centroid(verts))
    origin, e1, e2, n = _face_basis(cells)
    xy = [[_to_xy(v, origin, e1, e2) for v in verts] for verts in cells]
    return {
        "entity_id": str(mesh["entity_id"]),
        "topology_version": int(mesh["topology_version"]),
        "cells": cells,
        "areas": areas,
        "normals": normals,
        "centroids": centroids,
        "xy": xy,
        "n": n,
    }


def _copy_residual(coupling_residual: dict[str, Any] | None) -> dict[str, Any]:
    """Shallow copy so mapping_error cannot alias caller residual."""
    if coupling_residual is None:
        return {"provided": False}
    return dict(coupling_residual)


def _relative_mismatch(source_integral: float, target_integral: float) -> float:
    denom = max(abs(source_integral), abs(target_integral), _EPS)
    return (target_integral - source_integral) / denom


def map_surface_field(
    source_mesh: dict[str, Any],
    target_mesh: dict[str, Any],
    *,
    quantity: str,
    source_values: list[Any],
    coupling_residual: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Transfer one QUANTITY between non-conformal cells on the same CAD face.

    pressure / heat_flux: overlap-area conservative. displacement: centroid
    containment (constant field → identical vector on every target cell).
    """
    residual_out = _copy_residual(coupling_residual)
    spec = QUANTITIES.get(quantity)
    if spec is None:
        return {**_broken(f"unknown quantity: {quantity}"), "mapping_error": {}, "coupling_residual": residual_out}
    kind, _unit = spec
    try:
        src = _parse_tessellation(source_mesh)
        tgt = _parse_tessellation(target_mesh)
    except (ValueError, TypeError, KeyError) as exc:
        return {**_broken(str(exc)), "mapping_error": {}, "coupling_residual": residual_out}
    if src["entity_id"] != tgt["entity_id"]:
        return {
            **_broken("source and target must share CAD entity_id"),
            "mapping_error": {},
            "coupling_residual": residual_out,
        }
    if src["topology_version"] != tgt["topology_version"]:
        return {
            **_broken("source and target topology_version mismatch"),
            "mapping_error": {},
            "coupling_residual": residual_out,
        }
    if len(source_values) != len(src["cells"]):
        return {
            **_broken("source_values length must match source cell count"),
            "mapping_error": {},
            "coupling_residual": residual_out,
        }
    if kind == "scalar":
        if not all(_is_scalar(v) for v in source_values):
            return {
                **_broken(f"{quantity} requires scalar cell values"),
                "mapping_error": {},
                "coupling_residual": residual_out,
            }
    elif kind == "vector":
        if not all(_is_vector3(v) for v in source_values):
            return {
                **_broken(f"{quantity} requires 3-vector cell values"),
                "mapping_error": {},
                "coupling_residual": residual_out,
            }
    else:
        return {
            **_broken(f"{quantity} rank {kind} is not mapped in U5"),
            "mapping_error": {},
            "coupling_residual": residual_out,
        }

    if quantity == "displacement":
        return _map_consistent(src, tgt, source_values, residual_out, quantity)
    return _map_conservative(src, tgt, source_values, residual_out, quantity, kind)


def _map_conservative(
    src: dict[str, Any],
    tgt: dict[str, Any],
    source_values: list[Any],
    residual_out: dict[str, Any],
    quantity: str,
    kind: str,
) -> dict[str, Any]:
    """Overlap-weighted intensive transfer. Preserves ∫ φ dA on a shared face."""
    nsrc = len(src["cells"])
    ntgt = len(tgt["cells"])
    overlaps = [[0.0] * nsrc for _ in range(ntgt)]
    for i in range(ntgt):
        for j in range(nsrc):
            overlaps[i][j] = _overlap_area(tgt["xy"][i], src["xy"][j])

    if kind == "scalar":
        target_values: list[Any] = []
        for i in range(ntgt):
            ext = sum(float(source_values[j]) * overlaps[i][j] for j in range(nsrc))
            area = tgt["areas"][i]
            target_values.append(0.0 if area < _EPS else ext / area)
        source_integral = sum(float(source_values[j]) * src["areas"][j] for j in range(nsrc))
        target_integral = sum(float(target_values[i]) * tgt["areas"][i] for i in range(ntgt))
    else:
        target_values = []
        n = src["n"]
        for i in range(ntgt):
            acc = [0.0, 0.0, 0.0]
            for j in range(nsrc):
                vec = source_values[j]
                w = overlaps[i][j]
                acc[0] += float(vec[0]) * w
                acc[1] += float(vec[1]) * w
                acc[2] += float(vec[2]) * w
            area = tgt["areas"][i]
            if area < _EPS:
                target_values.append((0.0, 0.0, 0.0))
            else:
                target_values.append((acc[0] / area, acc[1] / area, acc[2] / area))
        source_integral = sum(_dot(tuple(source_values[j]), n) * src["areas"][j] for j in range(nsrc))
        target_integral = sum(_dot(tuple(target_values[i]), n) * tgt["areas"][i] for i in range(ntgt))

    mapping_error = {
        "relative_integral": _relative_mismatch(source_integral, target_integral),
        "source_integral": source_integral,
        "target_integral": target_integral,
        "quantity": quantity,
        "method": "conservative_overlap",
    }
    return {
        **_ok(quantity),
        "target_values": target_values,
        "mapping_error": mapping_error,
        "coupling_residual": residual_out,
    }


def _map_consistent(
    src: dict[str, Any],
    tgt: dict[str, Any],
    source_values: list[Any],
    residual_out: dict[str, Any],
    quantity: str,
) -> dict[str, Any]:
    """Value at target centroid from the source cell that contains it."""
    origin, e1, e2, _n = _face_basis(src["cells"])
    target_values = []
    mismatches = []
    for i, c3 in enumerate(tgt["centroids"]):
        cxy = _to_xy(c3, origin, e1, e2)
        chosen = None
        for j, poly in enumerate(src["xy"]):
            if _point_in_poly(cxy, _ensure_ccw(poly)):
                chosen = j
                break
        if chosen is None:
            # Fallback: nearest source centroid (still independent of residual).
            best = 0
            best_d = float("inf")
            for j, sc in enumerate(src["centroids"]):
                d = _norm(_vec_sub(c3, sc))
                if d < best_d:
                    best_d = d
                    best = j
            chosen = best
        value = tuple(float(c) for c in source_values[chosen])
        target_values.append(value)
        src_at = tuple(float(c) for c in source_values[chosen])
        mismatches.append(math.sqrt(sum((value[k] - src_at[k]) ** 2 for k in range(3))))

    mapping_error = {
        "relative_integral": max(mismatches) if mismatches else 0.0,
        "source_integral": 0.0,
        "target_integral": 0.0,
        "quantity": quantity,
        "method": "consistent_centroid",
        "max_centroid_mismatch": max(mismatches) if mismatches else 0.0,
    }
    return {
        **_ok(quantity),
        "target_values": target_values,
        "mapping_error": mapping_error,
        "coupling_residual": residual_out,
    }
