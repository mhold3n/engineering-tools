"""Run a custom solver deck/script and record it in job history."""

from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Optional

from .hello import CALCULIX_CREDIT, FREECAD_CREDIT, _find_freecad_cmd
from .jobs import append_job
from .registry import touch_project

SUPPORTED_TOOLS = ("calculix", "freecad")


def _resolve_ccx() -> Optional[str]:
    return shutil.which("ccx")


def _default_workdir(project: Path, run_id: str) -> Path:
    path = project / "artifacts" / f"run-{run_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _collect_outputs(workdir: Path, stem: str, tool: str) -> list[str]:
    found: list[str] = []
    if tool == "calculix":
        for ext in (".frd", ".dat", ".sta", ".cvg", ".12d"):
            p = workdir / f"{stem}{ext}"
            if p.exists():
                found.append(str(p))
    elif tool == "freecad":
        for p in sorted(workdir.iterdir()):
            if p.is_file() and p.suffix.lower() in {".fcstd", ".stl", ".step", ".stp", ".obj"}:
                found.append(str(p))
    return found


def run_deck(
    *,
    project: str | Path,
    tool: str,
    input_file: str | Path,
    workdir: Optional[str | Path] = None,
) -> dict[str, Any]:
    """Execute a CalculiX .inp or FreeCAD .py under the project and log a job.

    UX: ``etools run --tool calculix|freecad --input FILE --project PATH``.
    """
    tool_key = tool.strip().lower()
    if tool_key not in SUPPORTED_TOOLS:
        raise ValueError(f"unsupported tool {tool!r}; choose one of: {', '.join(SUPPORTED_TOOLS)}")

    root = Path(project).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "artifacts").mkdir(exist_ok=True)

    src = Path(input_file).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"input file not found: {src}")

    run_id = uuid.uuid4().hex[:12]
    work = Path(workdir).expanduser().resolve() if workdir else _default_workdir(root, run_id)
    work.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "ok": False,
        "project": str(root),
        "tool": tool_key,
        "command": "run",
        "input": str(src),
        "workdir": str(work),
        "run_id": run_id,
        "outputs": [],
        "message": "",
        "credit": None,
        "returncode": None,
    }

    if tool_key == "calculix":
        return _run_calculix(root, src, work, run_id, result)
    return _run_freecad(root, src, work, run_id, result)


def _run_calculix(
    root: Path,
    src: Path,
    work: Path,
    run_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    ccx = _resolve_ccx()
    credit = CALCULIX_CREDIT
    result["credit"] = credit
    if not ccx:
        result["message"] = (
            f"CalculiX binary 'ccx' not found on PATH. Install CalculiX or add ccx to PATH. {credit}"
        )
        _log_and_touch(root, result)
        return result

    if src.suffix.lower() != ".inp":
        result["message"] = f"CalculiX input should be a .inp file, got: {src.name}"
        _log_and_touch(root, result)
        return result

    stem = src.stem
    staged = work / f"{stem}.inp"
    if src.resolve() != staged.resolve():
        shutil.copy2(src, staged)

    try:
        proc = subprocess.run(
            [ccx, stem],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["message"] = f"CalculiX run failed: {exc}. {credit}"
        _log_and_touch(root, result)
        return result

    result["returncode"] = proc.returncode
    result["outputs"] = _collect_outputs(work, stem, "calculix")
    if staged.exists() and str(staged) not in result["outputs"]:
        result["outputs"].insert(0, str(staged))

    if proc.returncode == 0:
        result["ok"] = True
        outs = ", ".join(result["outputs"]) or str(work)
        result["message"] = f"CalculiX run OK via {ccx} (job={stem}). Outputs: {outs}. {credit}"
    else:
        err = (proc.stderr or proc.stdout or "").strip()
        tail = err.splitlines()[-1] if err else f"exit {proc.returncode}"
        result["message"] = f"CalculiX run failed ({tail}) via {ccx}. {credit}"

    _log_and_touch(root, result)
    return result


def _run_freecad(
    root: Path,
    src: Path,
    work: Path,
    run_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    cmd = _find_freecad_cmd()
    credit = FREECAD_CREDIT
    result["credit"] = credit
    if not cmd:
        result["message"] = (
            "FreeCADCmd (or freecad/FreeCAD) not found on PATH. "
            f"Install FreeCAD or add it to PATH. {credit}"
        )
        _log_and_touch(root, result)
        return result

    if src.suffix.lower() != ".py":
        result["message"] = f"FreeCAD input should be a .py script, got: {src.name}"
        _log_and_touch(root, result)
        return result

    staged = work / src.name
    if src.resolve() != staged.resolve():
        shutil.copy2(src, staged)

    out_fcstd = work / f"{src.stem}.FCStd"
    try:
        proc = subprocess.run(
            [cmd, str(staged), str(out_fcstd)],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["message"] = f"FreeCAD run failed: {exc}. {credit}"
        _log_and_touch(root, result)
        return result

    result["returncode"] = proc.returncode
    result["outputs"] = _collect_outputs(work, src.stem, "freecad")
    if staged.exists() and str(staged) not in result["outputs"]:
        result["outputs"].insert(0, str(staged))
    if out_fcstd.exists() and str(out_fcstd) not in result["outputs"]:
        result["outputs"].append(str(out_fcstd))

    if proc.returncode == 0:
        result["ok"] = True
        outs = ", ".join(result["outputs"]) or str(work)
        detail = (proc.stdout or "").strip() or "FreeCADCmd OK"
        result["message"] = f"FreeCAD run OK via {cmd}. Outputs: {outs}. {detail}. {credit}"
    else:
        err = (proc.stderr or proc.stdout or "").strip()
        tail = err.splitlines()[-1] if err else f"exit {proc.returncode}"
        result["message"] = f"FreeCAD run failed ({tail}) via {cmd}. {credit}"

    _log_and_touch(root, result)
    return result


def _log_and_touch(root: Path, result: dict[str, Any]) -> None:
    status = "ok" if result.get("ok") else "fail"
    append_job(
        root,
        tool=result.get("tool"),
        command="run",
        status=status,
        workdir=result.get("workdir"),
        outputs=list(result.get("outputs") or []),
        message=str(result.get("message") or ""),
        credit=result.get("credit"),
        input_path=result.get("input"),
    )
    touch_project(root)
