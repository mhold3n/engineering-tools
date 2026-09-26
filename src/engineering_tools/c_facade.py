"""C/D FSI façade: the only scenario-facing entry for damper partitioned runs.

Agents: `run_c_fsi` is the idle coupler pair. `run_d_fsi` is the driven
damper proof (lid U, D bands, d-session.json). Both own snapshot, XML,
prepare/mesh, then concurrent Solid/Fluid. This module does not spawn a
process named `precice`. Session JSON is written even when missing/broken.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Literal

from engineering_tools.c_backend_precice import (
    default_policy,
    find_precice,
    generate_precice_config,
    run_coupled_participants,
)
from engineering_tools.c_contract import new_session
from engineering_tools.c_fsi_meshes import canonical_xyz_m, write_c_fluid_case, write_c_solid_inp
from engineering_tools.c_parity import in_band, load_c_fsi_bands, load_d_fsi_bands, mpa_to_pa
from engineering_tools.c_snapshot import freeze_ab_snapshot
from engineering_tools.d_fsi_meshes import apply_driven_lid_u, write_d_fluid_case, write_d_solid_inp
from engineering_tools.hello_probes import _openfoam_tool

from . import c_adapter_calculix, c_adapter_openfoam

_PROBE_IDS: tuple[str, ...] = (
    "housing.wall.pressure",
    "key.root.von_mises",
    "housing.wall.displacement",
    "housing.wall.traction",
)

Kind = Literal["c", "d"]


def _dependencies_present() -> bool:
    """True when coupler, Fluid solver, and CalculiX-preCICE participant exist.

    Agents: plain `ccx` is A/B, not a C/D participant. A lib-only preCICE
    install is `missing` until `precice-tools`, `binprecice`, or the CI
    alias `precice` is on PATH (see find_precice).
    """
    return (
        find_precice() is not None
        and _openfoam_tool("pimpleFoam") is not None
        and c_adapter_calculix.find_calculix_participant() is not None
    )


def _ok_key(kind: Kind) -> str:
    return "c_ok" if kind == "c" else "d_ok"


def _write_session(out: Path, session: dict[str, Any], *, kind: Kind) -> None:
    out.mkdir(parents=True, exist_ok=True)
    name = "c-session.json" if kind == "c" else "d-session.json"
    (out / name).write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")


def _blank(status: str, *, kind: Kind) -> dict[str, Any]:
    session = new_session(scenario="damper-keyway", backend="precice")
    session["status"] = status
    session["evaluated"] = True
    session["c_ok"] = False
    session["d_ok"] = False
    session[_ok_key(kind)] = False
    return session


def _xyz_of(row: dict[str, Any]) -> list[float] | None:
    raw = row.get("xyz_m", row.get("resolved_xyz_m"))
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        return None
    try:
        return [float(raw[0]), float(raw[1]), float(raw[2])]
    except (TypeError, ValueError):
        return None


def _distance_m(left: list[float], right: list[float]) -> float:
    return math.sqrt(sum((left[i] - right[i]) ** 2 for i in range(3)))


def _magnitude(value: Any) -> float:
    if isinstance(value, (list, tuple)):
        nums = [float(part) for part in value]
        return math.sqrt(sum(part * part for part in nums))
    return abs(float(value))


def _b_targets(product_state: dict[str, Any]) -> dict[str, float]:
    """B snapshot scalars in SI. Key-root MPa is converted; traction is |wall Pa|."""
    probes = product_state["probes"]
    wall_pa = float(probes["chamber_wall"]["cfd"]["p"])
    root_mpa = float(probes["keyway_root"]["fea_mapped"]["von_mises"])
    return {
        "housing.wall.pressure": wall_pa,
        "key.root.von_mises": mpa_to_pa(root_mpa),
        "housing.wall.traction": abs(wall_pa),
    }


def _wall_pressure_pa(snapshot: Path) -> float | None:
    """B wall Pa from the frozen product-state, used only as the solid *DLOAD."""
    path = snapshot / "product-state.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        return float(state["probes"]["chamber_wall"]["cfd"]["p"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _run_partitioned_fsi(
    *,
    ab_dir: Path,
    out: Path,
    params: dict[str, Any],
    kind: Kind,
) -> dict[str, Any]:
    """Idle C or driven D. `kind` selects bands, lid, dirs, and session name."""
    out = Path(out)
    ok_key = _ok_key(kind)
    if not _dependencies_present():
        session = _blank("missing", kind=kind)
        _write_session(out, session, kind=kind)
        return session

    try:
        digest = freeze_ab_snapshot(Path(ab_dir), out / "ab-snapshot")
    except (OSError, FileNotFoundError) as exc:
        session = _blank("broken", kind=kind)
        session["message"] = f"snapshot freeze failed: {exc}"
        _write_session(out, session, kind=kind)
        return session

    session = _blank("ok", kind=kind)
    session["snapshot_digest"] = digest
    policy = default_policy()
    session["participants"] = list(policy["participants"])
    session["interfaces"] = [
        {
            "name": str(policy["mesh_name"]),
            "participants": [row["name"] for row in policy["participants"]],
        }
    ]
    config_path = out / "precice-config.xml"
    config_path.write_text(generate_precice_config(policy), encoding="utf-8")

    prefix = "c" if kind == "c" else "d"
    solid_dir = out / f"{prefix}-solid"
    fluid_dir = out / f"{prefix}-fluid"
    wall_pa = _wall_pressure_pa(out / "ab-snapshot")
    if kind == "d":
        write_d_solid_inp(params, solid_dir / "d-solid.inp", wall_pressure_pa=wall_pa)
        write_d_fluid_case(params, fluid_dir)
        bands = load_d_fsi_bands()
    else:
        write_c_solid_inp(params, solid_dir / "c-solid.inp", wall_pressure_pa=wall_pa)
        write_c_fluid_case(params, fluid_dir)
        bands = load_c_fsi_bands()
    n_steps = int(bands["n_steps"])
    c_adapter_calculix.prepare_solid_participant(solid_dir, config_path)
    c_adapter_openfoam.prepare_fluid_participant(fluid_dir, config_path)
    if not c_adapter_openfoam.mesh_fluid_participant(fluid_dir):
        session["status"] = "broken"
        session["message"] = "Fluid blockMesh failed"
        session[ok_key] = False
        _write_session(out, session, kind=kind)
        return session
    # blockMesh restages 0/U. D lid U must land after that copy.
    if kind == "d":
        apply_driven_lid_u(fluid_dir)
    solid_argv = c_adapter_calculix.solid_participant_argv(solid_dir)
    fluid_argv = c_adapter_openfoam.fluid_participant_argv()
    if solid_argv is None or fluid_argv is None:
        session["status"] = "broken"
        session["message"] = "participant argv missing"
        session[ok_key] = False
        _write_session(out, session, kind=kind)
        return session
    coupled = run_coupled_participants(
        solid_argv=solid_argv,
        solid_cwd=solid_dir,
        fluid_argv=fluid_argv,
        fluid_cwd=fluid_dir,
        n_windows=n_steps,
    )
    session["steps"] = list(coupled["steps"])
    if not coupled["ok"]:
        session["status"] = "broken"
        session["message"] = str(coupled.get("detail") or "coupling windows did not converge")
        session[ok_key] = False
        _write_session(out, session, kind=kind)
        return session

    merged: dict[str, Any] = {}
    merged.update(c_adapter_calculix.sample_c_probes(solid_dir))
    merged.update(c_adapter_openfoam.sample_c_probes(fluid_dir))
    probe_file = "c-probes.json" if kind == "c" else "d-probes.json"
    (out / probe_file).write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    session["probes"] = merged

    canonical = canonical_xyz_m(params)
    tolerance = float(bands["geometric_tolerance_m"])
    floor = float(bands["motion_floor_m"])
    broken = False

    for name in _PROBE_IDS:
        row = merged.get(name)
        if not isinstance(row, dict) or "value" not in row:
            broken = True
            continue
        try:
            numeric = _magnitude(row["value"]) if name == "housing.wall.displacement" else float(row["value"])
        except (TypeError, ValueError):
            broken = True
            continue
        if not math.isfinite(numeric):
            broken = True
        xyz = _xyz_of(row)
        if xyz is None or _distance_m(xyz, canonical[name]) > tolerance:
            broken = True

    displacement = merged.get("housing.wall.displacement")
    if isinstance(displacement, dict) and "value" in displacement:
        try:
            if _magnitude(displacement["value"]) < floor:
                broken = True
        except (TypeError, ValueError):
            broken = True
    else:
        broken = True

    parity: list[dict[str, Any]] = []
    try:
        product_state = json.loads((out / "ab-snapshot" / "product-state.json").read_text(encoding="utf-8"))
        targets = _b_targets(product_state)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        session["status"] = "broken"
        session["message"] = f"snapshot product-state unreadable: {exc}"
        session[ok_key] = False
        _write_session(out, session, kind=kind)
        return session

    for name, band in bands["parity"].items():
        row = merged.get(name)
        try:
            d_value = float(row["value"]) if isinstance(row, dict) else float("nan")
        except (TypeError, ValueError, KeyError):
            d_value = float("nan")
        b_value = float(targets[name])
        ok = math.isfinite(d_value) and in_band(d_value, b_value, float(band["abs"]), float(band["rel"]))
        parity.append({"id": name, "ok": ok, "c": d_value, "b": b_value})
        if not ok:
            broken = True
    session["parity"] = parity
    session["status"] = "broken" if broken else "ok"
    session[ok_key] = session["status"] == "ok"
    _write_session(out, session, kind=kind)
    return session


def run_c_fsi(*, ab_dir: Path, out: Path, params: dict[str, Any]) -> dict[str, Any]:
    """Idle C-FSI session at `out/c-session.json`."""
    return _run_partitioned_fsi(ab_dir=ab_dir, out=out, params=params, kind="c")


def run_d_fsi(*, ab_dir: Path, out: Path, params: dict[str, Any]) -> dict[str, Any]:
    """Driven D-FSI session at `out/d-session.json`. Zeros vs finite B are broken."""
    return _run_partitioned_fsi(ab_dir=ab_dir, out=out, params=params, kind="d")
