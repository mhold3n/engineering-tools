"""Minimal smoke-check against detected CAD/CAE tools."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from importlib import resources
from pathlib import Path
from typing import Any, Optional

from .profile import detect_profile, summarize_profile

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


def load_calculix_sample() -> str:
    """Return the packaged CalculiX .inp text."""
    root = resources.files("engineering_tools")
    return (root / "data" / "calculix" / f"{CCX_SAMPLE}.inp").read_text(encoding="utf-8")


def load_freecad_sample() -> str:
    """Return the packaged FreeCAD hello script text."""
    root = resources.files("engineering_tools")
    return (root / "data" / "freecad" / f"{FC_SAMPLE}.py").read_text(encoding="utf-8")


def _ccx_work_dir(project: Optional[str]) -> Path:
    if project:
        path = Path(project).expanduser().resolve() / "artifacts" / "calculix-hello"
        path.mkdir(parents=True, exist_ok=True)
        return path
    return Path(tempfile.mkdtemp(prefix="etools-ccx-"))


def _fc_work_dir(project: Optional[str]) -> Path:
    if project:
        path = Path(project).expanduser().resolve() / "artifacts" / "freecad-hello"
        path.mkdir(parents=True, exist_ok=True)
        return path
    return Path(tempfile.mkdtemp(prefix="etools-fc-"))


def _try_calculix(ccx: str, project: Optional[str] = None) -> tuple[bool, str, dict[str, Any]]:
    work = _ccx_work_dir(project)
    inp_path = work / f"{CCX_SAMPLE}.inp"
    inp_path.write_text(load_calculix_sample(), encoding="utf-8")
    extra: dict[str, Any] = {
        "sample": str(inp_path),
        "workdir": str(work),
        "credit": CALCULIX_CREDIT,
    }
    try:
        proc = subprocess.run(
            [ccx, CCX_SAMPLE],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (
            False,
            f"CalculiX found at {ccx} but run failed: {exc}. {CALCULIX_CREDIT}",
            extra,
        )

    frd = work / f"{CCX_SAMPLE}.frd"
    dat = work / f"{CCX_SAMPLE}.dat"
    extra["returncode"] = proc.returncode
    extra["outputs"] = [str(p) for p in (frd, dat) if p.exists()]

    if proc.returncode == 0:
        outs = ", ".join(extra["outputs"]) or str(work)
        return True, f"CalculiX hello_beam OK via {ccx}. Outputs: {outs}. {CALCULIX_CREDIT}", extra

    err = (proc.stderr or proc.stdout or "").strip()
    tail = err.splitlines()[-1] if err else f"exit {proc.returncode}"
    msg = (
        f"CalculiX found at {ccx}; sample staged at {inp_path} "
        f"but ccx failed ({tail}). {CALCULIX_CREDIT}"
    )
    return True, msg, extra


def _find_freecad_cmd(path_env: Optional[str] = None) -> Optional[str]:
    for name in ("FreeCADCmd", "freecadcmd", "freecad", "FreeCAD"):
        found = shutil.which(name, path=path_env)
        if found:
            return found
    return None


def _try_freecad(cmd: str, project: Optional[str] = None) -> tuple[bool, str, dict[str, Any]]:
    """Run packaged hello_box.py; optionally save an .FCStd into project artifacts."""
    work = _fc_work_dir(project)
    script = work / f"{FC_SAMPLE}.py"
    script.write_text(load_freecad_sample(), encoding="utf-8")
    out_fcstd = work / f"{FC_SAMPLE}.FCStd"
    extra: dict[str, Any] = {
        "sample": str(script),
        "workdir": str(work),
        "credit": FREECAD_CREDIT,
    }
    try:
        proc = subprocess.run(
            [cmd, str(script), str(out_fcstd)],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (
            False,
            f"FreeCAD found at {cmd} but run failed: {exc}. {FREECAD_CREDIT}",
            extra,
        )

    extra["returncode"] = proc.returncode
    extra["outputs"] = [str(out_fcstd)] if out_fcstd.exists() else []
    stdout = (proc.stdout or "").strip()

    if proc.returncode == 0:
        outs = ", ".join(extra["outputs"]) or "in-memory"
        detail = stdout or "FreeCAD hello_box OK"
        return (
            True,
            f"FreeCAD hello_box OK via {cmd}. Outputs: {outs}. {detail}. {FREECAD_CREDIT}",
            extra,
        )

    err = (proc.stderr or proc.stdout or "").strip()
    tail = err.splitlines()[-1] if err else f"exit {proc.returncode}"
    msg = (
        f"FreeCAD found at {cmd}; sample staged at {script} "
        f"but headless run failed ({tail}). {FREECAD_CREDIT}"
    )
    return True, msg, extra


def run_hello(project: Optional[str] = None) -> dict[str, Any]:
    """Prefer CalculiX sample, then FreeCAD sample, then detect-only."""
    detected = detect_profile()
    summary = summarize_profile(detected)
    result: dict[str, Any] = {
        "ok": False,
        "project": str(Path(project).expanduser().resolve()) if project else None,
        "message": "",
        "tools_found": summary["found_count"],
        "summary": summary,
    }

    ccx = shutil.which("ccx")
    if ccx:
        ok, message, extra = _try_calculix(ccx, project=project)
        result["ok"] = ok
        result["message"] = message
        result["backend"] = "CalculiX"
        result.update(extra)
        return result

    freecad = _find_freecad_cmd()
    if freecad:
        ok, message, extra = _try_freecad(freecad, project=project)
        result["ok"] = ok
        result["message"] = message
        result["backend"] = "FreeCAD"
        result.update(extra)
        return result

    if summary["found_count"]:
        names = ", ".join(summary["found"])
        result["ok"] = True
        result["message"] = f"Tools found: {names}"
        result["backend"] = "detected"
        return result

    result["ok"] = False
    result["message"] = (
        "No profile tools found on PATH. Install FreeCAD and/or CalculiX "
        "(ccx), or other CAELinux-style packages, then re-run `etools doctor`."
    )
    result["backend"] = None
    return result
