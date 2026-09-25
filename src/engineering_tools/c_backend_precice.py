"""preCICE coupling backend for C orchestration.

Comments for other agents: this module writes a preCICE 2 configuration and
locates a coupler binary. It is not the FSI solver and it is not the C
language runtime. CalculiX and OpenFOAM are the participants; they load the
XML and exchange Displacement and Traction through preCICE. Generation is
pure string assembly from the policy dict. It never reads an on-disk
precice-config.xml as input.

The PATH entry named `precice` is a CI alias, not the official driver.
Installs ship `precice-tools` (and sometimes `binprecice`). Do not add
`<solver:…/>` children: preCICE has no such element, and naming CalculiX or
OpenFOAM inside the config would pretend this process is those solvers.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


# Official coupler names first. `precice` is last so a CI stub still resolves
# when the real binaries are absent. This tuple is a lookup list, not a
# command this module should turn into an FSI solve.
_COUPLER_NAMES = ("precice-tools", "binprecice", "precice")

# Residual limit inside one implicit window. Not a stress band and not
# max_iterations. preCICE compares this to the relative change of the named data.
_RELATIVE_CONVERGENCE_LIMIT = "1.0e-4"

# preCICE (and the CI participant fakes) print this once per completed window.
# Counting it is how C records per-step convergence without a standalone
# `precice` driver process. Do not treat process exit 0 alone as residual ok.
WINDOW_COMPLETED_MARK = "Time window completed"


def default_policy() -> dict[str, Any]:
    """Return the default C coupling policy for Solid/Fluid FSI.

    `solver` on each participant is session metadata for the façade. It is
    not written into the XML. `max_time_windows` is how many coupling windows
    to run. It is not `max_iterations` (iterations inside one window) and it
    is not `time_window * max_iterations`.
    """
    return {
        "participants": [
            {"name": "Solid", "solver": "calculix"},
            {"name": "Fluid", "solver": "openfoam"},
        ],
        "mesh_name": "interface",
        "read_by_fluid": "Displacement",
        "read_by_solid": "Traction",
        "time_window": 0.01,
        "max_iterations": 100,
        "max_time_windows": 2,
    }


def find_precice() -> Path | None:
    """Return the first coupler binary on PATH, or None.

    Order: `precice-tools`, then `binprecice`, then `precice`. The last name
    is a CI alias, not the official driver. Callers use the path as an
    availability check. Participants consume the generated XML; this module
    must not be the FSI solver.
    """
    for name in _COUPLER_NAMES:
        found = shutil.which(name)
        if found is not None:
            return Path(found)
    return None


def generate_precice_config(policy: dict[str, Any]) -> str:
    """Build a preCICE 2 configuration from a coupling policy dict.

    Solid provides mesh `mesh_name` and writes Displacement, reads Traction.
    Fluid provides `{mesh_name}-fluid`, writes Traction, reads Displacement,
    and nearest-neighbor-maps between those meshes. Exchanges both name the
    Solid mesh, which is the mesh the communicated data lives on. Vector
    Traction matches vector Displacement; a scalar would drop direction.
    Dimensions are 3 because the damper interface displacement has three
    components. No `<solver:…/>` tags.
    """
    participants: list[dict[str, str]] = policy["participants"]
    mesh_name = str(policy["mesh_name"])
    read_by_fluid = str(policy["read_by_fluid"])
    read_by_solid = str(policy["read_by_solid"])
    time_window = float(policy["time_window"])
    max_iterations = int(policy["max_iterations"])
    max_time_windows = int(policy["max_time_windows"])

    solid = participants[0]
    fluid = participants[1]
    solid_name = escape(solid["name"])
    fluid_name = escape(fluid["name"])
    mesh = escape(mesh_name)
    # Fluid's own mesh. Mapping needs a second mesh; exchanges stay on `mesh`.
    fluid_mesh = escape(f"{mesh_name}-fluid")
    # read_by_* is what each side consumes; the other participant writes it.
    displacement = escape(read_by_fluid)
    traction = escape(read_by_solid)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<precice-configuration>",
        f'  <data:vector name="{displacement}"/>',
        f'  <data:vector name="{traction}"/>',
        f'  <mesh name="{mesh}" dimensions="3">',
        f'    <use-data name="{displacement}"/>',
        f'    <use-data name="{traction}"/>',
        "  </mesh>",
        f'  <mesh name="{fluid_mesh}" dimensions="3">',
        f'    <use-data name="{displacement}"/>',
        f'    <use-data name="{traction}"/>',
        "  </mesh>",
        f'  <participant name="{solid_name}">',
        f'    <use-mesh name="{mesh}" provide="yes"/>',
        f'    <use-mesh name="{fluid_mesh}" from="{fluid_name}"/>',
        f'    <write-data name="{displacement}" mesh="{mesh}"/>',
        f'    <read-data name="{traction}" mesh="{mesh}"/>',
        "  </participant>",
        f'  <participant name="{fluid_name}">',
        f'    <use-mesh name="{fluid_mesh}" provide="yes"/>',
        f'    <use-mesh name="{mesh}" from="{solid_name}"/>',
        f'    <write-data name="{traction}" mesh="{fluid_mesh}"/>',
        f'    <read-data name="{displacement}" mesh="{fluid_mesh}"/>',
        (
            f'    <mapping:nearest-neighbor direction="write" '
            f'from="{fluid_mesh}" to="{mesh}" constraint="conservative"/>'
        ),
        (
            f'    <mapping:nearest-neighbor direction="read" '
            f'from="{mesh}" to="{fluid_mesh}" constraint="consistent"/>'
        ),
        "  </participant>",
        (
            f'  <m2n:sockets acceptor="{fluid_name}" connector="{solid_name}" '
            f'exchange-directory="."/>'
        ),
        "  <coupling-scheme:serial-implicit>",
        f'    <participants first="{solid_name}" second="{fluid_name}"/>',
        f'    <max-time-windows value="{max_time_windows}"/>',
        f'    <time-window-size value="{time_window}"/>',
        f'    <max-iterations value="{max_iterations}"/>',
        (
            f'    <relative-convergence-measure data="{displacement}" '
            f'mesh="{mesh}" limit="{_RELATIVE_CONVERGENCE_LIMIT}"/>'
        ),
        (
            f'    <exchange data="{traction}" mesh="{mesh}" '
            f'from="{fluid_name}" to="{solid_name}"/>'
        ),
        (
            f'    <exchange data="{displacement}" mesh="{mesh}" '
            f'from="{solid_name}" to="{fluid_name}"/>'
        ),
        "  </coupling-scheme:serial-implicit>",
        "</precice-configuration>",
        "",
    ]
    return "\n".join(lines)


def _count_completed_windows(text: str) -> int:
    """How many coupling windows the log claims finished."""
    return text.count(WINDOW_COMPLETED_MARK)


def run_coupled_participants(
    *,
    solid_argv: list[str],
    solid_cwd: Path,
    fluid_argv: list[str],
    fluid_cwd: Path,
    n_windows: int,
) -> dict[str, Any]:
    """Start Solid and Fluid together. They, not this process, talk to preCICE.

    Agents: both Popen calls happen before either wait. Logs go to files so
    the pipes cannot fill. Exit 0 on both is not enough: each required
    window must appear as WINDOW_COMPLETED_MARK in the combined logs.
    Do not spawn a third `precice` process here.
    """
    solid_cwd = Path(solid_cwd)
    fluid_cwd = Path(fluid_cwd)
    solid_log_path = solid_cwd / "participant.log"
    fluid_log_path = fluid_cwd / "participant.log"
    try:
        solid_log = solid_log_path.open("w", encoding="utf-8")
        fluid_log = fluid_log_path.open("w", encoding="utf-8")
    except OSError:
        return {"ok": False, "steps": [], "detail": "could not open participant logs"}
    try:
        solid_proc = subprocess.Popen(
            solid_argv,
            cwd=solid_cwd,
            stdout=solid_log,
            stderr=subprocess.STDOUT,
        )
        fluid_proc = subprocess.Popen(
            fluid_argv,
            cwd=fluid_cwd,
            stdout=fluid_log,
            stderr=subprocess.STDOUT,
        )
    except OSError as exc:
        solid_log.close()
        fluid_log.close()
        return {"ok": False, "steps": [], "detail": str(exc)}
    try:
        solid_code = solid_proc.wait(timeout=180)
        fluid_code = fluid_proc.wait(timeout=180)
    except subprocess.TimeoutExpired:
        solid_proc.kill()
        fluid_proc.kill()
        solid_proc.wait(timeout=5)
        fluid_proc.wait(timeout=5)
        solid_log.close()
        fluid_log.close()
        return {"ok": False, "steps": [], "detail": "participant timeout"}
    solid_log.close()
    fluid_log.close()
    combined = solid_log_path.read_text(encoding="utf-8", errors="replace")
    combined += fluid_log_path.read_text(encoding="utf-8", errors="replace")
    completed = _count_completed_windows(combined)
    steps = [{"index": index, "converged": index < completed} for index in range(n_windows)]
    ok = solid_code == 0 and fluid_code == 0 and completed >= n_windows
    return {"ok": ok, "steps": steps, "completed_windows": completed}


def run_step(config_path: Path, step: int) -> bool:
    """Deprecated: a standalone `precice` process is not the FSI solve.

    Agents: the façade must not call this. Kept so old tests that patch
    `run_step` still import. Always returns False so a mistaken caller
    cannot green-wash coupling.
    """
    del config_path, step
    return False
