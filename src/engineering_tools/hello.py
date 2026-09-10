"""Minimal smoke-check against detected CAD/CAE tools."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from importlib import resources
from pathlib import Path
from typing import Any, Optional

from .profile import detect_profile, summarize_profile

_FREECAD_BOX = """\
import sys
try:
    import FreeCAD
    import Part
    doc = FreeCAD.newDocument("hello")
    box = doc.addObject("Part::Box", "Box")
    box.Length = 10
    box.Width = 10
    box.Height = 10
    doc.recompute()
    print("engineering-tools: FreeCAD headless box OK")
except Exception as exc:
    print(f"engineering-tools: FreeCAD script error: {exc}")
    sys.exit(1)
"""

SAMPLE_NAME = "hello_beam"
CALCULIX_CREDIT = (
    "CalculiX (GPL-2.0+) — http://www.calculix.de/ — called as an upstream solver, "
    "not vendored"
)


def load_calculix_sample() -> str:
    """Return the packaged CalculiX .inp text."""
    root = resources.files("engineering_tools")
    return (root / "data" / "calculix" / f"{SAMPLE_NAME}.inp").read_text(encoding="utf-8")


def _work_dir(project: Optional[str]) -> tuple[Path, bool]:
    """Return (directory, is_temp)."""
    if project:
        path = Path(project).expanduser().resolve() / "artifacts" / "calculix-hello"
        path.mkdir(parents=True, exist_ok=True)
        return path, False
    tmp = tempfile.mkdtemp(prefix="etools-ccx-")
    return Path(tmp), True


def _try_calculix(ccx: str, project: Optional[str] = None) -> tuple[bool, str, dict[str, Any]]:
    """Copy sample deck and run ccx; return ok, message, extra fields."""
    work, is_temp = _work_dir(project)
    inp_path = work / f"{SAMPLE_NAME}.inp"
    inp_path.write_text(load_calculix_sample(), encoding="utf-8")
    extra: dict[str, Any] = {
        "sample": str(inp_path),
        "workdir": str(work),
        "credit": CALCULIX_CREDIT,
    }
    try:
        proc = subprocess.run(
            [ccx, SAMPLE_NAME],
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

    frd = work / f"{SAMPLE_NAME}.frd"
    dat = work / f"{SAMPLE_NAME}.dat"
    extra["returncode"] = proc.returncode
    extra["outputs"] = [str(p) for p in (frd, dat) if p.exists()]

    if proc.returncode == 0:
        outs = ", ".join(extra["outputs"]) or str(work)
        msg = (
            f"CalculiX hello_beam OK via {ccx}. Outputs: {outs}. {CALCULIX_CREDIT}"
        )
        return True, msg, extra

    err = (proc.stderr or proc.stdout or "").strip()
    tail = err.splitlines()[-1] if err else f"exit {proc.returncode}"
    # Binary present still counts as a useful hello if we at least staged the deck.
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


def _try_freecad_box(cmd: str) -> tuple[bool, str]:
    """Run a tiny headless box; report success or 'binary found' on failure."""
    with tempfile.TemporaryDirectory(prefix="etools-hello-") as tmp:
        script = Path(tmp) / "hello_box.py"
        script.write_text(_FREECAD_BOX, encoding="utf-8")
        try:
            proc = subprocess.run(
                [cmd, str(script)],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"FreeCAD binary found at {cmd} but run failed: {exc}"

        if proc.returncode == 0:
            detail = (proc.stdout or "").strip() or "FreeCAD headless box OK"
            return True, detail
        err = (proc.stderr or proc.stdout or "").strip()
        msg = f"FreeCAD binary found at {cmd}"
        if err:
            msg = f"{msg}; headless script failed: {err.splitlines()[-1]}"
        else:
            msg = f"{msg}; headless script exited {proc.returncode}"
        return True, msg


def run_hello(project: Optional[str] = None) -> dict[str, Any]:
    """Smoke-check tools; prefer CalculiX sample, then FreeCAD, then detect-only."""
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
        ok, message = _try_freecad_box(freecad)
        result["ok"] = ok
        result["message"] = message
        result["backend"] = "FreeCAD"
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
