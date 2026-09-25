"""Orchestrate damper-keyway CAD, CalculiX, OpenFOAM, and B point-value relations."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from importlib import resources
from pathlib import Path
from typing import Any

from .damper_cfd import (
    chamber_center_index,
    chamber_wall_index,
    parse_internal_field_p,
    write_chamber_case,
)
from .damper_fea import sample_frd_von_mises, write_solid_inp
from .damper_params import (
    SOLID_PROBES,
    load_params,
    params_digest,
    probes_from_params,
)
from .damper_relations import evaluate_relations
from .hello_probes import _find_freecad_cmd, _openfoam_tool, _run_openfoam


def _report(
    *,
    ok: bool,
    status: str,
    message: str,
    workdir: Path,
    outputs: list[str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = {
        "ok": ok,
        "status": status,
        "message": message,
        "workdir": str(workdir),
        "outputs": outputs,
        "report": extra or {},
    }
    return body


def _pressure_field(work: Path) -> Path | None:
    for path in sorted(work.glob("*/p")):
        if path.parent.name != "0" and path.is_file() and path.stat().st_size > 0:
            return path
    return None


def run_damper_keyway(project: str | Path) -> dict[str, Any]:
    """Run CAD + FEA + CFD and evaluate A/B gates. Comments for other agents."""
    root = Path(project).expanduser().resolve()
    out = root / "artifacts" / "scenario-damper-keyway"
    out.mkdir(parents=True, exist_ok=True)
    params = load_params()
    params_path = out / "damper-params.json"
    params_path.write_text(json.dumps(params, indent=2) + "\n", encoding="utf-8")
    probes = probes_from_params(params)
    (out / "probes.json").write_text(json.dumps(probes, indent=2), encoding="utf-8")
    outputs = [str(params_path), str(out / "probes.json")]

    cad = _find_freecad_cmd()
    if not cad:
        return _report(ok=False, status="missing", message="FreeCADCmd not found", workdir=out, outputs=outputs)
    script = resources.files("engineering_tools") / "data" / "damper" / "build_damper.py"
    try:
        # FreeCADCmd treats extra argv as documents to open; params live in cwd.
        cad_proc = subprocess.run(
            [cad, str(script)],
            cwd=out,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _report(ok=False, status="broken", message=f"FreeCAD failed: {exc}", workdir=out, outputs=outputs)
    (out / "cad.log").write_text(
        (cad_proc.stdout or "") + "\n" + (cad_proc.stderr or ""),
        encoding="utf-8",
    )
    for name in ("damper.FCStd", "solid.step", "fluid.step"):
        path = out / name
        if not path.is_file():
            err = (cad_proc.stderr or cad_proc.stdout or "").strip().splitlines()
            hint = err[-1] if err else "no log"
            return _report(
                ok=False,
                status="broken",
                message=f"CAD did not write {name} (exit {cad_proc.returncode}): {hint}",
                workdir=out,
                outputs=outputs,
            )
        outputs.append(str(path))
    (out / "probes.json").write_text(json.dumps(probes, indent=2), encoding="utf-8")

    ccx = shutil.which("ccx")
    if not ccx:
        return _report(ok=False, status="missing", message="ccx not found", workdir=out, outputs=outputs)
    inp = write_solid_inp(params, out / "solid.inp")
    outputs.append(str(inp))
    try:
        fea_proc = subprocess.run([ccx, "solid"], cwd=out, capture_output=True, text=True, timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _report(ok=False, status="broken", message=f"CalculiX failed: {exc}", workdir=out, outputs=outputs)
    dat = out / "solid.dat"
    frd = out / "solid.frd"
    if not dat.is_file() and not frd.is_file():
        return _report(ok=False, status="broken", message="CalculiX wrote no .dat/.frd", workdir=out, outputs=outputs)
    if fea_proc.returncode:
        return _report(ok=False, status="broken", message=f"ccx exit {fea_proc.returncode}", workdir=out, outputs=outputs)
    if not frd.is_file():
        return _report(ok=False, status="broken", message="CalculiX wrote no .frd", workdir=out, outputs=outputs)
    try:
        von_map = sample_frd_von_mises(
            frd.read_text(encoding="utf-8", errors="replace"),
            {name: probes[name] for name in SOLID_PROBES},
        )
    except ValueError as exc:
        return _report(ok=False, status="broken", message=str(exc), workdir=out, outputs=outputs)
    key_a = von_map["key_fillet"]
    key_b = von_map["keyway_root"]
    if not math.isfinite(key_a) or not math.isfinite(key_b):
        return _report(ok=False, status="broken", message="key probe stress not finite", workdir=out, outputs=outputs)
    if key_a <= 0 and key_b <= 0:
        return _report(ok=False, status="broken", message="stress at both key probes is exactly zero", workdir=out, outputs=outputs)
    if key_a <= 0 or key_b <= 0:
        return _report(
            ok=False,
            status="broken",
            message=f"key probe stress not > 0 (fillet={key_a} root={key_b})",
            workdir=out,
            outputs=outputs,
        )
    von = max(key_a, key_b)
    if dat.is_file():
        outputs.append(str(dat))
    outputs.append(str(frd))

    mesh = _openfoam_tool("blockMesh")
    if not mesh:
        return _report(ok=False, status="missing", message="blockMesh or foamExec not found", workdir=out, outputs=outputs)
    foam = out / "foam"
    meta = write_chamber_case(params, foam)
    mesh_cmd, _locator = mesh
    try:
        mesh_proc = _run_openfoam(mesh_cmd, foam)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _report(ok=False, status="broken", message=f"blockMesh failed: {exc}", workdir=out, outputs=outputs)
    if mesh_proc.returncode:
        return _report(ok=False, status="broken", message=f"blockMesh exit {mesh_proc.returncode}", workdir=out, outputs=outputs)
    solver = _openfoam_tool("icoFoam")
    if not solver:
        return _report(ok=False, status="missing", message="icoFoam not found after blockMesh", workdir=out, outputs=outputs)
    solver_cmd, _sloc = solver
    try:
        solve_proc = _run_openfoam(solver_cmd, foam)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _report(ok=False, status="broken", message=f"icoFoam failed: {exc}", workdir=out, outputs=outputs)
    if solve_proc.returncode:
        return _report(ok=False, status="broken", message=f"icoFoam exit {solve_proc.returncode}", workdir=out, outputs=outputs)
    pressure_path = _pressure_field(foam)
    if pressure_path is None:
        return _report(ok=False, status="broken", message="icoFoam did not write p", workdir=out, outputs=outputs)
    try:
        p_text = pressure_path.read_text(encoding="utf-8", errors="replace")
        chamber_p = parse_internal_field_p(p_text, cell_index=chamber_center_index(meta["nx"], meta["ny"], meta["nz"]))
        wall_p = parse_internal_field_p(p_text, cell_index=chamber_wall_index(meta["nx"], meta["ny"], meta["nz"]))
    except ValueError as exc:
        return _report(ok=False, status="broken", message=str(exc), workdir=out, outputs=outputs)
    if not math.isfinite(chamber_p):
        return _report(ok=False, status="broken", message=f"chamber p {chamber_p} not finite", workdir=out, outputs=outputs)
    outputs.append(str(pressure_path))

    state_probes: dict[str, Any] = {}
    for name, xyz in probes.items():
        row: dict[str, Any] = {"xyz_mm": list(xyz), "fea": None, "cfd": None}
        if name in SOLID_PROBES:
            row["fea"] = {"von_mises": von_map[name]}
        if name == "chamber_center":
            row["cfd"] = {"p": chamber_p}
        elif name == "chamber_wall":
            row["cfd"] = {"p": wall_p}
        state_probes[name] = row
    relations = evaluate_relations(
        probes=probes,
        state_probes=state_probes,
        belt_land_traction_mpa=float(params["belt_land_traction_mpa"]),
    )
    product_state = {
        "schema_version": 1,
        "scenario": "damper-keyway",
        "params_digest": params_digest(params),
        "probes": state_probes,
        "relations": relations,
    }
    state_path = out / "product-state.json"
    state_path.write_text(json.dumps(product_state, indent=2) + "\n", encoding="utf-8")
    outputs.append(str(state_path))
    if not all(row["ok"] for row in relations):
        failed = [row["id"] for row in relations if not row["ok"]]
        extra = {
            "ok": False,
            "status": "capability-failed",
            "message": f"B relations failed: {failed}",
            "relations": relations,
            "von_mises": von,
            "key_fillet": key_a,
            "keyway_root": key_b,
            "chamber_p": chamber_p,
        }
        (out / "scenario-report.json").write_text(json.dumps(extra, indent=2) + "\n", encoding="utf-8")
        return _report(ok=False, status="capability-failed", message=extra["message"], workdir=out, outputs=outputs, extra=extra)

    extra = {
        "ok": True,
        "status": "ok",
        "message": "damper-keyway A+B passed",
        "relations": relations,
        "von_mises": von,
        "key_fillet": key_a,
        "keyway_root": key_b,
        "chamber_p": chamber_p,
    }
    (out / "scenario-report.json").write_text(json.dumps(extra, indent=2) + "\n", encoding="utf-8")
    outputs.append(str(out / "scenario-report.json"))
    return _report(ok=True, status="ok", message=extra["message"], workdir=out, outputs=outputs, extra=extra)
