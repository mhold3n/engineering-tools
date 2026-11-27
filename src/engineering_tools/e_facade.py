"""Phase E façade: live Solid/Fluid is the only engineering-success path.

Agents: --coupling e without real kernels is missing, not a fake pass.
PATH fakes need ETOOLS_E_MOCK_SOLVERS=1 and still cannot set e_ok.
--dry-run stages XML/meshes without e_ok. Live XML is Force/Displacement
plus Temperature on nodes and Heat-Flux on interface-faces.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from engineering_tools.c_adapter_calculix import find_calculix_participant, solid_participant_argv
from engineering_tools.c_backend_precice import WINDOW_COMPLETED_MARK, find_precice, run_coupled_participants
from engineering_tools.e_adapter_calculix import (
    _CP_J_KGK,
    _E_PA,
    _K_W_MK,
    _NU,
    _RHO,
    prepare_e_solid_participant,
    sample_e_solid_probes,
)
from engineering_tools.e_adapter_openfoam import (
    _ESI_FOAM,
    fluid_adapter_load_detail,
    fluid_e_participant_argv,
    mesh_e_fluid_participant,
    prepare_e_fluid_participant,
    sample_e_fluid_probes,
)
from engineering_tools.e_adapters import fluid_participant_input, structural_participant_input
from engineering_tools.e_backend_precice import generate_e_precice_config
from engineering_tools.e_cad import import_identity
from engineering_tools.e_model import dumps_model, validate_model
from engineering_tools.e_policy import compile_coupling_policy, coupling_session
from engineering_tools.e_mesh_pair import mesh_e_reference
from engineering_tools.e_mesh_solid import gmsh_available
from engineering_tools.e_state import FakeHistoryParticipant
from engineering_tools.e_verify import (
    MAPPING_RESIDUAL_CONVENTION,
    MAPPING_RESIDUAL_FORMULA,
    MAPPING_RESIDUAL_KIND,
    force_conservation_residual,
    parse_backend_version,
    verify_mechanical_couple,
)
from engineering_tools.hello_probes import _openfoam_tool

def _wall_pressure_pa(model: dict[str, Any]) -> float | None:
    """Canonical face.inner_wall pressure load in Pa, or None."""
    for record in model.get("loads") or []:
        if not isinstance(record, dict):
            continue
        if record.get("entity_id") == "face.inner_wall" and record.get("quantity") == "pressure":
            try:
                return float(record.get("value"))
            except (TypeError, ValueError):
                return None
    return None


# Deck that write_e_solid_inp actually solves. Canonical model stays in e-model.json.
_CANONICAL_NOT_EXECUTED = [
    "temperature_dependent_elastic",
]

ADAPTER_OUTER_CONSTRAINT = {
    "bc_id": "adapter.outer_fixed",
    "entity_id": "face.outer_wall",
    "kind": "fixed_displacement",
    "value": [0.0, 0.0, 0.0],
    "unit": "m",
    "dofs": [1, 2, 3],
    "source": "e_adapter_calculix.write_e_solid_inp",
    "rule": "r >= 0.0235 m and node not on NinterfaceN",
}


def _kernels_on_path() -> bool:
    rho = (_ESI_FOAM / "rhoPimpleFoam").is_file() or _openfoam_tool("rhoPimpleFoam") is not None
    return (
        find_precice() is not None
        and rho
        and gmsh_available()
        and find_calculix_participant() is not None
    )


def _authoritative_live() -> bool:
    """True when the ESI OpenFOAM binary is present. A PATH shell fake does not count."""
    return (_ESI_FOAM / "rhoPimpleFoam").is_file() and _kernels_on_path()


def _mock_solvers_requested() -> bool:
    return os.environ.get("ETOOLS_E_MOCK_SOLVERS") == "1"


def _count_windows(physical_time_s: float, time_window_s: float) -> dict[str, Any]:
    """Integer number of coupling windows covering a fixed physical time."""
    if physical_time_s <= 0 or time_window_s <= 0:
        return {"status": "broken", "detail": "physical_time_s and time_window_s must be positive"}
    ratio = physical_time_s / time_window_s
    n_windows = round(ratio)
    if abs(ratio - n_windows) > 1e-9 or n_windows < 1:
        return {
            "status": "broken",
            "detail": f"physical_time_s {physical_time_s} is not an integer number of windows of {time_window_s}",
        }
    return {"status": "ok", "n_windows": int(n_windows)}


def _completed_windows_from_logs(solid_dir: Path, fluid_dir: Path) -> int:
    """Min of Time window completed marks. Concatenating logs double-counts."""
    counts: list[int] = []
    for path in (Path(solid_dir) / "participant.log", Path(fluid_dir) / "participant.log"):
        if not path.is_file():
            return 0
        counts.append(path.read_text(encoding="utf-8", errors="replace").count(WINDOW_COMPLETED_MARK))
    return min(counts) if counts else 0


def _probe_text(command: list[str] | None) -> str | None:
    """Full stdout and stderr for version parsers. A missing tool returns None.

    Agents: run in a throwaway cwd so PATH fakes that mkdir 0.01 or write
    e-solid.frd cannot leak into pytest's worktree root.
    """
    if not command:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="e-version-probe-") as tmp:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
                cwd=tmp,
            )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    return text or None


def _backend_versions() -> tuple[dict[str, str | None], dict[str, str | None]]:
    """Parsed version tokens plus raw probe text. Missing stays null."""
    gmsh = shutil.which("gmsh")
    ccx = shutil.which("ccx_preCICE") or shutil.which("ccx")
    precice = shutil.which("precice-tools")
    foam_raw = os.environ.get("WM_PROJECT_VERSION")
    foam_cmd = None
    foam_version = shutil.which("foamVersion")
    if foam_version:
        foam_cmd = [foam_version]
    else:
        esi = _ESI_FOAM / "rhoPimpleFoam"
        if esi.is_file():
            foam_cmd = [str(esi), "-help"]
        else:
            located = _openfoam_tool("rhoPimpleFoam")
            if located is not None:
                foam_cmd = list(located[0]) + ["-help"]
    probes = {
        "gmsh": _probe_text([gmsh, "--version"] if gmsh else None),
        "calculix": _probe_text([ccx, "-v"] if ccx else None) or _probe_text([ccx, "--version"] if ccx else None),
        "openfoam": foam_raw if foam_raw else _probe_text(foam_cmd),
        "precice": _probe_text([precice, "--version"] if precice else None),
    }
    parsed = {name: parse_backend_version(name, text) for name, text in probes.items()}
    if parsed.get("precice") is None:
        pkg = shutil.which("pkg-config")
        extra = _probe_text([pkg, "--modversion", "libprecice"]) if pkg else None
        parsed["precice"] = parse_backend_version("precice", extra)
        if parsed["precice"] and extra:
            probes["precice"] = extra
    return parsed, probes


def run_e_session(
    out: Path,
    model: dict[str, Any],
    *,
    probes: dict[str, Any] | None = None,
    windows: int | None = None,
    dry_run: bool = False,
    h_max: float = 0.012,
    physical_time_s: float = 0.02,
    time_window_s: float = 0.01,
) -> dict[str, Any]:
    """Validate model, compile policy, persist e-session.json."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    cad = import_identity()
    check = validate_model(model)
    if check["status"] != "ok":
        return _persist(out, {"status": "broken", "e_ok": False, "detail": check["detail"]})
    struct = structural_participant_input(model, "shell")
    fluid = fluid_participant_input(model, "cavity")
    if struct["status"] != "ok":
        return _persist(out, {"status": struct["status"], "e_ok": False, "detail": struct["detail"]})
    if fluid["status"] != "ok":
        return _persist(out, {"status": fluid["status"], "e_ok": False, "detail": fluid["detail"]})
    counted = _count_windows(physical_time_s, time_window_s)
    if counted["status"] != "ok":
        return _persist(out, {"status": "broken", "e_ok": False, "detail": counted["detail"]})
    n_windows = int(windows if windows is not None else counted["n_windows"])
    clocks = {
        "h_max": float(h_max),
        "physical_time_s": float(physical_time_s),
        "time_window_s": float(time_window_s),
        "n_windows": n_windows,
        "p_pa": _wall_pressure_pa(model),
    }
    if dry_run:
        return _run_dry(out, model, cad, clocks=clocks)
    if probes is not None:
        return _run_fake(out, model, cad, probes=probes, clocks=clocks)
    if _mock_solvers_requested() and _kernels_on_path():
        return _run_live(out, model, cad, clocks=clocks, engineering=False)
    if _authoritative_live():
        return _run_live(out, model, cad, clocks=clocks, engineering=True)
    return _persist(
        out,
        {
            "status": "missing",
            "e_ok": False,
            "live": False,
            "detail": "live CalculiX/OpenFOAM/preCICE/gmsh kernels unavailable; not a fake couple",
        },
    )


def _compile_graph_policy(*, windows: int, time_window: float) -> dict[str, Any]:
    return compile_coupling_policy(
        kind="implicit two-way",
        require_checkpoint=True,
        region_physics=["compressible_fluid", "deformable_solid", "thermal_solid"],
        aitken_data=["Force", "Heat-Flux"],
        max_time_windows=windows,
        time_window=time_window,
    )


def _compile_live_policy(*, windows: int, time_window: float) -> dict[str, Any]:
    """Live step is the fluid-first one-way wall interaction.

    Agents: implicit two-way stays on _compile_graph_policy for the old
    heated-vessel graph. This function must not send solid displacement
    back to the fluid.
    """
    return compile_coupling_policy(
        kind="one-way",
        require_checkpoint=True,
        region_physics=["compressible_fluid", "deformable_solid"],
        max_time_windows=windows,
        time_window=time_window,
    )


def _live_path_record(policy: dict[str, Any], *, engineering: bool) -> dict[str, Any]:
    """Session keys that must match the live XML, not the canonical model graph.

    Agents: live XML is the fluid-first wall record. Solid does not write
    Displacement. CalculiX deck is constant *ELASTIC plus conductivity.
    checkpoint_events stay empty until a participant log records a restore.
    """
    return {
        "field_graph": policy["exchanges"],
        "checkpoint_events": [],
        "capabilities_used": ["calculix", "openfoam"] if engineering else ["path_mock"],
        "constitutive_executed": "linear_elastic",
        "regions_executed": ["deformable_solid", "compressible_fluid", "prescribed_rigid_motion"],
        "not_executed": list(_CANONICAL_NOT_EXECUTED),
        "solver_convergence": None,
        "solver_convergence_measured": False,
        "coupling_convergence": False,
    }


def _session_compare_blocks(
    cad: dict[str, Any],
    pair: dict[str, Any],
    model: dict[str, Any],
    *,
    clocks: dict[str, Any],
    policy: dict[str, Any],
    completed_windows: int,
    terminal_coupling_status: str,
    mapped: dict[str, Any],
    mapping_residual: float | None,
) -> dict[str, Any]:
    """Nested problem/discretization/measurements for compare_refinement.

    Agents: problem.materials and region_motion are the CalculiX/OpenFOAM
    deck, not model["materials"]. entity_id values are CAD identity ids.
    body.shell is elastic; body.lid is prescribed rigid. Geometry is
    vessel.step merged in .geo; cad_fingerprint remains identity.json hash.
    """
    dt = float(clocks["time_window_s"])
    n_expected = int(clocks["n_windows"])
    n_solid = int(pair.get("solid_interface_vertices") or 0)
    n_fluid = int(pair.get("fluid_interface_locations") or 0)
    solid_xyz = list(pair.get("solid_interface_vertex_xyz") or [])
    fluid_xyz = list(pair.get("fluid_interface_facecenter_xyz") or [])
    force_row = mapped.get("face.inner_wall.integrated_force") or {}
    fluid_force = mapped.get("face.inner_wall.fluid_integrated_force") or {}
    disp_row = mapped.get("face.inner_wall.displacement") or {}
    versions, version_probes = _backend_versions()
    problem = {
        "cad_fingerprint": cad.get("cad_fingerprint"),
        "topology_version": int(cad.get("topology_version") or 1),
        "materials": [
            {
                "material_id": "Steel",
                "constitutive_model": "linear_elastic",
                "E_Pa": _E_PA,
                "nu": _NU,
                "density": _RHO,
                "conductivity_W_mK": _K_W_MK,
                "specific_heat_J_kgK": _CP_J_KGK,
            },
            {
                "material_id": "lid_steel",
                "constitutive_model": "rigid",
            },
            {
                "material_id": "air",
                "equation_of_state": "perfect_gas",
            },
        ],
        "geometry_source": "vessel_step",
        "mesh_bound_to_cad_fingerprint": False,
        "canonical_not_executed": list(_CANONICAL_NOT_EXECUTED),
        "boundary_conditions": {
            "canonical_bcs": list(model.get("bcs") or []),
            "region_motion": [
                {
                    "region_id": "shell",
                    "entity_id": "body.shell",
                    "motion_model": "deformable_motion",
                    "mesh_set": "body.shell",
                },
                {
                    "region_id": "lid",
                    "entity_id": "body.lid",
                    "motion_model": "prescribed_rigid_motion",
                    "mesh_set": "body.lid",
                },
                {
                    "region_id": "cavity",
                    "entity_id": "body.gas",
                    "motion_model": "fixed",
                },
            ],
            "adapter_constraints": [dict(ADAPTER_OUTER_CONSTRAINT)],
        },
        "loads": list(model.get("loads") or []),
        "coupling_kind": policy.get("kind"),
        "convergence_measures": {"relative": 1.0e-4, "data": list(policy.get("aitken_data") or ["Force"])},
        "aitken_data": list(policy.get("aitken_data") or []),
        "aitken_initial_relaxation": 0.5,
        "max_iterations": int(policy.get("max_iterations") or 100),
        "t_end": float(clocks["physical_time_s"]),
        "entity_id": "face.inner_wall",
        "effective_solver_pressure_Pa": clocks.get("p_pa") if clocks.get("p_pa") is not None else _wall_pressure_pa(model),
    }
    discretization = {
        "h_max": float(clocks["h_max"]),
        "solid_mesh_id": pair.get("solid_mesh_id"),
        "fluid_mesh_id": pair.get("fluid_mesh_id"),
        "solid_interface_vertex_count": n_solid,
        "fluid_interface_facecenter_count": n_fluid,
        "solid_interface_vertices": solid_xyz,
        "fluid_interface_facecenters": fluid_xyz,
        "dt": dt,
        "solver_dt": dt,
        "expected_windows": n_expected,
        "completed_windows": int(completed_windows),
        "terminal_coupling_status": terminal_coupling_status,
    }
    measurements = {
        "integrated_interface_force": {
            "value": force_row.get("value"),
            "unit": "N",
            "entity_id": "face.inner_wall",
            "kind": "integrated_traction_magnitude",
            "l1_N": force_row.get("l1_N"),
            "net_components_N": force_row.get("net_components_N") or force_row.get("components_N"),
            "net_magnitude_N": force_row.get("net_magnitude_N"),
            "components_N": force_row.get("net_components_N") or force_row.get("components_N"),
        },
        "max_interface_displacement": {
            "value": disp_row.get("value"),
            "unit": "m",
            "entity_id": "face.inner_wall",
            "kind": "max_magnitude",
            "xyz_m": disp_row.get("xyz_m"),
            "node_id": disp_row.get("node_id"),
        },
        "mapping_residual": {
            "value": mapping_residual,
            "unit": "1",
            "entity_id": "face.inner_wall",
            "kind": MAPPING_RESIDUAL_KIND,
            "formula": MAPPING_RESIDUAL_FORMULA,
            "convention": MAPPING_RESIDUAL_CONVENTION,
            "dimensionless": True,
            "force_sign": 1,
            "solid_components_N": force_row.get("net_components_N") or force_row.get("components_N"),
            "fluid_components_N": fluid_force.get("net_components_N") or fluid_force.get("components_N"),
            "solid_l1_N": force_row.get("l1_N"),
            "fluid_l1_N": fluid_force.get("l1_N"),
            "solid_endpoint": force_row.get("endpoint"),
            "fluid_endpoint": fluid_force.get("endpoint"),
        },
    }
    return {
        "problem": problem,
        "discretization": discretization,
        "measurements": measurements,
        "provenance": {
            "backend_versions": versions,
            "backend_version_probes": version_probes,
            "topology_version": problem["topology_version"],
            "cad_fingerprint": problem["cad_fingerprint"],
            "canonical_face_id": "face.inner_wall",
            "h_max_m": discretization["h_max"],
            "physical_time_s": problem["t_end"],
            "time_window_s": dt,
            "n_windows": n_expected,
            "expected_windows": n_expected,
            "completed_windows": int(completed_windows),
            "terminal_coupling_status": terminal_coupling_status,
            "max_iterations": problem["max_iterations"],
            "coupling_kind": problem["coupling_kind"],
            "aitken_data": problem["aitken_data"],
            "aitken_initial_relaxation": 0.5,
            "solid_mesh_id": discretization["solid_mesh_id"],
            "fluid_mesh_id": discretization["fluid_mesh_id"],
            "solid_interface_vertices": n_solid,
            "fluid_interface_locations": n_fluid,
            "solid_interface_vertex_xyz": solid_xyz,
            "fluid_interface_facecenter_xyz": fluid_xyz,
            "materials": problem["materials"],
            "boundary_conditions": problem["boundary_conditions"],
            "loads": problem["loads"],
            "convergence_measures": problem["convergence_measures"],
            "entity_id": "face.inner_wall",
            "solver_dt": dt,
            "t_end": problem["t_end"],
            "backend": "precice",
        },
    }


def _run_fake(
    out: Path,
    model: dict[str, Any],
    cad: dict[str, Any],
    *,
    probes: dict[str, Any] | None,
    clocks: dict[str, Any],
) -> dict[str, Any]:
    n_windows = int(clocks["n_windows"])
    dt = float(clocks["time_window_s"])
    policy = _compile_graph_policy(windows=n_windows, time_window=dt)
    if policy["status"] != "ok":
        return _persist(out, {"status": "broken", "e_ok": False, "detail": policy["detail"]})
    xml = generate_e_precice_config(policy)
    (out / "precice-config.xml").write_text(xml, encoding="utf-8")
    (out / "e-model.json").write_text(dumps_model(model), encoding="utf-8")

    solid = FakeHistoryParticipant(participant_id="Solid")
    fluid_p = FakeHistoryParticipant(participant_id="Fluid")
    steps = []
    for index in range(n_windows):
        solid.begin_window(window_index=index, time_s=float(index) * dt)
        fluid_p.begin_window(window_index=index, time_s=float(index) * dt)
        solid.advance_iteration(plastic_increment=0.1)
        fluid_p.advance_iteration(plastic_increment=0.1)
        solid.restore_window_start()
        fluid_p.restore_window_start()
        solid.advance_iteration(plastic_increment=0.1)
        fluid_p.advance_iteration(plastic_increment=0.1)
        steps.append({"index": index, "converged": True})

    mapped = probes if probes is not None else _finite_demo_probes()
    if _loads_finite(model) and _fields_near_zero(mapped):
        return _persist(
            out,
            {
                "status": "broken",
                "e_ok": False,
                "live": False,
                "detail": "CAD-mapped fields ~0 while loads/BCs are finite",
                "probes": mapped,
            },
        )
    session = {
        "schema_version": 1,
        "scenario": "e-reference",
        "backend": "precice",
        "status": "mock",
        "e_ok": False,
        "live": False,
        "detail": "schema/fake couple is not an engineering result",
        "cad": {"fingerprint": cad.get("cad_fingerprint"), "topology_version": cad.get("topology_version")},
        "participants": policy["participants"],
        "capabilities_used": ["fake_history", "checkpoint_restore"],
        "field_graph": policy["exchanges"],
        "coupling": coupling_session(policy),
        "steps": steps,
        "checkpoint_events": [{"window": i, "restored": True} for i in range(n_windows)],
        "solver_convergence": None,
        "solver_convergence_measured": False,
        "coupling_convergence": False,
        "mapping_error": {"relative": None, "detail": "not measured on fake path"},
        "probes": mapped,
        "identity": cad,
        **_session_compare_blocks(
            cad,
            {},
            model,
            clocks=clocks,
            policy=policy,
            completed_windows=n_windows,
            terminal_coupling_status="mock",
            mapped=mapped,
            mapping_residual=None,
        ),
    }
    return _persist(out, session)


def _run_dry(
    out: Path,
    model: dict[str, Any],
    cad: dict[str, Any],
    *,
    clocks: dict[str, Any],
) -> dict[str, Any]:
    """Stage XML and mesh pair. Never e_ok."""
    n_windows = int(clocks["n_windows"])
    dt = float(clocks["time_window_s"])
    policy = _compile_live_policy(windows=n_windows, time_window=dt)
    if policy["status"] != "ok":
        return _persist(out, {"status": "broken", "e_ok": False, "live": False, "detail": policy["detail"]})
    xml_path = out / "precice-config.xml"
    xml_path.write_text(generate_e_precice_config(policy), encoding="utf-8")
    (out / "e-model.json").write_text(dumps_model(model), encoding="utf-8")
    pair = mesh_e_reference(out / "meshes", identity=cad, h_max=float(clocks["h_max"]))
    return _persist(
        out,
        {
            "status": "dry-run",
            "e_ok": False,
            "live": False,
            "detail": "dry-run staged XML/meshes; not an engineering couple",
            "cad": {"fingerprint": cad.get("cad_fingerprint"), "topology_version": cad.get("topology_version")},
            "mesh_pair": str(out / "meshes" / "pair.json") if pair.get("e_mesh_ok") else None,
            "e_mesh_ok": bool(pair.get("e_mesh_ok")),
            **_session_compare_blocks(
                cad,
                pair if pair.get("e_mesh_ok") else {},
                model,
                clocks=clocks,
                policy=policy,
                completed_windows=0,
                terminal_coupling_status="dry-run",
                mapped={},
                mapping_residual=None,
            ),
        },
    )


def _run_live(
    out: Path,
    model: dict[str, Any],
    cad: dict[str, Any],
    *,
    clocks: dict[str, Any],
    engineering: bool,
) -> dict[str, Any]:
    n_windows = int(clocks["n_windows"])
    dt = float(clocks["time_window_s"])
    t_end = float(clocks["physical_time_s"])
    h_max = float(clocks["h_max"])
    policy = _compile_live_policy(windows=n_windows, time_window=dt)
    if policy["status"] != "ok":
        return _persist(
            out,
            {
                "status": "broken",
                "e_ok": False,
                "live": bool(engineering),
                "detail": policy["detail"],
                "solver_convergence": None,
                "solver_convergence_measured": False,
                "coupling_convergence": False,
            },
        )
    live_record = _live_path_record(policy, engineering=engineering)
    xml_path = out / "precice-config.xml"
    xml_path.write_text(generate_e_precice_config(policy), encoding="utf-8")
    (out / "e-model.json").write_text(dumps_model(model), encoding="utf-8")
    pair = mesh_e_reference(out / "meshes", identity=cad, h_max=h_max)
    if not pair.get("e_mesh_ok"):
        return _persist(
            out,
            {
                "status": pair.get("status") or "broken",
                "e_ok": False,
                "live": bool(engineering),
                "detail": pair.get("detail") or "independent mesh pair failed",
                **live_record,
            },
        )
    n_solid = int(pair["solid_interface_vertices"])
    n_fluid = int(pair["fluid_interface_locations"])
    solid_dir = out / "e-solid"
    fluid_dir = out / "e-fluid"
    msh = Path(str(pair["solid"]["artifact"]))
    fluid_msh = Path(str(pair["fluid"]["artifact"]))
    solid = prepare_e_solid_participant(solid_dir, xml_path, cad, msh=msh, dt_s=dt, t_end_s=t_end)
    fluid = prepare_e_fluid_participant(
        fluid_dir,
        xml_path,
        cad,
        msh=fluid_msh,
        dt_s=dt,
        t_end_s=t_end,
        p_pa=float(clocks["p_pa"]) if clocks.get("p_pa") is not None else 1.01e5,
    )
    if solid.get("status") != "ok":
        return _persist(
            out,
            {"status": "broken", "e_ok": False, "live": bool(engineering), "detail": solid.get("detail"), **live_record},
        )
    if fluid.get("status") != "ok":
        return _persist(
            out,
            {"status": "broken", "e_ok": False, "live": bool(engineering), "detail": fluid.get("detail"), **live_record},
        )
    if not mesh_e_fluid_participant(fluid_dir):
        return _persist(
            out,
            {
                "status": "broken",
                "e_ok": False,
                "live": bool(engineering),
                "detail": "Fluid gmshToFoam failed",
                **live_record,
            },
        )
    solid_argv = solid_participant_argv(solid_dir)
    fluid_argv = fluid_e_participant_argv()
    if solid_argv is None or fluid_argv is None:
        return _persist(
            out,
            {
                "status": "broken",
                "e_ok": False,
                "live": bool(engineering),
                "detail": "participant argv missing",
                **live_record,
            },
        )
    coupled = run_coupled_participants(
        solid_argv=solid_argv,
        solid_cwd=solid_dir,
        fluid_argv=fluid_argv,
        fluid_cwd=fluid_dir,
        n_windows=n_windows,
    )
    # The fluid log line is the cause when the adapter library is absent.
    # Mechanical verify then only reports the windows that never started.
    fluid_log_path = fluid_dir / "participant.log"
    fluid_log = (
        fluid_log_path.read_text(encoding="utf-8", errors="replace")
        if fluid_log_path.is_file()
        else ""
    )
    adapter_detail = fluid_adapter_load_detail(fluid_log)
    mapped: dict[str, Any] = {}
    mapped.update(sample_e_solid_probes(solid_dir))
    mapped.update(sample_e_fluid_probes(fluid_dir))
    residual = force_conservation_residual(
        mapped.get("face.inner_wall.integrated_force")
        if isinstance(mapped.get("face.inner_wall.integrated_force"), dict)
        else None,
        mapped.get("face.inner_wall.fluid_integrated_force")
        if isinstance(mapped.get("face.inner_wall.fluid_integrated_force"), dict)
        else None,
    )
    completed = _completed_windows_from_logs(solid_dir, fluid_dir)
    windows_ok = completed >= n_windows
    mech = verify_mechanical_couple(
        windows_ok=windows_ok,
        probes=mapped,
        mapping_residual=residual,
        log_text="",
    )
    terminal = "completed" if windows_ok else "incomplete"
    blocks = _session_compare_blocks(
        cad,
        pair,
        model,
        clocks=clocks,
        policy=policy,
        completed_windows=completed,
        terminal_coupling_status=terminal,
        mapped=mapped,
        mapping_residual=residual if isinstance(residual, (int, float)) else None,
    )
    if _loads_finite(model) and _fields_near_zero(mapped):
        return _persist(
            out,
            {
                "status": "broken",
                "e_ok": False,
                "live": bool(engineering),
                "detail": adapter_detail or "CAD-mapped fields ~0 while loads/BCs are finite",
                "steps": list(coupled["steps"]),
                "probes": mapped,
                "solid_interface_vertices": n_solid,
                "fluid_interface_locations": n_fluid,
                **blocks,
                **live_record,
                "coupling_convergence": bool(windows_ok and engineering),
            },
        )
    e_ok = bool(engineering and mech["ok"] and windows_ok and not adapter_detail)
    if not engineering:
        e_ok = False
    session = {
        "schema_version": 1,
        "scenario": "e-reference",
        "backend": "precice",
        "status": "ok" if e_ok else ("mock" if not engineering else "broken"),
        "e_ok": e_ok,
        "live": bool(engineering),
        "cad": {"fingerprint": cad.get("cad_fingerprint"), "topology_version": cad.get("topology_version")},
        "participants": policy["participants"],
        "coupling": coupling_session(policy),
        "steps": list(coupled["steps"]),
        "mapping_error": mech.get("mapping_error"),
        "mechanical_verify": mech,
        "probes": mapped,
        "identity": cad,
        "solid_interface_vertices": n_solid,
        "fluid_interface_locations": n_fluid,
        "mesh_pair": str(out / "meshes" / "pair.json"),
        **blocks,
        **live_record,
        "coupling_convergence": bool(windows_ok and engineering),
        "backend_versions": blocks["provenance"].get("backend_versions") or {},
        "detail": None
        if e_ok
        else (
            adapter_detail
            or mech.get("detail")
            or coupled.get("detail")
            or "mechanical couple incomplete"
        ),
    }
    if not engineering:
        session["detail"] = "PATH mock solvers are not an engineering result"
        session["status"] = "mock"
    return _persist(out, session)


def _loads_finite(model: dict[str, Any]) -> bool:
    for load in model.get("loads") or []:
        try:
            if abs(float(load.get("value") or 0.0)) > 0.0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _fields_near_zero(probes: dict[str, Any]) -> bool:
    for row in probes.values():
        try:
            if abs(float(row.get("value") or 0.0)) > 1e-9:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _finite_demo_probes() -> dict[str, Any]:
    return {
        "face.inner_wall.pressure": {"value": 1.01e5, "unit": "Pa", "entity_id": "face.inner_wall"},
        "face.inner_wall.displacement": {"value": 1.2e-5, "unit": "m", "entity_id": "face.inner_wall"},
        "face.inner_wall.temperature": {"value": 350.0, "unit": "K", "entity_id": "face.inner_wall"},
        "face.inner_wall.heat_flux": {"value": 120.0, "unit": "W/m2", "entity_id": "face.inner_wall"},
    }


def _persist(out: Path, session: dict[str, Any]) -> dict[str, Any]:
    path = out / "e-session.json"
    path.write_text(json.dumps(session, indent=2, sort_keys=True), encoding="utf-8")
    session = dict(session)
    session["session_path"] = str(path)
    return session
