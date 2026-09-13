"""Trusted component probes used by stack verification."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from importlib import resources
from pathlib import Path
from typing import Any

CCX_SAMPLE = "hello_beam"
FC_SAMPLE = "hello_box"
CALCULIX_CREDIT = (
    "CalculiX (GPL-2.0+) - http://www.calculix.de/ - called as an upstream solver, "
    "not vendored"
)
FREECAD_CREDIT = (
    "FreeCAD (LGPL-2.0-or-later) - https://www.freecad.org/ - called as an upstream "
    "app, not vendored"
)
OPENFOAM_CREDIT = (
    "OpenFOAM (GPL-3.0-or-later) - https://openfoam.org/ - called as an "
    "upstream solver, not vendored"
)


def load_calculix_sample() -> str:
    root = resources.files("engineering_tools")
    return (root / "data" / "calculix" / f"{CCX_SAMPLE}.inp").read_text(encoding="utf-8")


def load_freecad_sample() -> str:
    root = resources.files("engineering_tools")
    return (root / "data" / "freecad" / f"{FC_SAMPLE}.py").read_text(encoding="utf-8")


def _work_dir(project: str | Path | None, name: str, prefix: str) -> Path:
    if project is None:
        return Path(tempfile.mkdtemp(prefix=prefix))
    path = Path(project).expanduser().resolve() / "artifacts" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _result(component_id: str, name: str, status: str, message: str, *, locator: str | None = None, workdir: Path | None = None, outputs: list[str] | None = None, credit: str | None = None, returncode: int | None = None) -> dict[str, Any]:
    return {"id": component_id, "name": name, "status": status, "message": message, "locator": locator, "workdir": str(workdir) if workdir else None, "outputs": outputs or [], "credit": credit, "returncode": returncode}


def probe_calculix(project: str | Path | None = None) -> dict[str, Any]:
    ccx = shutil.which("ccx")
    if not ccx:
        return _result("calculix", "CalculiX", "missing", "CalculiX binary 'ccx' not found")
    work = _work_dir(project, "calculix-hello", "etools-ccx-")
    sample = work / f"{CCX_SAMPLE}.inp"
    sample.write_text(load_calculix_sample(), encoding="utf-8")
    try:
        proc = subprocess.run([ccx, CCX_SAMPLE], cwd=work, capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _result("calculix", "CalculiX", "broken", f"CalculiX run failed: {exc}", locator=ccx, workdir=work, credit=CALCULIX_CREDIT)
    outputs = [str(path) for path in (work / f"{CCX_SAMPLE}.frd", work / f"{CCX_SAMPLE}.dat") if path.exists()]
    status = "ok" if proc.returncode == 0 else "broken"
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    message = f"CalculiX hello_beam {status} via {ccx}" + (f": {detail[-1]}" if detail else "")
    return _result("calculix", "CalculiX", status, message, locator=ccx, workdir=work, outputs=outputs, credit=CALCULIX_CREDIT, returncode=proc.returncode)


def _find_freecad_cmd(path_env: str | None = None) -> str | None:
    for name in ("FreeCADCmd", "freecadcmd", "freecad", "FreeCAD"):
        if found := shutil.which(name, path=path_env):
            return found
    return None


def probe_freecad(project: str | Path | None = None) -> dict[str, Any]:
    command = _find_freecad_cmd()
    if not command:
        return _result("freecad", "FreeCAD", "missing", "FreeCAD command not found")
    work = _work_dir(project, "freecad-hello", "etools-fc-")
    script = work / f"{FC_SAMPLE}.py"
    output = work / f"{FC_SAMPLE}.FCStd"
    script.write_text(load_freecad_sample(), encoding="utf-8")
    try:
        proc = subprocess.run([command, str(script), str(output)], cwd=work, capture_output=True, text=True, timeout=90, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _result("freecad", "FreeCAD", "broken", f"FreeCAD run failed: {exc}", locator=command, workdir=work, credit=FREECAD_CREDIT)
    outputs = [str(output)] if output.exists() else []
    status = "ok" if proc.returncode == 0 else "broken"
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    message = f"FreeCAD hello_box {status} via {command}" + (f": {detail[-1]}" if detail else "")
    return _result("freecad", "FreeCAD", status, message, locator=command, workdir=work, outputs=outputs, credit=FREECAD_CREDIT, returncode=proc.returncode)


def _openfoam_command() -> tuple[list[str], str] | None:
    if block_mesh := shutil.which("blockMesh"):
        return [block_mesh], block_mesh
    if foam_exec := shutil.which("foamExec"):
        return [foam_exec, "blockMesh"], f"{foam_exec} blockMesh"
    return None


def _copy_resource_tree(source, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        target = destination / child.name
        if child.is_dir():
            _copy_resource_tree(child, target)
        else:
            target.write_bytes(child.read_bytes())


def probe_openfoam(project: str | Path | None = None) -> dict[str, Any]:
    resolved = _openfoam_command()
    if not resolved:
        return _result("openfoam", "OpenFOAM", "missing", "blockMesh or foamExec not found")
    command, locator = resolved
    work = _work_dir(project, "openfoam-hello", "etools-openfoam-")
    root = resources.files("engineering_tools")
    _copy_resource_tree(root / "data" / "openfoam" / "hello_cavity", work)
    try:
        proc = subprocess.run(command, cwd=work, capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _result("openfoam", "OpenFOAM", "broken", f"OpenFOAM blockMesh failed: {exc}", locator=locator, workdir=work, credit=OPENFOAM_CREDIT)
    points = work / "constant" / "polyMesh" / "points"
    outputs = [str(points)] if points.is_file() else []
    if proc.returncode:
        status, message = "broken", f"OpenFOAM blockMesh failed with exit {proc.returncode}"
    elif not points.is_file():
        status, message = "broken", "OpenFOAM blockMesh did not create constant/polyMesh/points"
    else:
        status, message = "ok", f"OpenFOAM blockMesh ok via {locator}"
    return _result("openfoam", "OpenFOAM", status, message, locator=locator, workdir=work, outputs=outputs, credit=OPENFOAM_CREDIT, returncode=proc.returncode)


COMPONENT_PROBES = {"calculix-hello-beam": probe_calculix, "freecad-hello-box": probe_freecad, "openfoam-block-mesh": probe_openfoam}
