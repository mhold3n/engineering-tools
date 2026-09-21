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


def probe_mine_scheduling(project: str | Path | None = None) -> dict[str, Any]:
    from .geovia_models import mine_schedule

    work = _work_dir(project, "geovia-mine-hello", "etools-mine-")
    result = mine_schedule([{"tonnage": 0.5}, {"tonnage": 0.5}], periods=2)
    out = work / "schedule.json"
    out.write_text(str(result), encoding="utf-8")
    if result["scheduled"] != 2 or result["objective"] != 1.0:
        return _result(
            "first-party-mine-scheduling-model",
            "First-party mine scheduling model",
            "broken",
            "mine schedule toy model produced unexpected objective",
            workdir=work,
            outputs=[str(out)],
        )
    return _result(
        "first-party-mine-scheduling-model",
        "First-party mine scheduling model",
        "ok",
        "mine schedule toy model ok",
        workdir=work,
        outputs=[str(out)],
        returncode=0,
    )


def probe_pit_optimization(project: str | Path | None = None) -> dict[str, Any]:
    from .geovia_models import pit_optimize

    work = _work_dir(project, "geovia-pit-hello", "etools-pit-")
    result = pit_optimize([{"value": 5, "cost": 1}, {"value": 1, "cost": 4}], cutoff=0.0)
    out = work / "pit.json"
    out.write_text(str(result), encoding="utf-8")
    if result["count"] != 1 or result["objective"] != 4.0:
        return _result(
            "first-party-pit-optimization-model",
            "First-party pit optimization model",
            "broken",
            "pit optimize toy model produced unexpected objective",
            workdir=work,
            outputs=[str(out)],
        )
    return _result(
        "first-party-pit-optimization-model",
        "First-party pit optimization model",
        "ok",
        "pit optimize toy model ok",
        workdir=work,
        outputs=[str(out)],
        returncode=0,
    )


def make_binary_probe(
    component_id: str,
    name: str,
    binaries: tuple[str, ...],
    credit: str,
):
    """Build a missing/ok probe that only checks locator presence (independent smoke)."""

    def probe(project: str | Path | None = None) -> dict[str, Any]:
        for binary in binaries:
            found = shutil.which(binary)
            if found:
                return _result(
                    component_id,
                    name,
                    "ok",
                    f"{name} locator ok via {found}",
                    locator=found,
                    credit=credit,
                    returncode=0,
                )
        return _result(
            component_id,
            name,
            "missing",
            f"{name} binaries not found: {', '.join(binaries)}",
        )

    return probe


def make_pip_module_probe(component_id: str, name: str, module: str, credit: str):
    """Probe a pip-installed module using the receipt target directory on sys.path."""

    def probe(project: str | Path | None = None) -> dict[str, Any]:
        from .verification import installation_for, load_installations
        import sys

        receipt = installation_for(component_id, load_installations())
        locator = receipt.get("locator") if receipt else None
        if locator:
            sys.path.insert(0, locator)
        try:
            __import__(module)
        except ImportError:
            return _result(
                component_id,
                name,
                "missing",
                f"Python module {module!r} not importable",
                locator=locator,
                credit=credit,
            )
        return _result(
            component_id,
            name,
            "ok",
            f"Python module {module!r} import ok",
            locator=locator,
            credit=credit,
            returncode=0,
        )

    return probe


COMPONENT_PROBES = {
    "calculix-hello-beam": probe_calculix,
    "freecad-hello-box": probe_freecad,
    "openfoam-block-mesh": probe_openfoam,
    "first-party-mine-scheduling-model-hello": probe_mine_scheduling,
    "first-party-pit-optimization-model-hello": probe_pit_optimization,
    "pyomo-hello": make_pip_module_probe("pyomo", "Pyomo", "pyomo", "Pyomo (BSD) - https://www.pyomo.org/"),
    "openmdao-hello": make_pip_module_probe("openmdao", "OpenMDAO", "openmdao", "OpenMDAO (Apache-2.0) - https://openmdao.org/"),
    "dvc-hello": make_binary_probe("dvc", "DVC", ("dvc",), "DVC (Apache-2.0) - https://dvc.org/"),
    "ase-hello": make_pip_module_probe("ase", "ASE", "ase", "ASE (LGPL) - https://wiki.fysik.dtu.dk/ase/"),
    "rdkit-hello": make_pip_module_probe("rdkit", "RDKit", "rdkit", "RDKit (BSD) - https://www.rdkit.org/"),
    "gempy-hello": make_pip_module_probe("gempy", "GemPy", "gempy", "GemPy (LGPL) - https://www.gempy.org/"),
    "pylife-hello": make_pip_module_probe("pylife", "pyLife", "pylife", "pyLife (BSD) - https://github.com/boschresearch/pylife"),
    "blender-hello": make_binary_probe("blender", "Blender", ("blender",), "Blender (GPL) - https://www.blender.org/"),
    "librecad-hello": make_binary_probe("librecad", "LibreCAD", ("librecad",), "LibreCAD (GPL) - https://librecad.org/"),
    "kicad-hello": make_binary_probe("kicad", "KiCad", ("kicad", "kicad-cli"), "KiCad (GPL) - https://www.kicad.org/"),
    "git-lfs-hello": make_binary_probe("git-lfs", "Git LFS", ("git-lfs",), "Git LFS (MIT) - https://git-lfs.com/"),
    "postgresql-hello": make_binary_probe("postgresql", "PostgreSQL", ("psql",), "PostgreSQL (PostgreSQL) - https://www.postgresql.org/"),
    "paraview-hello": make_binary_probe("paraview", "ParaView", ("paraview", "pvpython"), "ParaView (BSD) - https://www.paraview.org/"),
    "qgis-hello": make_binary_probe("qgis", "QGIS", ("qgis",), "QGIS (GPL) - https://qgis.org/"),
    "openmodelica-hello": make_binary_probe('openmodelica', 'OpenModelica', ('omc',), "OpenModelica upstream"),
    "open-cascade-technology-hello": make_binary_probe('open-cascade-technology', 'Open CASCADE Technology', ('DRAWEXE',), "Open CASCADE Technology upstream"),
    "salome-meca-hello": make_binary_probe('salome-meca', 'SALOME-Meca', ('salome',), "SALOME-Meca upstream"),
    "code-aster-hello": make_binary_probe('code-aster', 'Code_Aster', ('as_run', 'aster'), "Code_Aster upstream"),
    "openlb-hello": make_binary_probe('openlb', 'OpenLB', ('openlb',), "OpenLB upstream"),
    "openems-hello": make_binary_probe('openems', 'openEMS', ('openEMS',), "openEMS upstream"),
    "elmer-fem-hello": make_binary_probe('elmer-fem', 'Elmer FEM', ('ElmerSolver',), "Elmer FEM upstream"),
    "project-chrono-hello": make_binary_probe('project-chrono', 'Project Chrono', ('chrono',), "Project Chrono upstream"),
    "opencfs-hello": make_binary_probe('opencfs', 'openCFS', ('cfs',), "openCFS upstream"),
    "topopt-jl-hello": make_pip_module_probe('topopt-jl', 'TopOpt.jl', 'TopOpt', "TopOpt.jl upstream"),
    "freecad-cam-hello": make_binary_probe('freecad-cam', 'FreeCAD CAM', ('FreeCADCmd', 'freecad'), "FreeCAD CAM upstream"),
    "qelectrotech-hello": make_binary_probe('qelectrotech', 'QElectroTech', ('qelectrotech',), "QElectroTech upstream"),
    "kicad-stepup-hello": make_pip_module_probe('kicad-stepup', 'KiCadStepUp', 'kicadStepUpMod', "KiCadStepUp upstream"),
    "nextcloud-hello": make_binary_probe('nextcloud', 'Nextcloud', ('nextcloud',), "Nextcloud upstream"),
    "erpnext-hello": make_pip_module_probe('erpnext', 'ERPNext', 'erpnext', "ERPNext upstream"),
    "erpnext-manufacturing-hello": make_pip_module_probe('erpnext-manufacturing', 'ERPNext Manufacturing', 'erpnext', "ERPNext Manufacturing upstream"),
    "frepple-hello": make_pip_module_probe('frepple', 'frePPLe', 'frepple', "frePPLe upstream"),
    "ros-2-hello": make_binary_probe('ros-2', 'ROS 2', ('ros2',), "ROS 2 upstream"),
    "moveit-hello": make_binary_probe('moveit', 'MoveIt', ('moveit', 'ros2'), "MoveIt upstream"),
    "gazebo-hello": make_binary_probe('gazebo', 'Gazebo', ('gz', 'gazebo'), "Gazebo upstream"),
    "opensearch-hello": make_binary_probe('opensearch', 'OpenSearch', ('opensearch',), "OpenSearch upstream"),
    "apache-superset-hello": make_pip_module_probe('apache-superset', 'Apache Superset', 'apache_superset', "Apache Superset upstream"),
    "lammps-hello": make_binary_probe('lammps', 'LAMMPS', ('lmp', 'lammps'), "LAMMPS upstream"),
    "quantum-espresso-hello": make_binary_probe('quantum-espresso', 'Quantum ESPRESSO', ('pw.x',), "Quantum ESPRESSO upstream"),
    "gromacs-hello": make_binary_probe('gromacs', 'GROMACS', ('gmx',), "GROMACS upstream"),
    "autodock-vina-hello": make_binary_probe('autodock-vina', 'AutoDock Vina', ('vina',), "AutoDock Vina upstream"),
    "elabftw-hello": make_binary_probe('elabftw', 'eLabFTW', ('elabftw',), "eLabFTW upstream"),
    "senaite-hello": make_pip_module_probe('senaite', 'SENAITE', 'senaite.core', "SENAITE upstream"),
    "psi4-hello": make_pip_module_probe('psi4', 'Psi4', 'psi4', "Psi4 upstream"),
    "openstack-hello": make_binary_probe('openstack', 'OpenStack', ('openstack',), "OpenStack upstream"),

    "sweet-home-3d-hello": make_binary_probe('sweet-home-3d', 'Sweet Home 3D', ('sweethome3d',), "Sweet Home 3D upstream"),
    "knime-analytics-platform-hello": make_binary_probe('knime-analytics-platform', 'KNIME Analytics Platform', ('knime',), "KNIME Analytics Platform upstream"),
    "eclipse-papyrus-hello": make_binary_probe('eclipse-papyrus', 'Eclipse Papyrus', ('papyrus',), "Eclipse Papyrus upstream"),
    "libreclinica-hello": make_binary_probe('libreclinica', 'LibreClinica', ('libreclinica',), "LibreClinica upstream"),
}
