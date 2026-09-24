"""Joint product probes for multi-component mappings.

Each probe runs only after hello has already marked every required component ok.
The check itself has to exercise the tools together. Docker session wrappers
(SALOME, Code_Aster, Nextcloud, OpenSearch) are intentionally absent: invoking
them starts a container that does not exit, so they stay unimplemented.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 60,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _receipt_locator(component_id: str) -> str | None:
    from .verification import installation_for, load_installations

    receipt = installation_for(component_id, load_installations())
    locator = receipt.get("locator") if receipt else None
    return str(locator) if locator else None


def _pythonpath(locator: str | None) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("DISPLAY", "")
    if locator:
        previous = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = locator + (os.pathsep + previous if previous else "")
    return env


def _covered(label: str, detail: str) -> dict[str, Any]:
    return {"status": "covered", "message": f"{label} covered: {detail}"}


def _failed(label: str, detail: str) -> dict[str, Any]:
    return {"status": "capability-failed", "message": f"{label} workflow failed: {detail}"}


def probe_solidworks_pdm(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Track a Git LFS pattern and initialize a DVC repo in one temporary project."""
    del results
    label = "SOLIDWORKS PDM→Git LFS+DVC"
    git = shutil.which("git")
    git_lfs = shutil.which("git-lfs")
    if not git or not git_lfs:
        return _failed(label, "git and git-lfs are required")
    work = Path(tempfile.mkdtemp(prefix="etools-pdm-"))
    try:
        init = _run([git, "init", "-q"], cwd=work)
        if init.returncode != 0:
            return _failed(label, f"git init exit {init.returncode}")
        local = _run([git_lfs, "install", "--local"], cwd=work)
        if local.returncode != 0:
            return _failed(label, f"git-lfs install exit {local.returncode}")
        track = _run([git_lfs, "track", "*.bin"], cwd=work)
        if track.returncode != 0:
            return _failed(label, f"git-lfs track exit {track.returncode}")
        attributes = (work / ".gitattributes").read_text(encoding="utf-8")
        if "filter=lfs" not in attributes:
            return _failed(label, "git-lfs did not write a filter attribute")
        dvc_env = _pythonpath(_receipt_locator("dvc"))
        dvc = _run([sys.executable, "-m", "dvc", "init", "-q"], cwd=work, env=dvc_env)
        if dvc.returncode != 0:
            detail = (dvc.stderr or dvc.stdout or "dvc init failed").strip().splitlines()
            return _failed(label, detail[-1] if detail else "dvc init failed")
        if not (work / ".dvc" / "config").is_file():
            return _failed(label, "dvc init did not write .dvc/config")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _failed(label, str(exc))
    return _covered(label, "git-lfs filter and .dvc/config")


def probe_delmia_quintiq(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Run a frePPLe XML plan and the Pyomo one-variable LP in the same product check."""
    del results
    label = "DELMIA Quintiq→frePPLe+Pyomo"
    frepple = shutil.which("frepple")
    if not frepple:
        return _failed(label, "frepple not found")
    work = Path(tempfile.mkdtemp(prefix="etools-quintiq-"))
    plan = work / "plan.xml"
    plan.write_text(
        """<?xml version="1.0" encoding="UTF-8" ?>
<plan xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <items><item name="product"/></items>
  <operations>
    <operation name="make product" xsi:type="operation_fixed_time">
      <item name="product"/>
      <duration>P1D</duration>
    </operation>
  </operations>
  <demands>
    <demand name="order-1"><item name="product"/><quantity>1</quantity></demand>
  </demands>
</plan>
""",
        encoding="utf-8",
    )
    try:
        planned = _run([frepple, str(plan)], cwd=work, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _failed(label, str(exc))
    if planned.returncode != 0:
        detail = (planned.stderr or planned.stdout or "").strip().splitlines()
        return _failed(label, f"frepple exit {planned.returncode}" + (f": {detail[-1]}" if detail else ""))
    from .hello_probes import probe_pyomo

    pyomo = probe_pyomo()
    if pyomo.get("status") != "ok":
        return _failed(label, f"pyomo {pyomo.get('status')}: {pyomo.get('message')}")
    return _covered(label, f"frepple plan exit 0; {pyomo.get('message')}")


def probe_delmia_robotics(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Confirm MoveIt is a ROS 2 package and Gazebo reports a sim version."""
    del results
    label = "DELMIA Robotics→ROS 2+MoveIt+Gazebo"
    ros2 = shutil.which("ros2")
    gz = shutil.which("gz")
    if not ros2 or not gz:
        return _failed(label, "ros2 and gz are required")
    try:
        moveit = _run([ros2, "pkg", "prefix", "moveit_core"], timeout=60)
        gazebo = _run([gz, "sim", "--versions"], timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _failed(label, str(exc))
    prefix = (moveit.stdout or "").strip()
    version = (gazebo.stdout or "").strip().splitlines()
    if moveit.returncode != 0 or not prefix:
        return _failed(label, "ros2 pkg prefix moveit_core failed")
    if gazebo.returncode != 0 or not version:
        return _failed(label, "gz sim --versions failed")
    return _covered(label, f"moveit_core prefix {prefix}; gz {version[0]}")


def probe_biovia_materials(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build an ASE H2 cell, run a zero-step LAMMPS job, and start PWSCF."""
    del results
    label = "BIOVIA Materials Studio→ASE+LAMMPS+Quantum ESPRESSO"
    lmp = shutil.which("lmp") or shutil.which("lammps")
    pw = shutil.which("pw.x")
    if not lmp or not pw:
        return _failed(label, "lmp and pw.x are required")
    env = _pythonpath(_receipt_locator("ase"))
    try:
        ase = _run(
            [
                sys.executable,
                "-c",
                "from ase import Atoms; atoms=Atoms('H2', positions=[(0,0,0),(0,0,0.74)]); print(len(atoms))",
            ],
            env=env,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _failed(label, str(exc))
    if ase.returncode != 0 or (ase.stdout or "").strip() != "2":
        detail = (ase.stderr or ase.stdout or "ASE H2 failed").strip().splitlines()
        return _failed(label, detail[-1] if detail else "ASE H2 failed")
    work = Path(tempfile.mkdtemp(prefix="etools-materials-"))
    deck = work / "in.hello"
    deck.write_text(
        "\n".join(
            [
                "units lj",
                "atom_style atomic",
                "boundary p p p",
                "region box block 0 2 0 2 0 2",
                "create_box 1 box",
                "create_atoms 1 single 1 1 1",
                "mass 1 1.0",
                "pair_style zero 1.0",
                "pair_coeff * *",
                "run 0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    try:
        lammps = _run([lmp, "-in", str(deck), "-log", str(work / "log.lammps"), "-screen", "none"], cwd=work, timeout=60)
        pwscf = _run([pw], cwd=work, timeout=30, stdin="\n")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _failed(label, str(exc))
    log = (work / "log.lammps").read_text(encoding="utf-8", errors="replace") if (work / "log.lammps").is_file() else ""
    if lammps.returncode != 0 or "Total wall time" not in log:
        return _failed(label, f"LAMMPS exit {lammps.returncode}")
    banner = (pwscf.stdout or "") + (pwscf.stderr or "")
    if "Program PWSCF" not in banner:
        return _failed(label, "pw.x did not identify as PWSCF")
    return _covered(label, "ASE H2, LAMMPS run 0, PWSCF started")


def probe_biovia_discovery(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Parse an RDKit molecule, ask GROMACS for its version, and ask Vina for usage."""
    del results
    label = "BIOVIA Discovery Studio→RDKit+GROMACS+AutoDock Vina"
    gmx = shutil.which("gmx")
    vina = shutil.which("vina")
    if not gmx or not vina:
        return _failed(label, "gmx and vina are required")
    env = _pythonpath(_receipt_locator("rdkit"))
    try:
        rdkit = _run(
            [
                sys.executable,
                "-c",
                "from rdkit import Chem; mol=Chem.MolFromSmiles('CCO'); print(mol.GetNumAtoms())",
            ],
            env=env,
            timeout=60,
        )
        gromacs = _run([gmx, "--version"], timeout=30)
        dock = _run([vina, "--help"], timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _failed(label, str(exc))
    if rdkit.returncode != 0 or (rdkit.stdout or "").strip() != "3":
        detail = (rdkit.stderr or rdkit.stdout or "RDKit failed").strip().splitlines()
        return _failed(label, detail[-1] if detail else "RDKit failed")
    if gromacs.returncode != 0 or "GROMACS" not in (gromacs.stdout or ""):
        return _failed(label, "gmx --version failed")
    usage = (dock.stdout or "") + (dock.stderr or "")
    if dock.returncode != 0 or "receptor" not in usage:
        return _failed(label, "vina --help failed")
    return _covered(label, "RDKit CCO, GROMACS version, Vina usage")
