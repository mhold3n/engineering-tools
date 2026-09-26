"""Joint product probes for multi-component mappings.

Each probe runs only after hello has already marked every required component ok.
The check itself has to exercise the tools together.

Container-backed locators are never invoked as written: those wrappers often
start a session or pull a missing tag. Probes parse the wrapper image, use a
tag already present on the host, and `docker run --pull=never` with a command
that exits.
"""

from __future__ import annotations

import os
import re
import shlex
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


_IMAGE_VALUE_FLAGS = {
    "-v",
    "-w",
    "-e",
    "-u",
    "-p",
    "--volume",
    "--workdir",
    "--env",
    "--user",
    "--publish",
    "--name",
    "--entrypoint",
    "--network",
    "--add-host",
}


def _docker_argv() -> list[str] | None:
    """Return docker CLI argv, using passwordless sudo when the socket needs it."""
    docker = shutil.which("docker")
    if not docker:
        return None
    probe = _run([docker, "image", "ls"], timeout=15)
    if probe.returncode == 0:
        return [docker]
    sudo = shutil.which("sudo")
    if sudo:
        return [sudo, "-n", docker]
    return [docker]


def _image_from_wrapper(binary_names: tuple[str, ...]) -> str | None:
    """Read the first docker-run image name out of an etools-bin wrapper."""
    for name in binary_names:
        path = shutil.which(name)
        if not path:
            continue
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        match = re.search(r"docker\s+run\b[^\n]*", text)
        if not match:
            continue
        cleaned = match.group(0).replace('"', "").replace("'", "")
        try:
            tokens = shlex.split(cleaned, posix=True)
        except ValueError:
            tokens = cleaned.split()
        skip_next = False
        for token in tokens[2:]:
            if skip_next:
                skip_next = False
                continue
            if token in _IMAGE_VALUE_FLAGS:
                skip_next = True
                continue
            if token.startswith("-"):
                continue
            return token
    return None


def _present_image(requested: str, docker: list[str]) -> str | None:
    """Return requested image if local, else another tag of the same repository. Never pull."""
    inspect = _run([*docker, "image", "inspect", requested], timeout=20)
    if inspect.returncode == 0:
        return requested
    repo = requested.rsplit(":", 1)[0]
    listed = _run([*docker, "images", "--format", "{{.Repository}}:{{.Tag}}", repo], timeout=20)
    for line in (listed.stdout or "").splitlines():
        tag = line.strip()
        if tag and not tag.endswith(":<none>"):
            return tag
    return None


def _present_named_image(docker: list[str], needle: str) -> str | None:
    """Return any local image whose name contains needle. Never pull."""
    listed = _run([*docker, "images", "--format", "{{.Repository}}:{{.Tag}}"], timeout=20)
    for line in (listed.stdout or "").splitlines():
        tag = line.strip()
        if needle.lower() in tag.lower() and not tag.endswith(":<none>"):
            return tag
    return None


def _docker_run(docker: list[str], extra: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return _run([*docker, "run", "--rm", "--pull=never", *extra], timeout=timeout)


def probe_catia_electrical(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Join KiCad CLI, KiCadStepUp tree, and FreeCADCmd in one check."""
    del results
    label = "CATIA electrical→KiCad+KiCadStepUp+FreeCAD"
    kicad = shutil.which("kicad-cli") or shutil.which("kicad")
    freecad = shutil.which("FreeCADCmd") or shutil.which("freecad")
    if not kicad or not freecad:
        return _failed(label, "kicad-cli and FreeCADCmd are required")
    stepup = _receipt_locator("kicad-stepup")
    if not stepup:
        return _failed(label, "kicad-stepup receipt is missing")
    root = Path(stepup)
    marker = next((root / name for name in ("InitGui.py", "kicadStepUpCMD.py", "README.md") if (root / name).is_file()), None)
    if marker is None:
        return _failed(label, f"KiCadStepUp files missing under {stepup}")
    try:
        version = _run([kicad, "version"] if Path(kicad).name == "kicad-cli" else [kicad, "--version"], timeout=30)
        cad = _run([freecad, "-c", "print(42)"], timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _failed(label, str(exc))
    kicad_out = (version.stdout or version.stderr or "").strip().splitlines()
    if version.returncode != 0 or not kicad_out:
        return _failed(label, "kicad version failed")
    if cad.returncode != 0 or "42" not in (cad.stdout or ""):
        return _failed(label, "FreeCADCmd -c failed")
    return _covered(label, f"kicad {kicad_out[0]}; {marker.name}; FreeCADCmd 42")


def probe_tosca(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Load TopOpt.jl and print Code_Aster as_run usage from a local image."""
    del results
    label = "Tosca→TopOpt.jl+Code_Aster"
    from .hello_probes import probe_topopt_jl

    topopt = probe_topopt_jl()
    if topopt.get("status") != "ok":
        return _failed(label, f"TopOpt.jl {topopt.get('status')}: {topopt.get('message')}")
    usage = _code_aster_usage()
    if usage is None:
        return _failed(label, "Code_Aster as_run --help did not run on a local image")
    return _covered(label, f"{topopt.get('message')}; as_run usage")


def probe_abaqus_cae(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Require a local SALOME-Meca image and Code_Aster as_run usage."""
    del results
    label = "Abaqus CAE→SALOME-Meca+Code_Aster"
    docker = _docker_argv()
    if not docker:
        return _failed(label, "docker is required")
    requested = _image_from_wrapper(("salome",))
    present = _present_image(requested, docker) if requested else None
    if present is None:
        present = _present_named_image(docker, "salome")
    if not present:
        return _failed(
            label,
            f"no local SALOME image (wrapper {requested!r}; GHCR latest requires auth and was not pulled)",
        )
    usage = _code_aster_usage()
    if usage is None:
        return _failed(label, "Code_Aster as_run --help did not run on a local image")
    return _covered(label, f"salome image {present}; as_run usage")


def _code_aster_usage() -> str | None:
    docker = _docker_argv()
    if not docker:
        return None
    requested = _image_from_wrapper(("as_run", "aster")) or "negetem/codeaster:latest"
    present = _present_image(requested, docker)
    if not present:
        return None
    try:
        help_proc = _docker_run(docker, ["-w", "/opt/aster", present, "--help"], timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (help_proc.stdout or "") + (help_proc.stderr or "")
    if "as_run" not in text and "Functions" not in text:
        return None
    return text


def probe_enovia(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Join Git LFS, psql, ERPNext tree, and Nextcloud php -v on a local image."""
    del results
    label = "ENOVIA→Git LFS+PostgreSQL+Nextcloud+ERPNext"
    git_lfs = shutil.which("git-lfs")
    psql = shutil.which("psql")
    if not git_lfs or not psql:
        return _failed(label, "git-lfs and psql are required")
    erpnext = _receipt_locator("erpnext")
    if not erpnext:
        return _failed(label, "erpnext receipt is missing")
    root = Path(erpnext)
    marker = next((root / rel for rel in ("erpnext/__init__.py", "erpnext/hooks.py") if (root / rel).is_file()), None)
    if marker is None:
        return _failed(label, f"ERPNext files missing under {erpnext}")
    docker = _docker_argv()
    if not docker:
        return _failed(label, "docker is required")
    requested = _image_from_wrapper(("nextcloud",))
    if not requested:
        return _failed(label, "nextcloud wrapper does not name a docker image")
    present = _present_image(requested, docker)
    if not present:
        return _failed(label, f"Nextcloud image {requested} is not present locally")
    try:
        lfs = _run([git_lfs, "version"], timeout=20)
        postgres = _run([psql, "--version"], timeout=20)
        php = _docker_run(docker, ["--entrypoint", "php", present, "-v"], timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _failed(label, str(exc))
    if lfs.returncode != 0 or "git-lfs" not in ((lfs.stdout or "") + (lfs.stderr or "")).lower():
        return _failed(label, "git-lfs version failed")
    if postgres.returncode != 0 or "PostgreSQL" not in (postgres.stdout or ""):
        return _failed(label, "psql --version failed")
    if php.returncode != 0 or "PHP" not in ((php.stdout or "") + (php.stderr or "")):
        return _failed(label, "nextcloud php -v failed")
    return _covered(label, f"git-lfs; {postgres.stdout.strip().splitlines()[0]}; {marker.name}; PHP in {present}")


def _opensearch_and_superset(label: str) -> dict[str, Any]:
    docker = _docker_argv()
    if not docker:
        return _failed(label, "docker is required")
    requested = _image_from_wrapper(("opensearch",))
    if not requested:
        return _failed(label, "opensearch wrapper does not name a docker image")
    present = _present_image(requested, docker)
    if not present:
        return _failed(label, f"OpenSearch image {requested} is not present locally")
    env = _pythonpath(_receipt_locator("apache-superset"))
    try:
        version = _docker_run(
            docker,
            [
                "--entrypoint",
                "bash",
                present,
                "-lc",
                "/usr/share/opensearch/bin/opensearch --version",
            ],
            timeout=60,
        )
        superset = _run(
            [sys.executable, "-c", "import superset; print(getattr(superset, '__version__', 'ok'))"],
            env=env,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _failed(label, str(exc))
    banner = (version.stdout or "") + (version.stderr or "")
    if "Version:" not in banner:
        return _failed(label, f"opensearch --version failed on {present}")
    if superset.returncode != 0:
        detail = (superset.stderr or superset.stdout or "superset import failed").strip().splitlines()
        return _failed(label, detail[-1] if detail else "superset import failed")
    version_line = next((line.strip() for line in banner.splitlines() if "Version:" in line), "Version")
    return _covered(label, f"{version_line} via {present}; superset import")


def probe_netvibes(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """OpenSearch --version on a local image and import Apache Superset."""
    del results
    return _opensearch_and_superset("Netvibes→OpenSearch+Superset")


def probe_exalead(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Same OpenSearch+Superset check as Netvibes; Exalead maps to the same pair."""
    del results
    return _opensearch_and_superset("Exalead→OpenSearch+Superset")
