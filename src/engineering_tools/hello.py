"""Minimal smoke-check against detected CAD/CAE tools."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
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
        return True, msg  # binary found counts as ok for hello


def run_hello(project: Optional[str] = None) -> dict[str, Any]:
    """Smoke-check tools; optionally note a project path."""
    detected = detect_profile()
    summary = summarize_profile(detected)
    result: dict[str, Any] = {
        "ok": False,
        "project": str(Path(project).expanduser().resolve()) if project else None,
        "message": "",
        "tools_found": summary["found"],
        "summary": summary,
    }

    freecad = _find_freecad_cmd()
    if freecad:
        ok, message = _try_freecad_box(freecad)
        result["ok"] = ok
        result["message"] = message
        result["backend"] = "FreeCAD"
        return result

    ccx = shutil.which("ccx")
    if ccx:
        result["ok"] = True
        result["message"] = f"CalculiX ready ({ccx})"
        result["backend"] = "CalculiX"
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
