"""Phase E discretization-stability comparator (U11).

Agents: compare_refinement does not launch solvers. mapping_residual is
cross-solver pressure-load vector conservation over fluid L1 scale, not
pre/post preCICE Force arrays. L1-to-L1 is load_magnitude_consistency only.
Do not read thermal ICs. Do not treat max_iterations as physical time.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from engineering_tools.c_backend_precice import WINDOW_COMPLETED_MARK

ENTITY = "face.inner_wall"
RELATIVE_TOLERANCE = 0.2
MAPPING_CONSERVATION_TOLERANCE = 0.05
# Same applied-load convention (solid FORC / CLOAD vs fluid p*Sf). Not inferred from nets.
FORCE_SIGN = 1
# Denominator floor so closed-cylinder net cancellation does not explode residual.
L1_FLOOR_N = 1e-9
MAPPING_RESIDUAL_FORMULA = (
    "||sum(F_solid)-(+1)*sum(F_fluid)||_2 / max(sum_f ||F_fluid||_2, 1e-9 N)"
)
MAPPING_RESIDUAL_CONVENTION = "cross_solver_pressure_load_consistency"
MAPPING_RESIDUAL_KIND = "vector_sum_over_source_l1"
LOAD_MAGNITUDE_FORMULA = (
    "|sum_n ||F_solid,n|| - sum_f ||F_fluid,f||| / max(sum_n ||F_solid,n||, sum_f ||F_fluid,f||)"
)
QUANTITY_SPECS = (
    ("integrated_interface_force", "N", "integrated_traction_magnitude"),
    ("max_interface_displacement", "m", "max_magnitude"),
    ("mapping_residual", "1", MAPPING_RESIDUAL_KIND),
)
_SPATIAL_H = (0.012, 0.006)
_TEMPORAL = {"coarse_dt": 0.01, "fine_dt": 0.005, "t_end": 0.02, "coarse_windows": 2, "fine_windows": 4}
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_SERIAL_TOL = 1e-9
_PROBLEM_KEYS = (
    "cad_fingerprint",
    "topology_version",
    "materials",
    "boundary_conditions",
    "loads",
    "coupling_kind",
    "convergence_measures",
    "aitken_data",
    "aitken_initial_relaxation",
    "max_iterations",
    "t_end",
    "entity_id",
    "effective_solver_pressure_Pa",
)


def dumps_report(report: dict[str, Any]) -> str:
    """Strict JSON. NaN/Inf must not serialize as success artifacts."""
    return json.dumps(report, indent=2, sort_keys=True, allow_nan=False)


def parse_backend_version(tool: str, text: str | None) -> str | None:
    """Pure parser. Host environment is not consulted."""
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    if tool == "gmsh":
        if re.fullmatch(r"\d+\.\d+(?:\.\d+)?", raw):
            return raw
        match = re.match(r"^(\d+\.\d+(?:\.\d+)?)\b", raw)
        return match.group(1) if match else None
    if tool == "calculix":
        if re.fullmatch(r"\d+\.\d+(?:\.\d+)?", raw):
            return raw
        match = re.search(r"(?im)^\s*(?:This is\s+)?Version\s+(\d+\.\d+(?:\.\d+)?)\s*$", raw)
        if match:
            return match.group(1)
        match = re.search(r"(?i)\bVersion\s+(\d+\.\d+(?:\.\d+)?)", raw)
        return match.group(1) if match else None
    if tool == "openfoam":
        if re.match(r"(?i)usage:", raw):
            return None
        banner = re.search(r"(?i)Version:\s*(v?\d[\w.+-]*)", raw)
        if banner:
            return banner.group(1).rstrip(",")
        if re.fullmatch(r"v?\d{4}", raw):
            return raw
        return None
    if tool == "precice":
        if re.fullmatch(r"\d+\.\d+(?:\.\d+)?", raw):
            return raw
        for line in raw.splitlines():
            if "WARNING" in line.upper() or "deprecated" in line.lower():
                continue
            token = line.strip()
            if re.fullmatch(r"\d+\.\d+(?:\.\d+)?", token):
                return token
        return None
    return None


def _vec3(raw: Any) -> tuple[float, float, float] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        return None
    try:
        vec = (float(raw[0]), float(raw[1]), float(raw[2]))
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(axis) for axis in vec):
        return None
    return vec


def _norm2(vec: tuple[float, float, float]) -> float:
    return math.sqrt(vec[0] * vec[0] + vec[1] * vec[1] + vec[2] * vec[2])


def load_magnitude_consistency(solid_l1: float, fluid_l1: float) -> float | None:
    """Diagnostic |L1_s-L1_f|/max(L1). Not vector conservation."""
    if not math.isfinite(solid_l1) or not math.isfinite(fluid_l1) or solid_l1 < 0 or fluid_l1 < 0:
        return None
    num = abs(solid_l1 - fluid_l1)
    denom = max(solid_l1, fluid_l1)
    if denom == 0.0:
        return 0.0 if num == 0.0 else None
    return num / denom


def vector_conservation_residual(
    *,
    solid_net: tuple[float, float, float],
    fluid_net: tuple[float, float, float],
    source_l1: float,
    sign: int = FORCE_SIGN,
) -> float | None:
    """||Fs - sign Ff|| / max(source L1, floor). Fluid L1 is the Force-write scale."""
    if sign not in (-1, 1) or not math.isfinite(source_l1) or source_l1 < 0:
        return None
    delta = (
        solid_net[0] - sign * fluid_net[0],
        solid_net[1] - sign * fluid_net[1],
        solid_net[2] - sign * fluid_net[2],
    )
    num = _norm2(delta)
    denom = max(source_l1, L1_FLOOR_N)
    if not math.isfinite(num) or not math.isfinite(denom) or denom <= 0:
        return None
    return num / denom


def mapping_l1_residual(solid: dict[str, Any] | None, fluid: dict[str, Any] | None) -> float | None:
    """Backward name: vector conservation using nested load records."""
    return residual_from_source_rows(solid, fluid)


def residual_from_source_rows(solid: dict[str, Any] | None, fluid: dict[str, Any] | None) -> float | None:
    if not isinstance(solid, dict) or not isinstance(fluid, dict):
        return None
    solid_net = _vec3(solid.get("net_components_N") or solid.get("components_N"))
    fluid_net = _vec3(fluid.get("net_components_N") or fluid.get("components_N"))
    try:
        source_l1 = float(fluid.get("l1_N"))
    except (TypeError, ValueError):
        return None
    if solid_net is None or fluid_net is None:
        return None
    return vector_conservation_residual(solid_net=solid_net, fluid_net=fluid_net, source_l1=source_l1)


def residual_from_mapping_row(row: dict[str, Any]) -> float | None:
    solid = {"components_N": row.get("solid_components_N"), "l1_N": row.get("solid_l1_N")}
    fluid = {"components_N": row.get("fluid_components_N"), "l1_N": row.get("fluid_l1_N")}
    return residual_from_source_rows(solid, fluid)


def force_conservation_residual(
    solid: dict[str, Any] | None,
    fluid: dict[str, Any] | None,
) -> float | None:
    """Live façade alias: vector conservation, FORCE_SIGN=+1."""
    return residual_from_source_rows(solid, fluid)


def relative_change(coarse: float, fine: float) -> tuple[float | None, str]:
    """Declared formula: abs(fine-coarse)/abs(fine). Overflow returns undefined."""
    if coarse == 0.0 and fine == 0.0:
        return 0.0, "ok"
    if fine == 0.0:
        return None, "undefined"
    try:
        rel = abs(fine - coarse) / abs(fine)
    except (OverflowError, ZeroDivisionError):
        return None, "overflow"
    if not math.isfinite(rel):
        return None, "overflow"
    return rel, "ok"


def _fail(kind: str, differences: list[str], **extra: Any) -> dict[str, Any]:
    payload = {
        "ok": False,
        "record_valid": extra.pop("record_valid", False),
        "within_tolerance": extra.pop("within_tolerance", False),
        "kind": kind,
        "same_problem_definition": extra.pop("same_problem_definition", False),
        "differences": differences,
        "validation_errors": extra.pop("validation_errors", list(differences)),
        "problem_definition_differences": extra.pop("problem_definition_differences", []),
        "refinement_contract_errors": extra.pop("refinement_contract_errors", []),
        "acceptance_failures": extra.pop("acceptance_failures", []),
        "quantities": extra.pop("quantities", []),
    }
    payload.update(extra)
    return payload


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _xyz_ok(points: Any, count: int) -> bool:
    if not isinstance(points, list) or len(points) != count or count <= 0:
        return False
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 3:
            return False
        if not all(_finite(axis) for axis in point):
            return False
    return True


def _problem(session: dict[str, Any]) -> dict[str, Any]:
    raw = session.get("problem")
    if isinstance(raw, dict) and raw:
        return dict(raw)
    return {}


def _disc(session: dict[str, Any]) -> dict[str, Any]:
    raw = session.get("discretization")
    if isinstance(raw, dict) and raw:
        return dict(raw)
    return {}


def _versions(session: dict[str, Any]) -> dict[str, Any]:
    prov = session.get("provenance") or {}
    raw = session.get("backend_versions") or prov.get("backend_versions") or {}
    return dict(raw) if isinstance(raw, dict) else {}


def _measurement(session: dict[str, Any], name: str) -> dict[str, Any] | None:
    block = (session.get("measurements") or {}).get(name)
    if isinstance(block, dict):
        return block
    return None


def _horizon_mismatch(dt: Any, windows: Any, t_end: Any) -> bool:
    try:
        return abs(float(dt) * int(windows) - float(t_end)) > 1e-12
    except (TypeError, ValueError):
        return True


def _problem_field_issues(problem: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    fingerprint = problem.get("cad_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint.strip():
        issues.append("cad_fingerprint")
    try:
        topology = int(problem.get("topology_version"))
    except (TypeError, ValueError):
        topology = 0
    if topology <= 0:
        issues.append("topology_version")
    materials = problem.get("materials")
    if not isinstance(materials, list) or not materials:
        issues.append("materials")
    bcs = problem.get("boundary_conditions")
    if not isinstance(bcs, dict):
        issues.append("boundary_conditions")
    else:
        canonical = bcs.get("canonical_bcs")
        if not isinstance(canonical, list) or not canonical:
            issues.append("boundary_conditions")
        else:
            for record in canonical:
                if not isinstance(record, dict) or not record.get("entity_id") or "value" not in record:
                    issues.append("boundary_conditions")
                    break
        adapter = bcs.get("adapter_constraints")
        if not isinstance(adapter, list) or not adapter:
            issues.append("boundary_conditions")
    loads = problem.get("loads")
    if not isinstance(loads, list) or not loads:
        issues.append("loads")
    else:
        for record in loads:
            if not isinstance(record, dict) or not record.get("entity_id"):
                issues.append("loads")
                break
    if not isinstance(problem.get("coupling_kind"), str) or not str(problem.get("coupling_kind")).strip():
        issues.append("coupling_kind")
    conv = problem.get("convergence_measures")
    if not isinstance(conv, dict) or not conv or "relative" not in conv:
        issues.append("convergence_measures")
    aitken = problem.get("aitken_data")
    if not isinstance(aitken, list) or not aitken:
        issues.append("aitken_data")
    if not _finite(problem.get("aitken_initial_relaxation")):
        issues.append("aitken_data")
    try:
        max_it = int(problem.get("max_iterations"))
    except (TypeError, ValueError):
        max_it = 0
    if max_it <= 0:
        issues.append("max_iterations")
    if not _finite(problem.get("t_end")) or float(problem.get("t_end") or 0) <= 0:
        issues.append("t_end")
    if problem.get("entity_id") != ENTITY:
        issues.append("entity_id")
    if not _finite(problem.get("effective_solver_pressure_Pa")) or float(problem.get("effective_solver_pressure_Pa") or 0) <= 0:
        issues.append("effective_solver_pressure_Pa")
    else:
        for record in loads if isinstance(loads, list) else []:
            if isinstance(record, dict) and record.get("quantity") == "pressure" and record.get("entity_id") == ENTITY:
                try:
                    declared = float(record.get("value"))
                except (TypeError, ValueError):
                    issues.append("effective_solver_pressure_Pa")
                    break
                if abs(declared - float(problem["effective_solver_pressure_Pa"])) > _SERIAL_TOL:
                    issues.append("effective_solver_pressure_Pa")
    return issues


def _disc_field_issues(disc: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    try:
        h_max = float(disc.get("h_max"))
    except (TypeError, ValueError):
        h_max = 0.0
    if not math.isfinite(h_max) or h_max <= 0:
        issues.append("h_max")
    for key in ("solid_mesh_id", "fluid_mesh_id"):
        if not isinstance(disc.get(key), str) or not _SHA256.match(str(disc.get(key))):
            issues.append(key)
    try:
        n_solid = int(disc.get("solid_interface_vertex_count"))
        n_fluid = int(disc.get("fluid_interface_facecenter_count"))
    except (TypeError, ValueError):
        issues.append("solid_interface_vertices")
        issues.append("fluid_interface_facecenters")
        return issues
    if not _xyz_ok(disc.get("solid_interface_vertices"), n_solid):
        issues.append("solid_interface_vertices")
    if not _xyz_ok(disc.get("fluid_interface_facecenters"), n_fluid):
        issues.append("fluid_interface_facecenters")
    return issues


def _session_state_issues(session: dict[str, Any], label: str) -> list[str]:
    issues: list[str] = []
    if session.get("status") != "ok" or session.get("e_ok") is not True:
        issues.append(f"{label}_session_status")
    if session.get("live") is not True:
        issues.append(f"{label}_not_live")
    return issues


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= _SERIAL_TOL * max(1.0, abs(a), abs(b))


def _measure_issues(row: dict[str, Any] | None, name: str, unit: str, kind: str) -> list[str]:
    if row is None:
        return [name]
    issues: list[str] = []
    if row.get("entity_id") != ENTITY:
        issues.append("entity_id")
    if row.get("unit") != unit:
        issues.append(name)
    if name == "integrated_interface_force":
        if row.get("kind") != "integrated_traction_magnitude":
            issues.append(name)
        comps = _vec3(row.get("net_components_N") or row.get("components_N"))
        try:
            l1 = float(row.get("l1_N"))
            value = float(row.get("value"))
        except (TypeError, ValueError):
            issues.append(name)
            return issues
        if comps is None or not math.isfinite(l1) or l1 < 0 or not math.isfinite(value) or value < 0:
            issues.append(name)
            return issues
        net_mag = _norm2(comps)
        recorded_net = row.get("net_magnitude_N")
        if recorded_net is not None and (not _finite(recorded_net) or not _close(float(recorded_net), net_mag)):
            issues.append(name)
        if not _close(value, l1):
            issues.append(name)
    elif name == "max_interface_displacement":
        if row.get("kind") != "max_magnitude":
            issues.append(name)
        if not _finite(row.get("value")) or float(row["value"]) < 0:
            issues.append(name)
    else:
        if row.get("kind") != MAPPING_RESIDUAL_KIND:
            issues.append(name)
        if row.get("unit") != "1" or row.get("dimensionless") is not True:
            issues.append(name)
        if row.get("formula") != MAPPING_RESIDUAL_FORMULA:
            issues.append(name)
        if row.get("convention") != MAPPING_RESIDUAL_CONVENTION:
            issues.append(name)
        recomputed = residual_from_mapping_row(row)
        try:
            recorded = float(row.get("value"))
        except (TypeError, ValueError):
            issues.append(name)
            return issues
        if recomputed is None or not math.isfinite(recorded) or recorded < 0.0 or recorded > 1.0:
            issues.append(name)
            return issues
        if not _close(recorded, recomputed):
            issues.append(name)
        try:
            sl1 = float(row.get("solid_l1_N"))
            fl1 = float(row.get("fluid_l1_N"))
        except (TypeError, ValueError):
            issues.append(name)
            return issues
        if sl1 < 0 or fl1 < 0 or not math.isfinite(sl1) or not math.isfinite(fl1):
            issues.append(name)
        if _vec3(row.get("solid_components_N")) is None or _vec3(row.get("fluid_components_N")) is None:
            issues.append(name)
    return issues


def compare_refinement(coarse: dict[str, Any], fine: dict[str, Any], *, kind: str) -> dict[str, Any]:
    """Pure session/pair comparison. Does not launch Gmsh or solvers."""
    if kind not in {"spatial", "temporal"}:
        return _fail(kind, ["kind"], same_problem_definition=False, detail="unknown kind")

    pc, pf = _problem(coarse), _problem(fine)
    dc, df = _disc(coarse), _disc(fine)
    validation_errors: list[str] = []
    problem_definition_differences: list[str] = []
    refinement_contract_errors: list[str] = []
    acceptance_failures: list[str] = []

    validation_errors.extend(_session_state_issues(coarse, "coarse"))
    validation_errors.extend(_session_state_issues(fine, "fine"))
    validation_errors.extend(_problem_field_issues(pc))
    validation_errors.extend(_problem_field_issues(pf))
    validation_errors.extend(_disc_field_issues(dc))
    validation_errors.extend(_disc_field_issues(df))

    for key in _PROBLEM_KEYS:
        if pc.get(key) != pf.get(key):
            problem_definition_differences.append(key)

    for name, unit, kind_name in QUANTITY_SPECS:
        validation_errors.extend(_measure_issues(_measurement(coarse, name), name, unit, kind_name))
        validation_errors.extend(_measure_issues(_measurement(fine, name), name, unit, kind_name))
        crow = _measurement(coarse, name)
        frow = _measurement(fine, name)
        if crow is not None and frow is not None:
            for meta in ("unit", "kind", "formula", "convention", "dimensionless"):
                if crow.get(meta) != frow.get(meta):
                    validation_errors.append(name)

    required_ver = ("gmsh", "calculix", "openfoam", "precice")
    for session in (coarse, fine):
        vers = _versions(session)
        if any(not isinstance(vers.get(name), str) or not str(vers.get(name)).strip() for name in required_ver):
            validation_errors.append("backend_versions")
            break
        if any(parse_backend_version(name, vers.get(name)) is None for name in required_ver):
            validation_errors.append("backend_versions")
            break
    else:
        if _versions(coarse) != _versions(fine):
            problem_definition_differences.append("backend_versions")

    try:
        n_sc, n_sf = int(dc.get("solid_interface_vertex_count")), int(df.get("solid_interface_vertex_count"))
        n_fc, n_ff = int(dc.get("fluid_interface_facecenter_count")), int(df.get("fluid_interface_facecenter_count"))
    except (TypeError, ValueError):
        n_sc = n_sf = n_fc = n_ff = 0

    if kind == "spatial":
        if dc.get("h_max") != _SPATIAL_H[0] or df.get("h_max") != _SPATIAL_H[1]:
            refinement_contract_errors.append("h_max")
        if dc.get("dt") != df.get("dt"):
            refinement_contract_errors.append("dt")
        if dc.get("solver_dt") != df.get("solver_dt"):
            refinement_contract_errors.append("solver_dt")
        if dc.get("expected_windows") != df.get("expected_windows"):
            refinement_contract_errors.append("expected_windows")
        if _horizon_mismatch(dc.get("dt"), dc.get("expected_windows"), pc.get("t_end")):
            refinement_contract_errors.append("t_end")
        if _horizon_mismatch(df.get("dt"), df.get("expected_windows"), pf.get("t_end")):
            refinement_contract_errors.append("t_end")
        if dc.get("solid_mesh_id") == df.get("solid_mesh_id"):
            refinement_contract_errors.append("solid_mesh_id")
        if dc.get("fluid_mesh_id") == df.get("fluid_mesh_id"):
            refinement_contract_errors.append("fluid_mesh_id")
        if not (n_sf > n_sc):
            refinement_contract_errors.append("solid_interface_vertex_count")
        if not (n_ff > n_fc):
            refinement_contract_errors.append("fluid_interface_facecenter_count")
    else:
        if dc.get("h_max") != df.get("h_max"):
            problem_definition_differences.append("h_max")
        if dc.get("solid_mesh_id") != df.get("solid_mesh_id"):
            problem_definition_differences.append("solid_mesh_id")
        if dc.get("fluid_mesh_id") != df.get("fluid_mesh_id"):
            problem_definition_differences.append("fluid_mesh_id")
        if n_sc != n_sf:
            problem_definition_differences.append("solid_interface_vertex_count")
        if n_fc != n_ff:
            problem_definition_differences.append("fluid_interface_facecenter_count")
        if dc.get("solid_interface_vertices") != df.get("solid_interface_vertices"):
            problem_definition_differences.append("solid_interface_vertices")
        if dc.get("fluid_interface_facecenters") != df.get("fluid_interface_facecenters"):
            problem_definition_differences.append("fluid_interface_facecenters")
        if dc.get("dt") != _TEMPORAL["coarse_dt"] or df.get("dt") != _TEMPORAL["fine_dt"]:
            refinement_contract_errors.append("dt")
        if dc.get("solver_dt") != _TEMPORAL["coarse_dt"] or df.get("solver_dt") != _TEMPORAL["fine_dt"]:
            refinement_contract_errors.append("solver_dt")
        if dc.get("expected_windows") != _TEMPORAL["coarse_windows"] or df.get("expected_windows") != _TEMPORAL["fine_windows"]:
            refinement_contract_errors.append("expected_windows")
        if pc.get("t_end") != _TEMPORAL["t_end"] or pf.get("t_end") != _TEMPORAL["t_end"]:
            problem_definition_differences.append("t_end")
        if _horizon_mismatch(dc.get("dt"), dc.get("expected_windows"), pc.get("t_end")):
            refinement_contract_errors.append("t_end")
        if _horizon_mismatch(df.get("dt"), df.get("expected_windows"), pf.get("t_end")):
            refinement_contract_errors.append("t_end")

    if dc.get("completed_windows") != dc.get("expected_windows") or df.get("completed_windows") != df.get("expected_windows"):
        refinement_contract_errors.append("completed_windows")
    if dc.get("terminal_coupling_status") != "completed" or df.get("terminal_coupling_status") != "completed":
        refinement_contract_errors.append("completed_windows")

    quantities = []
    for name, unit, _kind in QUANTITY_SPECS:
        crow = _measurement(coarse, name)
        frow = _measurement(fine, name)
        if name == "mapping_residual":
            cvf = residual_from_mapping_row(crow) if crow else None
            fvf = residual_from_mapping_row(frow) if frow else None
        else:
            try:
                cvf = float(crow["value"]) if crow else None
                fvf = float(frow["value"]) if frow else None
            except (TypeError, ValueError, KeyError):
                cvf = fvf = None
            if cvf is not None and not math.isfinite(cvf):
                cvf = None
            if fvf is not None and not math.isfinite(fvf):
                fvf = None
        coarse_ok = cvf is not None and math.isfinite(cvf)
        fine_ok = fvf is not None and math.isfinite(fvf)
        if not coarse_ok or not fine_ok:
            validation_errors.append(name)
            quantities.append(
                {
                    "name": name,
                    "coarse": cvf if coarse_ok else None,
                    "fine": fvf if fine_ok else None,
                    "recomputed_coarse": cvf if name == "mapping_residual" and coarse_ok else None,
                    "recomputed_fine": fvf if name == "mapping_residual" and fine_ok else None,
                    "relative_change": None,
                    "relative_tolerance": RELATIVE_TOLERANCE if name != "mapping_residual" else None,
                    "conservation_tolerance": MAPPING_CONSERVATION_TOLERANCE if name == "mapping_residual" else None,
                    "within_tolerance": False,
                    "unit": unit,
                }
            )
            continue
        rel, status = relative_change(cvf, fvf)
        if status != "ok":
            validation_errors.append(name)
            within = False
        elif name == "mapping_residual":
            within = cvf <= MAPPING_CONSERVATION_TOLERANCE and fvf <= MAPPING_CONSERVATION_TOLERANCE
            if not within:
                acceptance_failures.append(name)
        else:
            within = rel is not None and rel <= RELATIVE_TOLERANCE
            if not within:
                acceptance_failures.append(name)
        mag_c = mag_f = None
        if name == "mapping_residual" and crow and frow:
            try:
                mag_c = load_magnitude_consistency(float(crow["solid_l1_N"]), float(crow["fluid_l1_N"]))
                mag_f = load_magnitude_consistency(float(frow["solid_l1_N"]), float(frow["fluid_l1_N"]))
            except (TypeError, ValueError, KeyError):
                mag_c = mag_f = None
        quantities.append(
            {
                "name": name,
                "coarse": cvf,
                "fine": fvf,
                "recomputed_coarse": cvf if name == "mapping_residual" else None,
                "recomputed_fine": fvf if name == "mapping_residual" else None,
                "load_magnitude_consistency_coarse": mag_c,
                "load_magnitude_consistency_fine": mag_f,
                "relative_change": rel if status == "ok" else None,
                "relative_tolerance": RELATIVE_TOLERANCE if name != "mapping_residual" else None,
                "conservation_tolerance": MAPPING_CONSERVATION_TOLERANCE if name == "mapping_residual" else None,
                "within_tolerance": within,
                "unit": unit,
            }
        )

    validation_errors = sorted(set(validation_errors))
    problem_definition_differences = sorted(set(problem_definition_differences))
    refinement_contract_errors = sorted(set(refinement_contract_errors))
    acceptance_failures = sorted(set(acceptance_failures))
    differences = sorted(
        set(validation_errors + problem_definition_differences + refinement_contract_errors + acceptance_failures)
    )
    same_problem = not problem_definition_differences
    record_valid = not validation_errors and not problem_definition_differences and not refinement_contract_errors
    accepted = not acceptance_failures
    ok = bool(record_valid and accepted)

    def _snap(p: dict[str, Any], d: dict[str, Any]) -> dict[str, Any]:
        return {
            "h_max": d.get("h_max"),
            "dt": d.get("dt"),
            "solver_dt": d.get("solver_dt"),
            "expected_windows": d.get("expected_windows"),
            "completed_windows": d.get("completed_windows"),
            "t_end": p.get("t_end"),
            "solid_interface_vertex_count": d.get("solid_interface_vertex_count"),
            "fluid_interface_facecenter_count": d.get("fluid_interface_facecenter_count"),
            "solid_mesh_id": d.get("solid_mesh_id"),
            "fluid_mesh_id": d.get("fluid_mesh_id"),
        }

    return {
        "ok": ok,
        "record_valid": record_valid,
        "within_tolerance": accepted,
        "kind": kind,
        "same_problem_definition": same_problem,
        "differences": differences,
        "validation_errors": validation_errors,
        "problem_definition_differences": problem_definition_differences,
        "refinement_contract_errors": refinement_contract_errors,
        "acceptance_failures": acceptance_failures,
        "quantities": quantities,
        "relative_tolerance": RELATIVE_TOLERANCE,
        "mapping_conservation_tolerance": MAPPING_CONSERVATION_TOLERANCE,
        "force_sign": FORCE_SIGN,
        "coarse": _snap(pc, dc),
        "fine": _snap(pf, df),
        "coarse_provenance": {
            "problem": pc,
            "discretization": dc,
            "backend_versions": _versions(coarse),
        },
        "fine_provenance": {
            "problem": pf,
            "discretization": df,
            "backend_versions": _versions(fine),
        },
        "window_completed_mark": WINDOW_COMPLETED_MARK,
        "relative_change_formula": "abs(fine-coarse)/abs(fine)",
        "mapping_residual_formula": MAPPING_RESIDUAL_FORMULA,
        "mapping_residual_convention": MAPPING_RESIDUAL_CONVENTION,
        "load_magnitude_formula": LOAD_MAGNITUDE_FORMULA,
    }


def verify_mechanical_couple(
    *,
    windows_ok: bool,
    probes: dict[str, Any],
    mapping_residual: float | None,
    log_text: str,
) -> dict[str, Any]:
    """Live couple evidence: force, max interface disp, L1 mapping residual."""
    del log_text
    reasons: list[str] = []
    if not windows_ok:
        reasons.append("coupling windows did not complete")
    disp = probes.get("face.inner_wall.displacement")
    force = probes.get("face.inner_wall.integrated_force")
    try:
        dval = float(disp["value"]) if isinstance(disp, dict) else float("nan")
    except (TypeError, ValueError, KeyError):
        dval = float("nan")
    try:
        fval = float(force["value"]) if isinstance(force, dict) else float("nan")
    except (TypeError, ValueError, KeyError):
        fval = float("nan")
    if not math.isfinite(dval) or abs(dval) <= 0.0:
        reasons.append("no displacement response on face.inner_wall")
    l1 = None
    if isinstance(force, dict) and _finite(force.get("l1_N")):
        l1 = float(force["l1_N"])
    if l1 is None or l1 <= 0.0:
        reasons.append("no transferred/integrated force on face.inner_wall")
    residual = mapping_residual
    if residual is None:
        residual = residual_from_source_rows(
            probes.get("face.inner_wall.integrated_force")
            if isinstance(probes.get("face.inner_wall.integrated_force"), dict)
            else None,
            probes.get("face.inner_wall.fluid_integrated_force")
            if isinstance(probes.get("face.inner_wall.fluid_integrated_force"), dict)
            else None,
        )
    if residual is None:
        reasons.append("mapping residual missing")
    elif not math.isfinite(residual) or residual > MAPPING_CONSERVATION_TOLERANCE:
        reasons.append("mapping conservation residual exceeds tolerance")
    ok = not reasons
    return {
        "status": "ok" if ok else "broken",
        "ok": ok,
        "detail": "; ".join(reasons) if reasons else "mechanical couple",
        "mapping_error": {"relative": residual},
        "integrated_force_N": fval if math.isfinite(fval) else None,
        "displacement_m": dval if math.isfinite(dval) else None,
    }


def run_live_refinement_pair(
    out: Path,
    model: dict[str, Any],
    *,
    kind: str,
    session_runner: Any | None = None,
) -> dict[str, Any]:
    """Coarse session, fine session, compare, write e-refine.json even on fail."""
    from engineering_tools.e_facade import run_e_session

    runner = session_runner or run_e_session
    root = Path(out)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "e-refine.json"

    def _persist(report: dict[str, Any]) -> dict[str, Any]:
        report["path"] = str(path)
        try:
            path.write_text(dumps_report(report), encoding="utf-8")
        except (TypeError, ValueError) as exc:
            fallback = _fail(
                kind,
                ["serialization"],
                record_valid=False,
                detail="strict JSON serialization failed",
                exception_type=type(exc).__name__,
                message=str(exc)[:500],
            )
            fallback["path"] = str(path)
            path.write_text(dumps_report(fallback), encoding="utf-8")
            return fallback
        return report

    def _crash(stage: str, level: str | None, exc: Exception, **extra: Any) -> dict[str, Any]:
        report = _fail(
            kind if kind in {"spatial", "temporal"} else "unknown",
            [stage],
            record_valid=False,
            stage=stage,
            level=level,
            exception_type=type(exc).__name__,
            message=str(exc)[:500],
            **extra,
        )
        return _persist(report)

    if kind == "spatial":
        try:
            coarse = runner(root / "coarse", model, h_max=0.012, physical_time_s=0.02, time_window_s=0.01)
        except Exception as exc:
            return _crash("coarse_session", "coarse", exc)
        try:
            fine = runner(root / "fine", model, h_max=0.006, physical_time_s=0.02, time_window_s=0.01)
        except Exception as exc:
            return _crash("fine_session", "fine", exc, coarse_identity=str(root / "coarse"))
    elif kind == "temporal":
        try:
            coarse = runner(root / "coarse", model, h_max=0.012, physical_time_s=0.02, time_window_s=0.01)
        except Exception as exc:
            return _crash("coarse_session", "coarse", exc)
        try:
            fine = runner(root / "fine", model, h_max=0.012, physical_time_s=0.02, time_window_s=0.005)
        except Exception as exc:
            return _crash("fine_session", "fine", exc, coarse_identity=str(root / "coarse"))
    else:
        return _persist(_fail(kind, ["kind"], same_problem_definition=False, detail="unknown kind"))
    try:
        report = compare_refinement(coarse, fine, kind=kind)
    except Exception as exc:
        return _crash("compare", None, exc, coarse_identity=str(root / "coarse"), fine_identity=str(root / "fine"))
    return _persist(report)
